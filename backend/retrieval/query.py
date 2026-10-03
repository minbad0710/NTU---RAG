"""Query understanding: intent rules and topic extraction (rule-based), plus optional rewrite and
decomposition with a small local LLM served by Ollama."""
import functools
import json
import os
import re
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5:3b")

# checked in this order: "give me an exam question" is generate, "which exams asked" is past_paper
GENERATE_RE = re.compile(  # bare "generate"/"practice" also appear in normal questions ("timers generate interrupts")
    r"\b(quiz me|test me|mock (exam|test|paper|questions?)|"
    r"(generate|practi[cs]e|give|make|set|create)\b.{0,40}\b(questions?|exercises?|quiz))\b",
    re.I,
)
PAST_RE = re.compile(
    r"\b(past[- ]?(year|paper)s?|previous (years?|exams?|papers?)|pyp|in the (exam|finals?)|come out|came out|"
    r"which (exams?|papers?)|have they asked|asked (us|in))\b",
    re.I,
)
# with a past-paper cue, only these mean "write new questions" ("practice questions like the past papers");
# "give me / show me past-year questions" asks to find the real ones
NEW_QUESTIONS_RE = re.compile(
    r"\b(generate|create|make|write|new|practi[cs]e|similar|like|style|based on|mock|quiz me|test me)\b", re.I)
# request wording that pulls retrieval toward intro/assessment slides; removed before searching
REQUEST_WORDS_RE = re.compile(
    r"\b(exam-style|marking scheme|generate|practi[cs]e|quiz|test|mock|give|show|find|make|set|create|me|us|we|i|"
    r"they|past|previous|year|years|paper|papers|exams?|finals?|questions?|common|asked?|ever|come|came|out|which|"
    r"have|has|did|can|you|want|to|before|where|had|some|a|an|the|on|about|in|with|\d+)\b",
    re.I,
)


STOPWORDS = set(
    "what is are was the a an of in on for to how do does did i we you it its this that these and or with about "
    "me tell give explain overview everything all why when which can could should would will be my our there "
    "their from by as at into".split()
)


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def content_words(text):
    return [w for w in words(text) if w not in STOPWORDS]


MULTIPART_RE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|difference|differ|and (how|why|what|when|which|where|then))\b", re.I
)


def looks_multipart(question):
    return bool(MULTIPART_RE.search(question))


# --- "solve" intent: a full solution to a specific exercise (past-year reference, generated question, pasted) ---
SOLVE_RE = re.compile(
    r"\b(solve|solution|work(ed)? out|answers? (to|for|of|this|that|it)|what('s| is) the answer|"
    r"how (do|would|should|can) (i|we|you) (solve|answer|do|approach)|help me (solve|answer|with))\b",
    re.I,
)
# "AY1516", "AY2015/16", "2015/16"
YEAR_RE = re.compile(r"\bAY\s?(?:20)?(\d{2})\s?/?\s?(?:20)?(\d{2})\b|\b20(\d{2})\s?/\s?(?:20)?(\d{2})\b", re.I)
SEM_RE = re.compile(r"\b(?:S|sem(?:ester)?)\s?([12])\b", re.I)
# "Q4(a)", "Q4a", "Question 3(c)", "Q1(15)"
QREF_RE = re.compile(r"\bQ(?:uestion)?\s?(\d{1,2})(?:\s*\(?\s*([a-h]|\d{1,2})\b\s*\)?)?", re.I)
EXERCISE_RE = re.compile(r"\(\s*\d{1,2}(?:\.\d)?\s*marks?\s*\)|(?:^|\s)[B-E][.)]\s.*(?:^|\s)[C-E][.)]\s", re.I | re.S)


# tutor mode for exercises: a hint (nudge, no answer) or the full worked solution (default)
HINT_RE = re.compile(  # a request for a hint, not the word in passing ("the hint of a hash function")
    r"(\b(give|want|need|get|have|another|more|next|one|small|some)\s+(me\s+)?(a\s+|another\s+|more\s+|small\s+)?"
    r"(hints?|clue|nudge)\b|^\W*(hints?|clue|nudge)\b|\b(hints?|clue|nudge)\s+(please|pls|for|on)\b|"
    r"^\W*(where|how) (do|should|can) i (start|begin)\W*$)",
    re.I,
)
FULL_RE = re.compile(r"\b(full (solution|answer|explanation|working)|complete (solution|answer)|"
                     r"show (me )?(the )?(solution|answer|working|steps)|just (tell|give) me the answer)\b", re.I)


def tutor_mode(text):
    return "hint" if HINT_RE.search(text) and not FULL_RE.search(text) else "full"


def is_follow_up(text):
    """'another hint' / 'show me the full solution' with no new exercise: applies to the last exercise."""
    return bool(HINT_RE.search(text) or FULL_RE.search(text)) and len(text) < 150 and not YEAR_RE.search(text) \
        and not QREF_RE.search(text)


def paper_ref(text):
    """{'year': 'AY2015/16', 'sem': 2 or None, 'q': 4, 'part': 'a' or None} if text names a past-paper question."""
    y, q = YEAR_RE.search(text), QREF_RE.search(text)
    if not (y and q):
        return None
    y1, y2 = (y[1], y[2]) if y[1] else (y[3], y[4])
    s = SEM_RE.search(text)
    return {"year": f"AY20{y1}/{y2}", "sem": int(s[1]) if s else None, "q": int(q[1]),
            "part": q[2].lower() if q[2] else None}


def generated_ref(text):
    """Question number in "solve question 2" / "answer Q1", for questions generated earlier in the chat."""
    q = QREF_RE.search(text)
    wants = SOLVE_RE.search(text) or HINT_RE.search(text) or FULL_RE.search(text)
    return int(q[1]) if q and wants and not YEAR_RE.search(text) else None


def looks_like_exercise(text):
    """Pasted exam-style text: marks like "(5 marks)" or MCQ options A. B. C. ..."""
    return len(text) > 80 and bool(EXERCISE_RE.search(text))


def parse(question):
    """Returns (intent, topic). intent is "solve", "generate", "past_paper" or "qa"; topic is what to search for
    (for "solve", the exercise text; a referenced question is looked up later)."""
    if paper_ref(question) or generated_ref(question) or looks_like_exercise(question) or is_follow_up(question) \
            or (SOLVE_RE.search(question) and len(question) > 150):
        # drop a leading "solve this question:" so only the exercise is searched
        return "solve", re.sub(r"^\s*(please\s+)?(solve|answer|(give me |can i have |i need )?an? hint)[^:\n]{0,40}:\s*",
                               "", question, flags=re.I)
    if PAST_RE.search(question) and not NEW_QUESTIONS_RE.search(question):
        intent = "past_paper"  # "give me past-year questions on X": find them, don't write new ones
    elif GENERATE_RE.search(question):
        intent = "generate"
    elif PAST_RE.search(question):
        intent = "past_paper"
    else:
        return "qa", question
    topic = re.sub(r"\s+", " ", REQUEST_WORDS_RE.sub(" ", question)).strip(" ?.,!-")
    return intent, topic or question


REWRITE_PROMPT = """You write search queries for university computer science lecture slides \
(algorithms, operating systems, software engineering, computer networks, microprocessors).

Rewrite the student's question as one short search query that uses the exact technical terms a lecturer \
would put on a slide: name the concept, algorithm, protocol or hardware module.
{decompose}Output only the queries, one per line. No numbering, no explanations.

Examples:
Question: cheapest way to connect all the towns with cables
minimum spanning tree Prim Kruskal algorithm
Question: why does my program crash when two threads update the same list
race condition critical section mutual exclusion
{decompose_example}
Question: {question}
"""
DECOMPOSE_RULE = (
    "Then, only if the question asks about two or more distinct things, add one more line per thing, "
    "each a short standalone search query.\n"
)
DECOMPOSE_EXAMPLE = """Question: how is TCP different from UDP and when do I use each
TCP versus UDP transport protocol comparison
TCP connection-oriented reliable transport
UDP connectionless datagram transport
"""


@functools.lru_cache(maxsize=1024)
def _generate(prompt, max_tokens=100):  # the cap stops rare runaway outputs
    options = {"temperature": 0, "num_predict": max_tokens}
    body = json.dumps({"model": LOCAL_MODEL, "prompt": prompt, "stream": False, "options": options})
    req = urllib.request.Request(f"{OLLAMA_URL}/api/generate", body.encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["response"]


REWRITES_PROMPT = """A student asked a broad question about a university computer science course. \
Rewrite it as 3 different questions. Each one must still ask about the WHOLE topic (do not split it into \
parts), phrased from a different angle:
1. a step-back question about the underlying concepts and principles behind the topic
2. the same question restated in the precise terms the lecture slides use
3. a question about the topic's key mechanisms, how they work, and their trade-offs
Stay within what the course's lecture slides cover (listed below).
Output only the 3 questions, one per line. No numbering, no explanations.

Lecture slides on this topic:
{slides}
Broad question: {question}
"""


def rewrites(question, slides, n=3):
    """Rewrite a broad question into n whole-topic questions from different angles (step-back style)."""
    prompt = REWRITES_PROMPT.format(question=question, slides="\n".join(f"- {s}" for s in slides))
    text = re.sub(r"<think>.*?</think>", "", _generate(prompt, max_tokens=200), flags=re.S)
    lines = [re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", l).strip() for l in text.splitlines()]
    return [l for l in lines if len(l) > 10 and not l.lower().startswith("broad question")][:n]


def expand(question, decompose=False):
    """Extra search queries: a rewrite in course terms, plus sub-queries for multi-part questions."""
    prompt = REWRITE_PROMPT.format(
        question=question,
        decompose=DECOMPOSE_RULE if decompose else "",
        decompose_example=DECOMPOSE_EXAMPLE if decompose else "",
    )
    text = re.sub(r"<think>.*?</think>", "", _generate(prompt), flags=re.S)
    lines = [re.sub(r"^\s*(?:[-*]|\d+[.)]|question:)\s*", "", l, flags=re.I).strip() for l in text.splitlines()]
    lines = [l for l in lines if l and len(l) < 200]
    return lines[:4] if decompose else lines[:1]

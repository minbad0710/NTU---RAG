"""Corrective answer loop for Q&A and solve requests, as a LangGraph state graph.

    retrieve -> grade_documents --(some relevant)--> generate -> check_hallucination -> check_answer -> END
                     |                                  ^     |       | (not grounded:   | (hint)    | (doesn't
                     | (none relevant)                  |     |       |  retry once)     +--> END    |  answer)
                     |                                  +-----|-------+                              |
                     +--------------> web_search <------------+--- (still not grounded) -------------+
                                       / model_answer

Sources are tried in order: course slides, then one round of web search, then (rarely) the model's own knowledge.
Claude Haiku does the small tasks (grading chunks, fetching web results, the checks); CLAUDE_MODEL writes answers.
The checks run one after the other: the answers-the-question check only runs on an answer that passed the
hallucination check. Each answer attempt can be streamed to the caller as it is written (see Draft).
"""
import json
import re
from typing import TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from backend import config as settings  # "config" is the LangGraph run config in node signatures
from backend import llm
from backend.answering import figures, prompts

SMALL_MODEL = "claude-haiku-4-5"
IMAGE_CHECK_MODEL = settings.CLAUDE_MODEL  # hallucination check when slide images are attached (see check_hallucination)
# Haiku uses the basic tool variant. 5 searches gave the same accuracy on eval/datasets/solve_set.jsonl at ~2x the cost.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 3}
WEB_REPORT_TOKENS = 8000  # detailed excerpts, so the method is in the documents the answer is checked against
MAX_GENERATE_RETRIES = 1  # regenerations per source after a failed hallucination check
GRADE_CHARS = 2400  # the whole chunk: the relevant slide can come after unrelated ones (800 missed CRC)


class State(TypedDict, total=False):
    question: str
    plan: dict
    history: list
    documents: list  # chunks the answer may use (slides, or one "web" document)
    source: str  # "slides" | "web" | "model"
    generation: str
    retries: int
    feedback: str
    web_sources: list
    trace: list
    slide_images: list  # labelled image blocks of figure slides used by the last slides-stage generation
    with_images: bool  # fallback mode: the slides attempt now includes figure images
    failed: str  # what the last check rejected: "" | "grounded" | "answer"


class Draft:
    """Streams each answer attempt to the caller while it is written, before it is checked. The first HOLD
    characters are held back so an INSUFFICIENT_CONTEXT reply is never shown; when a later attempt replaces a shown
    one, on_reset(reason) is called first."""
    HOLD = 200  # generate looks for INSUFFICIENT_CONTEXT in the first 200 characters

    def __init__(self, on_text, on_reset):
        self.on_text, self.on_reset = on_text, on_reset
        self.shown = False  # the current attempt has reached the caller

    def start(self, reason):
        if self.shown:
            self.on_reset(reason)
        self.buf, self.live, self.dead, self.shown = "", False, False, False

    def feed(self, chunk):
        if self.dead:
            return
        if self.live:
            self.on_text(chunk)
            return
        self.buf += chunk
        if settings.INSUFFICIENT in self.buf:
            self.dead = True
        elif len(self.buf) >= self.HOLD:
            self.live = self.shown = True
            self.on_text(self.buf)

    def finish(self):
        if not self.live and not self.dead and self.buf.strip():
            self.shown = True
            self.on_text(self.buf)


def small_json(system, content, schema, model=SMALL_MODEL):
    """A check with a structured (JSON schema) reply, Haiku by default; content is text or content blocks."""
    text = llm.ask(system, [{"role": "user", "content": content}], 4000, stream=False, model=model,
                    output_config={"format": {"type": "json_schema", "schema": schema}})
    return json.loads(text)


def asked(state):
    """What the student asked, for the grader, web search and checks (with their request when they sent a file,
    e.g. which sub-question of a photographed page they mean)."""
    plan = state["plan"]
    text = f"<exercise>\n{plan['exercise']}\n</exercise>" if plan["intent"] == "solve" else \
        f"<question>{state['question']}</question>"
    return text + (f"\n<student_request>{plan['instruction']}</student_request>" if plan.get("instruction") else "")


# --- nodes -------------------------------------------------------------------------------------------------------

def retrieve(state):
    return {"documents": state["plan"]["hits"], "source": "slides", "retries": 0, "feedback": "",
            "web_sources": [], "trace": [], "slide_images": [], "with_images": False, "failed": ""}


GRADE_SYSTEM = """You filter lecture excerpts before a tutor answers a student's question or exercise.
Be inclusive: keep every excerpt that could help, including background, definitions, related examples and the
method or formula the question needs, even if the answer still takes calculation or reasoning. Drop only
excerpts about a different topic. Return the numbers of the excerpts to keep (an empty list if none help)."""
GRADE_SCHEMA = {"type": "object", "properties": {"relevant": {"type": "array", "items": {"type": "integer"}}},
                "required": ["relevant"], "additionalProperties": False}


def grade_documents(state):
    docs = state["documents"]
    listing = "\n\n".join(f"[{i}] ({c['source']})\n{re.sub(r'\s+', ' ', c['text'])[:GRADE_CHARS]}"
                          for i, c in enumerate(docs, 1))
    keep = small_json(GRADE_SYSTEM, f"{asked(state)}\n\n<excerpts>\n{listing}\n</excerpts>", GRADE_SCHEMA)["relevant"]
    kept = [docs[i - 1] for i in sorted(set(keep)) if 1 <= i <= len(docs)]
    return {"documents": kept, "trace": state["trace"] + [f"grade: {len(kept)}/{len(docs)} slide chunks relevant"]}


WEB_SYSTEM = """Search the web to find what a tutor needs to answer the student's question or exercise.
Then report what the sources say, in detail, so the answer can be written from your report alone: for each useful
source give its URL and quote or closely paraphrase the relevant content - definitions, formulas, the steps of the
method, conditions and conventions, and any worked example. Aim for 800-1500 words. Do not answer from your own
knowledge and do not add anything the sources don't say. If nothing useful is found, reply with exactly NO_RESULTS."""


def web_search(state):
    text = llm.ask(WEB_SYSTEM, [{"role": "user", "content": asked(state)}], WEB_REPORT_TOKENS, stream=False,
                    model=SMALL_MODEL, tools=[WEB_SEARCH_TOOL],  # force a search: Haiku otherwise sometimes
                    tool_choice={"type": "tool", "name": "web_search"})  # answers from memory
    sources = list(llm.LAST_WEB_SOURCES)
    found = "NO_RESULTS" not in text[:50] and bool(text.strip())
    # the summary's citations live in API metadata, so list the pages explicitly for the answer to cite
    listing = "\n".join(f"- {t}: {u}" for t, u in sources[:10])
    doc = [{"kind": "web", "source": "web search results", "pages": "",
            "text": f"{text}\n\nPages found:\n{listing}"}] if found else []
    return {"documents": doc, "source": "web", "retries": 0, "feedback": "", "web_sources": sources,
            "trace": state["trace"] + [f"web search: {len(sources)} sources" + ("" if found else ", nothing useful")]}


RESET_REASONS = {"slides": "Trying again with the slide figures.", "web": "Answering from web search results instead.",
                 "model": "Answering from general knowledge instead."}


def generate(state, config: RunnableConfig):
    plan, source = state["plan"], state["source"]
    context = prompts.format_context(plan["exam_hits"] + state["documents"]) if source == "slides" else \
        prompts.format_context(state["documents"]) if source == "web" else ""
    hint = plan["intent"] == "solve" and plan["mode"] == "hint"
    task = f"<exercise>\n{plan['exercise']}\n</exercise>\n\n" + ("Give the hint." if hint else "Solve the exercise.") \
        if plan["intent"] == "solve" else f"Question: {state['question']}"
    content = (f"{context}\n\n" if context else "") + task
    if state.get("feedback"):
        content += f"\n\nA previous attempt was rejected: {state['feedback']} Fix this."
    system = prompts.system_prompt(plan["course"], plan["intent"], source, plan["mode"], plan["hint_level"])
    content = prompts.with_attachments(content, plan)
    want_images = source == "slides" and (settings.SLIDE_IMAGES_MODE == "always" or
                                          (settings.SLIDE_IMAGES_MODE == "fallback" and state.get("with_images")))
    images, used = figures.slide_image_blocks(state["documents"]) if want_images else ([], [])
    if images:  # figure slides from the kept chunks, before the excerpts
        content = images + (content if isinstance(content, list) else [{"type": "text", "text": content}])
    messages = state["history"] + [{"role": "user", "content": content}]
    draft, log = config["configurable"].get("draft"), config["configurable"].get("log")
    if draft:
        draft.start(state.get("feedback") and f"Revising the answer: {state['feedback']}" or RESET_REASONS[source])
        reply = llm.ask(system, messages, 16000, stream=True, on_text=draft.feed)
        draft.finish()
    else:
        reply = llm.ask(system, messages, 16000, stream=False)
    if log and source != "model" and settings.INSUFFICIENT not in reply[:200]:
        log("[Checking the answer against the sources...]")
    note =[f"slide images: {', '.join(used)}"] if used and not state.get("slide_images") else []
    if source != "model" and settings.INSUFFICIENT in reply[:200]:
        note.append(f"{source} answer: {settings.INSUFFICIENT}")
    return {"generation": reply, "trace": state["trace"] + note, "slide_images": images}


HALLUCINATION_SYSTEM = """You check a study assistant's answer for hallucinations.
grounded: true if every factual claim in the answer is supported by the provided documents. Calculations and
standard mathematical or logical steps don't need support, but must be correct. Citations must point to the
documents given. Judge ONLY whether what the answer says is supported - not whether it is complete: the answer
may be a hint that deliberately leaves out the working or the result. Before flagging a calculation, re-check it
yourself against the exercise. problem: if not grounded, one sentence naming the unsupported claim; otherwise
empty."""
HALLUCINATION_SCHEMA = {"type": "object", "properties": {"grounded": {"type": "boolean"}, "problem": {"type": "string"}},
                        "required": ["grounded", "problem"], "additionalProperties": False}


def grounded_verdict(state):
    """(ok, problem, trace note) of the hallucination check."""
    docs = prompts.format_context(state["documents"])
    text = f"<documents>\n{docs}\n</documents>\n\n{asked(state)}\n\n<answer>\n{state['generation']}\n</answer>"
    # the slide images the answer could use count as documents too (otherwise facts read off a diagram look
    # unsupported)
    images = (state.get("slide_images") or []) if state["source"] == "slides" else []
    # so is what the answer saw with the exercise: the scanned exam page with its figure, or the student's file
    # (without it, values read off an exam figure were rejected as unsupported, costing a whole regeneration)
    images = images + state["plan"]["attachments"]
    content = images + [{"type": "text", "text": "The images and files above (slide figures, the exam page or the "
                                                 "student's file) are part of the documents.\n\n" + text}] \
        if images else text
    # Haiku misread dense diagrams (said a graph slide showed no edge weights) and rejected correct answers;
    # with images attached, the check uses the same model that read them for the answer
    verdict = small_json(HALLUCINATION_SYSTEM, content, HALLUCINATION_SCHEMA,
                         model=IMAGE_CHECK_MODEL if images else SMALL_MODEL)
    note = f"{state['source']} answer: grounded={verdict['grounded']}" + \
        (f" ({verdict['problem']})" if verdict["problem"] else "")
    return verdict["grounded"], verdict["problem"], note


ANSWER_SYSTEM = """You check whether a study assistant's answer addresses what the student asked (every part of
an exercise), rather than saying it can't, dodging, or answering something else. You don't see the sources the
answer used, and checking them is not your job: never reject an answer because it cites slides, figures or
documents you can't see. problem: if not, one sentence; otherwise empty."""
ANSWER_SCHEMA = {"type": "object", "properties": {"answers_question": {"type": "boolean"}, "problem": {"type": "string"}},
                 "required": ["answers_question", "problem"], "additionalProperties": False}


def is_hint(state):
    return state["plan"]["intent"] == "solve" and state["plan"]["mode"] == "hint"


def answer_verdict(state):
    """(ok, problem, trace note) of the answers-the-question check (full answers only; hints skip it)."""
    verdict = small_json(ANSWER_SYSTEM, f"{asked(state)}\n\n<answer>\n{state['generation']}\n</answer>",
                         ANSWER_SCHEMA)
    note = f"{state['source']} answer: answers question={verdict['answers_question']}" + \
        (f" ({verdict['problem']})" if verdict["problem"] else "")
    return verdict["answers_question"], verdict["problem"], note


def check_hallucination(state):
    """Is every claim in the answer supported by the documents? If not, generate tries again with the problem."""
    ok, problem, note = grounded_verdict(state)
    if ok:
        return {"trace": state["trace"] + [note], "failed": "", "feedback": ""}
    return {"trace": state["trace"] + [note], "failed": "grounded", "feedback": problem,
            "retries": state["retries"] + 1}


def check_answer(state):
    """Runs only on a grounded full answer (not on hints): does it answer what was asked?"""
    ok, problem, note = answer_verdict(state)
    if ok:
        return {"trace": state["trace"] + [note], "failed": "", "feedback": ""}
    # an answer that dodges the question needs better sources (next_source), not another try with the same ones
    return {"trace": state["trace"] + [note], "failed": "answer", "feedback": "not answered"}


def model_answer(state):
    return {"source": "model", "documents": [], "feedback": "", "trace": state["trace"] + ["model knowledge"]}


def add_slide_images(state):
    """The text-only slides answer failed: try the slides again with their figure images, before the web."""
    return {"with_images": True, "retries": 0, "feedback": "", "trace": state["trace"] + ["retry with slide images"]}


# --- routing -----------------------------------------------------------------------------------------------------

def next_source(state):
    """Where to go when the current attempt can't give a good answer: slide text -> slide text + figure images
    (fallback mode, only if the kept chunks have figure slides) -> web -> model."""
    if state["source"] == "slides":
        if settings.SLIDE_IMAGES_MODE == "fallback" and not state.get("with_images") and \
                figures.figure_slides(state["documents"]):
            return "add_slide_images"
        return "web_search"
    return "model_answer"


def after_grade(state):
    return "generate" if state["documents"] else "web_search"


def after_web(state):
    return "generate" if state["documents"] else "model_answer"


def after_generate(state):
    if state["source"] != "model" and settings.INSUFFICIENT in state["generation"][:200]:
        return next_source(state)
    return "end" if state["source"] == "model" else "check_hallucination"


def after_hallucination(state):
    if not state["failed"]:  # a grounded hint is final: hints skip the answer check
        return "end" if is_hint(state) else "check_answer"
    return "generate" if state["retries"] <= MAX_GENERATE_RETRIES else next_source(state)


def after_answer(state):
    """Passed: done. A full answer that doesn't answer the question moves on to the next source."""
    if not state["failed"]:
        return "end"
    return next_source(state)


def build():
    g = StateGraph(State)
    for name, fn in [("retrieve", retrieve), ("grade_documents", grade_documents), ("web_search", web_search),
                     ("generate", generate), ("check_hallucination", check_hallucination),
                     ("check_answer", check_answer), ("model_answer", model_answer),
                     ("add_slide_images", add_slide_images)]:
        g.add_node(name, fn)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade_documents")
    g.add_conditional_edges("grade_documents", after_grade, ["generate", "web_search"])
    g.add_conditional_edges("web_search", after_web, ["generate", "model_answer"])
    g.add_conditional_edges("generate", after_generate,
                            {"check_hallucination": "check_hallucination", "web_search": "web_search",
                             "model_answer": "model_answer", "add_slide_images": "add_slide_images", "end": END})
    sources = {"generate": "generate", "web_search": "web_search", "model_answer": "model_answer",
               "add_slide_images": "add_slide_images"}
    g.add_conditional_edges("check_hallucination", after_hallucination, {"check_answer": "check_answer", **sources})
    g.add_conditional_edges("check_answer", after_answer, {"end": END, **sources})
    g.add_edge("model_answer", "generate")
    g.add_edge("add_slide_images", "generate")
    return g.compile()


GRAPH = build()


def answer_checked(question, plan, history, log=print, on_text=None, on_reset=None):
    """Run the corrective loop. Returns (answer, source, trace, web_sources, streamed); source is slides/web/model.
    With on_text, each full-answer attempt is streamed while it is written and on_reset(reason) is called when a later
    attempt replaces it; streamed says whether the returned answer is the one streamed last. Hints are not
    streamed: a hint rejected for giving the answer away would already be on screen."""
    state = {"question": question, "plan": plan, "history": history}
    draft = Draft(on_text, on_reset or (lambda reason: None)) if on_text and not is_hint(state) else None
    if log:
        log("[Answering from the course slides...]")
    final = state
    for update in GRAPH.stream(state, {"configurable": {"draft": draft, "log": log}}, stream_mode="values"):
        if log and update.get("source") != final.get("source") and update.get("source") in ("web", "model"):
            log({"web": "[The course slides don't answer this well enough; searching the web...]",
                 "model": "[No reliable answer from the slides or the web; answering from general knowledge...]"}
                [update["source"]])
        final = update
    reply = final["generation"]
    # keep history compact: store the bare question, not the retrieved context
    history += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    web = final["web_sources"] if final["source"] == "web" else []
    return reply, final["source"], final["trace"], web, bool(draft and draft.shown)

"""Everything before the answer: intent, the exercise, the course, and the retrieved chunks (a "plan")."""
import re
import sys

from backend import config
from backend.answering import figures
from backend.retrieval import query
from backend.retrieval.router import explicit_course

def slide_titles(chunks, limit=10):
    """'Lecture name: slide heading' for each slide in the chunks, to show what the course covers."""
    titles = []
    for c in chunks:
        lecture = re.sub(r"^(SC-CE2107-|M1-L\d+-)|[-_]26$|\.pdf$", "", c["source"])
        for heading in re.findall(r"\[slide \d+\]\n([^\n]{4,80})", c["text"]):
            t = f"{lecture}: {heading.strip()}"
            if t not in titles:
                titles.append(t)
    return titles[:limit]


def new_plan(intent, topic, **fields):
    return {"intent": intent, "topic": topic, "queries": [], "course": None, "probs": {}, "hits": [],
            "exam_hits": [], "broad": False, "specificity": None,
            "exercise": None, "exam_items": [], "error": None, "mode": "full", "hint_level": 0,
            "attachments": [], "instruction": "", "attachment_name": None, "attachment_note": "", **fields}


def prepare_solve(question, topic, index, router, current_course, force_course, generated, last=None):
    """Find the exercise (past-paper reference, earlier generated question, pasted text, or - for a follow-up
    like "another hint" - the last exercise), its course, the lecture chunks and similar past questions.
    mode is "hint" (hint_level 1, 2, ...; after config.MAX_HINTS it becomes a full solution) or "full"."""
    mode = query.tutor_mode(question)
    if query.is_follow_up(question) and not query.looks_like_exercise(question):
        if not last:
            return new_plan("solve", topic, error="Which exercise? Paste it (/paste), name the paper, e.g. "
                                                  "'SC2008 AY2023/24 S2 Q2(b)', or ask me to generate one.")
        level = last["hint_level"] + 1 if mode == "hint" else 0
        if level > config.MAX_HINTS:  # hints used up: give the full solution
            mode, level = "full", 0
        return {**last, "topic": topic, "mode": mode, "hint_level": level, "error": None}
    plan = new_plan("solve", topic, mode=mode, hint_level=1 if mode == "hint" else 0)
    code = force_course or explicit_course(question, router.labels)
    ref = query.paper_ref(question)
    if ref:
        items = index.find_exam(ref, code or current_course) or ([] if code else index.find_exam(ref))
        label = ref["year"] + (f" S{ref['sem']}" if ref["sem"] else "") + f" Q{ref['q']}"
        label += f"({ref['part']})" if ref["part"] else ""
        courses = sorted({c["course"] for c in items})
        if len(courses) > 1:  # the same paper and question number exist in several courses: ask which
            plan["probs"] = {c: 1 / len(courses) for c in courses}
            return plan
        if not items:
            plan.update(course=code or current_course, error=f"I couldn't find {label} in the indexed past papers"
                        + (f" for {code or current_course}" if code or current_course else "") + ".")
            return plan
        plan.update(exam_items=items, course=items[0]["course"],
                    exercise="\n\n".join(f"{c['label']}\n{c['text']}" for c in items) if len(items) > 1
                    else items[0]["text"])
        if config.ATTACH_FIGURE_PAGES and any(c["has_figure"] for c in items):
            blocks, pages = figures.exam_page_blocks(items)
            if blocks:  # Claude sees the real figure, not just its OCR'd labels
                plan.update(attachments=blocks, attachment_name=f"{items[0]['source']} page(s) {pages}",
                            attachment_note=f"The attached image(s) are the scanned exam page(s) {pages} that "
                                            "contain this question and its figures.")
    else:
        n = query.generated_ref(question)
        if n and generated and len(topic) < 150:
            if n > len(generated):
                plan["error"] = f"I only generated {len(generated)} question(s); which one do you mean?"
                return plan
            plan["exercise"] = generated[n - 1]
        elif n and len(topic) < 150:
            plan["error"] = ("Which question? Paste it, or name the paper, e.g. 'SC2008 AY2023/24 S2 Q2(b)'.")
            return plan
        else:
            plan["exercise"] = topic
    return solve_retrieval(plan, index, router, code, current_course)


def solve_retrieval(plan, index, router, code, current_course):
    """Course (if not known yet), lecture chunks and similar past questions for plan["exercise"]."""
    qvec = index.embed_queries([plan["exercise"][:1500]])
    if not plan["course"]:
        plan["course"], plan["probs"] = (code, {code: 1.0}) if code else \
            router.route(plan["exercise"], qvec, current=current_course)
        if not plan["course"]:
            return plan
    course = plan["course"]
    plan["queries"] = [plan["exercise"][:1500]]
    plan["hits"] = index.search(qvec, course, texts=plan["queries"])
    own = {id(c) for c in plan["exam_items"]}
    plan["exam_hits"] = [c for c in index.search(qvec, course, config.SOLVE_EXAMPLES_K + len(own), kind="exam",
                                                texts=plan["queries"])
                         if id(c) not in own][:config.SOLVE_EXAMPLES_K]
    return plan


EXPLAIN_RE = re.compile(r"\b(explain|summari[sz]e|describe|what (is|are|does)|tell me about|meaning of)\b", re.I)


def prepare_attachment(question, attachment, index, router, current_course, force_course):
    """A query with an image or PDF: the typed text says what the student wants, the file supplies the content
    (its extracted text for routing and retrieval; the file itself is attached to the answer call)."""
    user, text = question.strip(), attachment["text"]
    if not text.strip():
        return new_plan("qa", user, error=f"I couldn't read any text in {attachment['name']}.")
    asked, _ = query.parse(user) if user else (None, None)
    wants_solution = any(r.search(user) for r in (query.SOLVE_RE, query.HINT_RE, query.FULL_RE))
    if asked in ("generate", "past_paper") and not wants_solution:  # e.g. "generate questions like this"
        plan = prepare(f"{user}\n{text[:1500]}", index, router, current_course=current_course,
                       force_course=force_course)
    elif wants_solution or asked == "solve" or (query.looks_like_exercise(text) and not EXPLAIN_RE.search(user)):
        mode = query.tutor_mode(user)
        plan = new_plan("solve", text, exercise=text, mode=mode, hint_level=1 if mode == "hint" else 0)
        code = force_course or explicit_course(f"{user}\n{text}", router.labels)
        plan = solve_retrieval(plan, index, router, code, current_course)
    else:  # explain the content of the file
        plan = prepare(f"{user or 'Explain this.'}\n\n{text}", index, router, current_course=current_course,
                       force_course=force_course, force_intent="qa")
    plan.update(attachments=attachment["blocks"], instruction=user, attachment_name=attachment["name"])
    return plan


def prepare(question, index, router, current_course=None, strip=True, expand=config.EXPAND, abstract=True,
            force_course=None, abstract_threshold=config.ABSTRACT_THRESHOLD, generated=None, last=None,
            attachment=None, force_intent=None):
    """Everything before the LLM answer: intent, search queries, course and retrieved chunks.

    expand: "off", "rewrite", "decompose" (always call the local LLM), or "auto": decompose only questions
    that look multi-part. On eval/datasets/testset.jsonl, always expanding hurt easy questions (the original wording
    already retrieves well), and routing on expanded queries made the router guess instead of asking.
    So routing uses the original question only; expanded queries only widen retrieval.

    abstract: for Q&A questions below abstract_threshold (broad questions), add 3 step-back rewrites (local LLM)
    to the search queries and retrieve config.BROAD_K chunks. Raise the threshold (e.g. to infinity) to do this for
    every Q&A question, for experiments.

    attachment: an image or PDF loaded by attachments.load(); question is then the typed text (may be empty).
    """
    if attachment:
        return prepare_attachment(question, attachment, index, router, current_course, force_course)
    intent, topic = (force_intent, question) if force_intent else query.parse(question)
    if intent == "solve":
        return prepare_solve(question, topic, index, router, current_course, force_course, generated, last)
    if not strip:
        topic = question
    queries = [topic]
    qvecs = index.embed_queries(queries)
    if force_course:  # the student named the course after we asked
        course, probs = force_course, {force_course: 1.0}
    else:
        course, probs = router.route(question, qvecs, current=current_course)
    plan = new_plan(intent, topic, queries=queries, course=course, probs=probs)
    if not course:
        return plan
    if intent == "qa":
        plan["specificity"] = index.specificity(topic, qvecs[0], course)
        if abstract and plan["specificity"] < abstract_threshold:
            slides = slide_titles(index.search(qvecs, course, 12, texts=queries))
            try:
                rewrites = query.rewrites(topic, slides)
            except OSError as e:  # Ollama not running: answer the broad question directly
                print(f"[broad-question rewrite skipped: {e}]", file=sys.stderr)
                rewrites = []
            if rewrites:
                plan.update(broad=True, queries=queries + rewrites)
                plan["hits"] = index.search(index.embed_queries(plan["queries"]), course, config.BROAD_K,
                                             texts=queries)  # keywords from the student's wording only
                return plan
    if expand == "auto":
        expand = "decompose" if query.looks_multipart(topic) else "off"
    if expand != "off":
        try:
            queries += query.expand(topic, decompose=expand == "decompose")
            qvecs = index.embed_queries(queries)
        except OSError as e:  # Ollama not running: carry on with the original query
            print(f"[query expansion skipped: {e}]", file=sys.stderr)
    plan["hits"] = index.search(qvecs, course, texts=queries)
    if intent in config.EXAM_K:
        plan["exam_hits"] = index.search(qvecs, course, config.EXAM_K[intent], kind="exam", texts=queries)
    return plan

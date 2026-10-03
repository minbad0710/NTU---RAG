"""One chat conversation: the state kept between turns and the handling of one student message.

Used by the command line (backend/cli.py) and the web server (backend/server.py). Progress and results are reported through an
`emit(event)` callback as small dicts, so each front end decides how to show them:
  {"type": "info", "text"}                  e.g. "Switched to SC2005"
  {"type": "status", "text"}                progress while the answer is being prepared
  {"type": "ask_course", "options": [...]}  the router is unsure; reply with a course code
  {"type": "exercise", ...}                 the past-paper question being solved
  {"type": "past_papers", ...}              past-year lookup results (no LLM)
  {"type": "delta", "text"}                 streamed answer text, shown before the answer is checked
  {"type": "draft_reset", "text"}           the streamed text was rejected; a new attempt follows (text: why)
  {"type": "answer", ...}                   the final answer and its sources
  {"type": "error", "text"}
"""
import re

from backend import config
from backend.answering import corrective, planner, practice, prompts
from backend.retrieval.router import explicit_course

SOURCE_LABELS = {"slides": "course slides", "web": "web search",
                 "model": "general knowledge (not the course slides or the web; double-check it)"}


def past_question(c):
    """A past-paper part as a plain dict for the front ends."""
    return {"course": c["course"], "year": c["year"], "sem": c["sem"], "label": c["label"], "marks": c["marks"],
            "has_figure": c["has_figure"], "source": c["source"], "text": re.sub(r"\s*\n\s*", " ", c["text"])}


def slide_sources(chunks):
    seen, out = set(), []
    for c in chunks:
        if c.get("kind", "lecture") == "lecture" and (c["source"], c["pages"]) not in seen:
            seen.add((c["source"], c["pages"]))
            out.append({"course": c["course"], "file": c["source"], "pages": c["pages"]})
    return out


class ChatSession:
    def __init__(self, index, router):
        self.index, self.router = index, router
        self.reset()

    def reset(self):
        self.history, self.course, self.pending, self.generated, self.last = [], None, None, [], None

    def respond(self, text, attachment=None, emit=print):
        """Handle one message (and optionally an attachment from attachments.load())."""
        text = text.strip()
        code = explicit_course(text, self.router.labels) if not attachment else None
        if code and (text.lower().startswith("/course") or len(text.split()) <= 2):
            # a bare course code: switch course, and answer the question we asked about, if any
            if code != self.course:
                self.history = []
            self.course = code
            emit({"type": "info", "text": f"Switched to {code} {config.COURSE_NAMES[code]}.", "course": code})
            if not self.pending:
                return
            (text, attachment), self.pending = self.pending, None
            plan = planner.prepare(text, self.index, self.router, force_course=code, generated=self.generated,
                               last=self.last, attachment=attachment)
        else:
            plan = planner.prepare(text, self.index, self.router, current_course=self.course,
                               generated=self.generated, last=self.last, attachment=attachment)
        if plan["error"]:
            emit({"type": "error", "text": plan["error"]})
            return
        if plan["course"] is None:
            top2 = sorted(plan["probs"], key=plan["probs"].get, reverse=True)[:2]
            emit({"type": "ask_course", "text": "Which course is this about?",
                  "options": [{"code": c, "name": config.COURSE_NAMES[c]} for c in top2]})
            self.pending = (text, attachment)
            return
        if plan["course"] != self.course:
            self.history = []  # a new course starts a new conversation
        self.course = plan["course"]

        if plan["intent"] == "past_paper":
            emit({"type": "past_papers", "course": plan["course"], "topic": plan["topic"],
                  "items": [past_question(c) for c in plan["exam_hits"]]})
            return

        follow_up = plan["intent"] == "solve" and self.last is not None and plan["exercise"] == self.last["exercise"]
        if plan["exam_items"] and not follow_up:  # show the past-paper question being solved
            first = plan["exam_items"][0]
            emit({"type": "exercise", "course": plan["course"], "label": prompts.exam_label(first).split(" [")[0],
                  "text": plan["exercise"], "figure_attached": bool(plan["attachment_note"]),
                  "has_figure": any(c["has_figure"] for c in plan["exam_items"])})
        if plan["intent"] == "solve":
            self.last = plan  # "another hint" / "full solution" follow-ups refer to this exercise

        base = {"type": "answer", "course": plan["course"], "intent": plan["intent"], "mode": plan["mode"],
                "hint_level": plan["hint_level"]}
        if plan["intent"] == "generate":
            emit({"type": "status", "text": "Writing practice questions from the slides and past papers..."})
            reply = practice.answer(text, plan, self.history, on_text=lambda t: emit({"type": "delta", "text": t}))
            self.generated = practice.generated_questions(reply) or self.generated  # for "solve question 2"
            emit({**base, "text": reply, "streamed": True, "source": "slides", "source_label": SOURCE_LABELS["slides"],
                  "slides": slide_sources(plan["hits"]), "past_questions": [past_question(c) for c in plan["exam_hits"]],
                  "web_sources": [], "generated": len(self.generated)})
            return

        reply, source, trace, web, streamed = corrective.answer_checked(
            text, plan, self.history, log=lambda line: emit({"type": "status", "text": line.strip("[]")}),
            on_text=lambda t: emit({"type": "delta", "text": t}),
            on_reset=lambda reason: emit({"type": "draft_reset", "text": reason}))
        hint = plan["intent"] == "solve" and plan["mode"] == "hint"
        if hint:  # page titles and URLs can give the answer away ("Observer pattern - Wikipedia"): sites only
            web = sorted({(re.sub(r"^https?://(www\.)?([^/]+).*", r"\2", u), "") for _, u in web})
        emit({**base, "text": reply, "streamed": streamed, "source": source, "source_label": SOURCE_LABELS[source],
              "trace": trace,
              "slides": slide_sources(plan["hits"]) if source == "slides" else [],
              "past_questions": [past_question(c) for c in plan["exam_hits"]] if source == "slides" else [],
              "web_sources": [{"title": t, "url": u} for t, u in web[:6]],
              "max_hints": config.MAX_HINTS})

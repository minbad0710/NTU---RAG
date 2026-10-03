"""What Claude is told: system prompts per intent, source stage and tutor mode, and the user message layout."""
from backend import config

SOURCE_RULES = {  # what each source stage of the corrective loop (corrective.py) may draw on
    "slides": (
        " Use ONLY the lecture excerpts provided and any attached slide images (diagrams and worked examples from "
        "the same slides), citing them as (filename, slide N); do not add facts from your own knowledge. "
        "Calculations and standard mathematical or logical steps are fine, but concepts, definitions, formulas "
        f"and methods must come from the excerpts or slide images. If they don't contain enough to answer, reply "
        f"with exactly {config.INSUFFICIENT} and nothing else."
    ),
    "web": (
        " The course slides don't answer this, so you are given web search results instead. Base the answer ONLY "
        "on what those results say and cite their URLs. Start with one line saying the answer comes from web "
        f"sources, not the course slides. If the results don't answer it, reply with exactly {config.INSUFFICIENT} and "
        "nothing else."
    ),
    "model": (
        " Neither the course slides nor a web search gave a reliable answer. Answer from your own knowledge, and "
        "start with one line saying so, so the student knows to double-check it."
    ),
}


HINT_LEVELS = {
    1: ("Give ONE focused hint (about 4-6 sentences) that tells the student the specific knowledge they need for "
        "this <exercise>, and say where the course covers it. For a calculation or procedure (compute, trace, "
        "apply an algorithm, choose an option): write out the exact formula, rule or algorithm step as the course "
        "states it, and connect it to the exercise - which given values or conditions it uses and what the "
        "question is really asking for. For an explain, discuss, compare or identify question, the explanation "
        "itself is the answer: name the concept area and list the specific aspects the student should reason "
        "about, as questions, without explaining them - and if it asks which design pattern, algorithm or "
        "protocol to use, don't name it or cite a source whose URL or title would name it. End with a guiding "
        "question about the first step. Never do the working: no substituted numbers, no intermediate or final "
        "results, and don't reveal which option is correct."),
    2: ("The student has had a first hint and is still stuck. Give a stronger hint for the <exercise>: outline "
        "the steps of the method and carry out only the first step, then say what they should do next. Do NOT "
        "give the final answer or later intermediate results, and don't reveal which option is correct."),
}


def system_prompt(course, intent, stage="slides", mode="full", hint_level=0):
    base = f"You are a teaching assistant for NTU {course} {config.COURSE_NAMES.get(course, '')}. "
    if intent == "solve" and mode == "hint":
        return base + HINT_LEVELS[min(hint_level, max(HINT_LEVELS))] + SOURCE_RULES[stage]
    if intent == "generate":  # not part of the corrective chain: questions are written from the excerpts
        return base + (
            "Use the provided lecture excerpts and cite sources as (filename, slide N). "
            "Write new exam-style practice questions on the requested topic, grounded in the lecture excerpts. "
            "Match the style, difficulty and marks of the <past_question> examples, but do not copy them. "
            "Start each question with a heading '## Question N (M marks)', then give a model answer, and the "
            "slides and past question it is based on."
        )
    if intent == "solve":
        prompt = base + (
            "Give a full worked solution to the <exercise>, following the methods and notation the course uses; "
            "the <past_question> items are similar past-year questions, for context only. Solve every part. "
            "For multiple choice, give the correct option and briefly say why the others are wrong. For "
            "calculations, show the formula, the substitution with units, and the result. For explain or "
            "describe questions, scale the depth to the marks (about one key point per mark). End with the final "
            "answer(s) clearly marked. If the exercise refers to a figure or table whose content you can't see, "
            "say so and state the assumptions you make. This is an unofficial solution: where the course's "
            "convention is ambiguous, say so and note the alternative."
        )
    else:
        prompt = base + "Answer the student's question clearly, as a tutor preparing them for the exam."
    return prompt + SOURCE_RULES[stage]


def format_context(chunks):
    parts = []
    for c in chunks:
        if c.get("kind") == "exam":
            parts.append(f"<past_question paper=\"{c['source']}\" year=\"{c['year']} S{c['sem']}\" "
                         f"question=\"{c['label']}\" marks=\"{c['marks']}\">{c['text']}</past_question>")
        else:
            parts.append(f"<excerpt source=\"{c['source']}\" slides=\"{c['pages']}\">{c['text']}</excerpt>")
    return "\n\n".join(parts)


def exam_label(c):
    return f"{c['year']} S{c['sem']} {c['label']}" + (f" [{c['marks']:g} marks]" if c["marks"] else "")


def final_content(question, plan, stage="slides"):
    """The last user message for Claude: retrieved excerpts (slides stage only) plus the question or exercise."""
    context = format_context(plan["exam_hits"] + plan["hits"]) + "\n\n" if stage == "slides" else ""
    if plan["intent"] == "solve":
        src = f" source=\"{exam_label(plan['exam_items'][0])}\"" if plan["exam_items"] else ""
        return f"{context}<exercise{src}>\n{plan['exercise']}\n</exercise>\n\nSolve the exercise."
    return f"{context}Question: {question}"


def with_attachments(text, plan):
    """User message content: the student's image/PDF (so Claude sees figures OCR can't capture), then the text."""
    if not plan["attachments"]:
        return text
    note = plan.get("attachment_note") or f"The attached file ({plan['attachment_name']}) is what the student gave."
    if plan["instruction"]:
        note += f" The student's request: {plan['instruction']}"
    return [*plan["attachments"], {"type": "text", "text": f"{note}\n\n{text}"}]

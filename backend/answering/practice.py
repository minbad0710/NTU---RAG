"""Practice-question generation: one streamed answer from the slides and similar past-year questions."""
import re

from backend import llm
from backend.answering import prompts

def answer(question, plan, history, on_text=None):
    """Stream Claude's answer (chunks to on_text) and return it (used for generated practice questions)."""
    system = prompts.system_prompt(plan["course"], plan["intent"])
    content = prompts.with_attachments(prompts.final_content(question, plan), plan)
    # generous limit: the model's thinking tokens count toward it too (2500 cut answers off mid-sentence)
    reply = llm.ask(system, history + [{"role": "user", "content": content}], 12000, stream=True, on_text=on_text)
    # keep history compact: store the bare question, not the retrieved context
    history += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    return reply


def generated_questions(reply):
    """Question texts from a generate reply ('## Question N ...' headings), without their model answers."""
    blocks = re.split(r"^#{1,3}\s*Question\s+\d+.*$", reply, flags=re.M | re.I)[1:]
    return [re.split(r"^\W*model answer", b, maxsplit=1, flags=re.M | re.I)[0].strip(" \n-") for b in blocks]

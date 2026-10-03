"""Chat with the tutor in the terminal: python -m backend.cli"""
import os
import re
import sys
from pathlib import Path

from backend import attachments, config
from backend.answering.session import ChatSession
from backend.retrieval.index import Index
from backend.retrieval.router import Router

def split_file_input(text):
    """('path', 'rest of the request') if the input is '/file <path> ...' or starts with a path to an image or
    PDF (dragging a file into the terminal pastes its path, maybe quoted, maybe with spaces); else (None, text)."""
    text = re.sub(r"^/file\s+", "", text, flags=re.I) if text.lower().startswith("/file") else text
    m = re.match(r"""^\s*(["'])(.+?)\1\s*(.*)$""", text, re.S)
    if m and Path(m[2]).is_file():
        return m[2], m[3].strip()
    words = text.split(" ")
    for i in range(len(words), 0, -1):  # longest prefix that is an existing image/PDF (paths may contain spaces)
        candidate = " ".join(words[:i])
        if Path(candidate).suffix.lower() in (*attachments.IMAGE_TYPES, ".pdf") and Path(candidate).is_file():
            return candidate, " ".join(words[i:]).strip()
    return None, text


def cli_emit(event):
    """Print one session event for the command line."""
    kind = event["type"]
    if kind == "info":
        print(event["text"])
    elif kind == "status":
        print(f"[{event['text']}]")
    elif kind == "error":
        print(f"\nBot: {event['text']}")
    elif kind == "ask_course":
        options = " or ".join(f"{o['code']} ({o['name']})" for o in event["options"])
        print(f"\nBot: Which course is this about? {options}? Reply with the course code.")
    elif kind == "past_papers":
        if not event["items"]:
            print("\nBot: No past-paper questions indexed for this course yet "
                  "(run python -m backend.ingest.ocr_papers, then python -m backend.ingest.build_index).")
            return
        print(f"\nBot: Past-year questions on '{event['topic']}' ({event['course']}), best matches first:\n")
        for q in event["items"]:
            marks = f" [{q['marks']:g} marks]" if q["marks"] else ""
            more = "..." if len(q["text"]) > 400 else ""
            figure = "  (has figure)" if q["has_figure"] else ""
            print(f"* {q['year']} S{q['sem']} {q['label']}{marks}{figure}\n  {q['text'][:400]}{more}\n")
    elif kind == "exercise":
        print(f"\n{event['label']} ({event['course']}):\n{event['text']}\n")
        if event["figure_attached"]:
            print("[This question has a figure: the scanned page is attached so the answer can use it.]\n")
        elif event["has_figure"]:
            print("[Note: this question refers to a figure I can only see as OCR text.]\n")
    elif kind == "delta":
        print(event["text"], end="", flush=True)
    elif kind == "draft_reset":
        print(f"\n[{event['text']}]\n")
    elif kind == "answer":
        if event["intent"] == "solve":
            print(f"[Hint {event['hint_level']}]" if event["mode"] == "hint" else "[Full solution]")
        if not event.get("streamed"):  # a streamed answer is already on screen
            print(f"\n{event['text']}\n")
        print(f"Answered from: {event['source_label']}")
        if event["slides"]:
            print("Sources:", "; ".join(f"{s['file']} p.{s['pages']}" for s in event["slides"]))
        if event["past_questions"]:
            label = "Past questions used as examples" if event["intent"] == "generate" else "Similar past questions"
            print(f"{label}:", "; ".join(f"{q['year']} S{q['sem']} {q['label']}" for q in event["past_questions"]))
        if event["web_sources"]:
            print("Web sources:\n" + "\n".join(f"  - {w['title']}: {w['url']}" if w["url"] else f"  - {w['title']}"
                                               for w in event["web_sources"]))
        if event["intent"] == "solve" and event["mode"] == "hint":
            more = "'another hint' or " if event["hint_level"] < event["max_hints"] else ""
            print(f"(Still stuck? Ask for {more}'full solution'.)")


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY (env var or .env file).")
    index = Index()
    session = ChatSession(index, Router(index))
    print(f"NTU course RAG ({', '.join(config.COURSE_NAMES)}). Type /course <code> to switch, /paste to paste a "
          "multi-line exercise, /file <image or PDF> [request] to ask about a file (or drag the file in). "
          "For exercises, ask for a hint or the full solution. Empty line or Ctrl+C to quit.")
    while True:
        try:
            q = input(f"\nYou{f' [{session.course}]' if session.course else ''}: ").strip()
            if q.lower() == "/paste":  # multi-line input, e.g. an exercise copied from a tutorial sheet
                print("Paste the exercise, then a line with /end:")
                lines = []
                while (line := input()).strip().lower() != "/end":
                    lines.append(line)
                q = "Solve this question:\n" + "\n".join(lines).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        attachment = None
        path, rest = split_file_input(q)
        if path:  # an image or PDF as the query, optionally followed by what the student wants
            try:
                attachment = attachments.load(path)
            except (ValueError, OSError, RuntimeError) as e:
                print(f"\nBot: I couldn't read that file: {e}")
                continue
            q = rest
            how = "OCR" if attachment["ocr"] else "PDF text"
            print(f"[Read {attachment['name']}: {attachment['pages']} page(s), text via {how}"
                  + ("" if attachment["blocks"] else "; too long to attach, using its text only") + "]")
            preview = re.sub(r"\s+", " ", attachment["text"])[:200]
            print(f"[Text found: {preview}{'...' if len(attachment['text']) > 200 else ''}]")
        session.respond(q, attachment, emit=cli_emit)


if __name__ == "__main__":
    main()

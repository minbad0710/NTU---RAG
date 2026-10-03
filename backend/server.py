"""Web API for the course RAG (used by the website in frontend/).

    POST /api/chat     form: session_id, message, optional file (image or PDF)
                       -> newline-delimited JSON events (see answering/session.py), streamed as they happen
    POST /api/reset    form: session_id  -> forget that conversation
    GET  /api/courses  -> course codes and names
    GET  /api/slide    ?course&file&page -> PNG of a lecture slide (for clickable citations)

Run from the project folder: .venv/Scripts/python -m uvicorn backend.server:app --port 8000
The pipeline keeps shared state (PDF handles, usage counters), so requests are handled one at a time.
"""
import json
import queue
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend import attachments, config
from backend.answering import figures
from backend.answering.session import ChatSession
from backend.retrieval.index import Index
from backend.retrieval.router import Router

app = FastAPI(title="NTU Course RAG")
INDEX = Index()
ROUTER = Router(INDEX)
SESSIONS: dict[str, ChatSession] = {}
LOCK = threading.Lock()  # one request through the pipeline at a time
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def session_for(session_id):
    if session_id not in SESSIONS:
        SESSIONS[session_id] = ChatSession(INDEX, ROUTER)
    return SESSIONS[session_id]


@app.get("/api/courses")
def courses():
    return [{"code": c, "name": n} for c, n in config.COURSE_NAMES.items()]


@app.post("/api/reset")
def reset(session_id: str = Form(...)):
    SESSIONS.pop(session_id, None)
    return {"ok": True}


@app.post("/api/chat")
def chat(session_id: str = Form(...), message: str = Form(""), file: UploadFile | None = File(None)):
    upload = None
    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in (*attachments.IMAGE_TYPES, ".pdf"):
            raise HTTPException(400, "Attach an image (PNG, JPG, GIF, WebP) or a PDF.")
        data = file.file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, "That file is larger than 20 MB.")
        upload = (Path(file.filename).name, suffix, data)
    if not message.strip() and upload is None:
        raise HTTPException(400, "Type a question or attach a file.")

    events: queue.Queue = queue.Queue()

    def work():
        try:
            with LOCK:
                attachment = None
                if upload:
                    name, suffix, data = upload
                    events.put({"type": "status", "text": f"Reading {name}..."})
                    with tempfile.TemporaryDirectory() as tmp:
                        path = Path(tmp) / f"upload{suffix}"
                        path.write_bytes(data)
                        attachment = attachments.load(path)
                    attachment["name"] = name
                    events.put({"type": "file", "name": name, "pages": attachment["pages"], "ocr": attachment["ocr"],
                                "text": attachment["text"][:300]})
                session_for(session_id).respond(message, attachment, emit=events.put)
        except Exception as e:  # report to the page instead of dropping the stream
            events.put({"type": "error", "text": f"Something went wrong: {e}"})
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while (event := events.get()) is not None:
            yield json.dumps(event) + "\n"
        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.get("/api/slide")
def slide(course: str, file: str, page: int):
    path = config.DATA_DIR / course / file
    if course not in config.COURSE_NAMES or path.parent != config.DATA_DIR / course or not path.is_file():
        raise HTTPException(404, "No such slide deck.")
    with LOCK:
        doc = figures.open_pdf(course, file)
        if not 1 <= page <= len(doc):
            raise HTTPException(404, "No such slide.")
        png = doc[page - 1].get_pixmap(dpi=110).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})

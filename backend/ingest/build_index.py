"""Build the search index: chunk the lecture slides, add the OCR'd past-paper parts, embed everything.

Usage: python -m backend.ingest.build_index   (run backend/ingest/ocr_papers.py first for the past papers)
"""
import json
import re

import numpy as np
import pymupdf

from backend import config
from backend.ingest import exams
from backend.retrieval import embedding

def is_past_paper(path):
    return "_Questions" in path.name


def chunk_pdf(path):
    """Merge consecutive slides into chunks of ~config.MAX_CHARS, tracking the page range."""
    doc = pymupdf.open(path)
    base = {"course": path.parent.name, "source": path.name, "kind": "lecture"}
    chunks, buf, start = [], "", None
    for i, page in enumerate(doc, start=1):
        text = re.sub(r"[ \t]+", " ", page.get_text()).strip()
        text = re.sub(r"\n{2,}", "\n", text)
        if len(text) < 20:
            continue
        if buf and len(buf) + len(text) > config.MAX_CHARS:
            chunks.append({**base, "pages": f"{start}-{i - 1}", "text": buf})
            buf, start = "", None
        if start is None:
            start = i
        buf += f"\n[slide {i}]\n{text}"
        while len(buf) > config.MAX_CHARS * 2:  # very dense single slide: hard split
            chunks.append({**base, "pages": str(start), "text": buf[:config.MAX_CHARS * 2]})
            buf, start = buf[config.MAX_CHARS * 2:], i
    if buf.strip():
        chunks.append({**base, "pages": f"{start}-{len(doc)}", "text": buf})
    return chunks


def build_index(model=config.EMBED_MODEL):
    chunks = []
    for pdf in sorted(config.DATA_DIR.glob("*/*.pdf")):
        if is_past_paper(pdf):  # scanned images: their text comes from ocr_papers.py + exams.py below
            continue
        c = chunk_pdf(pdf)
        print(f"{pdf.parent.name}/{pdf.name}: {len(c)} chunks")
        chunks += c
    exam_chunks = exams.load_exam_chunks()
    print(f"Past papers: {len(exam_chunks)} question parts" + ("" if exam_chunks else " (run python -m backend.ingest.ocr_papers first)"))
    chunks += exam_chunks
    vecs = embedding.embed([f"{c['source']}\n{c['text']}" for c in chunks], model)
    out = embedding.index_dir(model)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "vectors.npy", vecs)
    (out / "chunks.json").write_text(json.dumps(chunks), encoding="utf-8")
    print(f"Indexed {len(chunks)} chunks with {model}.")


if __name__ == "__main__":
    build_index()

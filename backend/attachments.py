"""Read an image or PDF the student gives as (part of) a query.

Text is extracted locally and free (PDF text layer, or RapidOCR for images and scanned pages); it drives intent
detection, routing, retrieval and the checks. The original file is also attached to the answer call as an image
or document block, so Claude sees figures, circuits and tables that OCR can't capture.
"""
import base64
import re
from pathlib import Path

import numpy as np
import pymupdf

from backend.ingest import ocr_papers  # the same local OCR engine that reads the scanned past papers

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp"}
MAX_IMAGE_BYTES = 4_500_000  # API limit is 5 MB per base64 image; larger images are re-encoded smaller
MAX_ATTACH_PAGES = 20  # longer PDFs are used as text only (attaching every page gets expensive)
MAX_TEXT_CHARS = 8000
# a PDF page with an embedded image and less text than this is treated as scanned and OCR'd (NTU's scanned
# papers carry a ~120-character library watermark as their only text)
MIN_PAGE_TEXT = 300
WATERMARK_RE = re.compile(r"copyright act|technological university library", re.I)


def ocr_text(result):
    """OCR lines in reading order (top to bottom, then left to right)."""
    lines = sorted(result["lines"], key=lambda l: (round(l["box"][1] / 15), l["box"][0]))
    return "\n".join(l["text"] for l in lines if l["score"] >= 0.5 and not WATERMARK_RE.search(l["text"]))


def is_scanned(page):
    """An image covers at least half the page (a scan), not just a logo on a short slide."""
    area = abs(page.rect)
    return any(abs(pymupdf.Rect(info["bbox"]) & page.rect) > 0.5 * area for info in page.get_image_info())


def image_block(data, media_type):
    return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                        "data": base64.standard_b64encode(data).decode()}}


def load(path):
    """Returns {"name", "kind": "image"|"pdf", "pages", "text", "ocr": bool, "blocks": [content blocks]}."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in IMAGE_TYPES:
        doc = pymupdf.open(path)  # PyMuPDF opens images as one-page documents
        page = doc[0]
        pix = page.get_pixmap(alpha=False)  # native resolution (rendering at 200 dpi would blow up photos)
        text = ocr_text(ocr_papers.ocr_image(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)))
        data, media = path.read_bytes(), IMAGE_TYPES[ext]
        if len(data) > MAX_IMAGE_BYTES or ext == ".gif":
            scale = min(1.0, (MAX_IMAGE_BYTES / len(data)) ** 0.5)
            data, media = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale)).tobytes("png"), "image/png"
        return {"name": path.name, "kind": "image", "pages": 1, "text": text[:MAX_TEXT_CHARS], "ocr": True,
                "blocks": [image_block(data, media)]}
    if ext == ".pdf":
        doc = pymupdf.open(path)
        texts, used_ocr = [], False
        for page in list(doc)[:MAX_ATTACH_PAGES]:
            t = page.get_text().strip()
            if len(t) < MIN_PAGE_TEXT and is_scanned(page):  # scanned page: OCR it
                t, used_ocr = ocr_text(ocr_papers.ocr_image(ocr_papers.render(page))), True
            texts.append(t)
        blocks = [] if len(doc) > MAX_ATTACH_PAGES else [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                            "data": base64.standard_b64encode(path.read_bytes()).decode()}}]
        return {"name": path.name, "kind": "pdf", "pages": len(doc), "text": "\n\n".join(texts)[:MAX_TEXT_CHARS],
                "ocr": used_ocr, "blocks": blocks}
    raise ValueError(f"Unsupported file type {ext!r}: use an image ({', '.join(IMAGE_TYPES)}) or a PDF.")

"""OCR the scanned past-year papers (free, local RapidOCR) into ocr/<course>/<paper>.json.

Each file holds, per page, the OCR lines with confidence and bounding box. Papers already done are skipped,
so the run can be interrupted and resumed. Splitting into questions happens later (exams.py), so it can be
changed without re-running OCR.

Usage: python -m backend.ingest.ocr_papers [workers]
"""
import json
import logging
import sys
import time
from multiprocessing import Pool

import numpy as np
import pymupdf

from backend import config

DATA_DIR = config.DATA_DIR
OCR_DIR = config.OCR_DIR
DPI = 200  # 150 dpi already loses superscripts like n²
THREADS_PER_WORKER = 4

_engine = None


def engine():
    global _engine
    if _engine is None:
        from rapidocr import RapidOCR

        logging.disable(logging.INFO)
        _engine = RapidOCR(params={"EngineConfig.onnxruntime.intra_op_num_threads": THREADS_PER_WORKER})
    return _engine


def render(page, rotate=0):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(DPI / 72, DPI / 72).prerotate(rotate))
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)


def ocr_image(img):
    r = engine()(np.ascontiguousarray(img))
    lines = [] if r.txts is None else [
        {"text": txt, "score": round(float(score), 3), "box": [round(float(v)) for v in (*box[0], *box[2])]}
        for txt, score, box in zip(r.txts, r.scores, r.boxes)
    ]
    return {"width": img.shape[1], "lines": lines}


def ocr_page(page):
    """OCR one PDF page; returns a list because a sideways two-up scan holds two exam pages."""
    img = render(page)
    result = ocr_image(img)
    if not is_sideways(result):
        return [result]
    img, result = max(((im, ocr_image(im)) for im in (render(page, 90), render(page, -90))),
                      key=lambda pair: mean_score(pair[1]))
    if img.shape[1] > 1.2 * img.shape[0]:  # landscape after rotating: two pages side by side
        half = img.shape[1] // 2
        return [ocr_image(img[:, :half]), ocr_image(img[:, half:])]
    return [result]


def is_sideways(result):
    """Scanned sideways: long text lines come out taller than wide."""
    long = [l["box"] for l in result["lines"] if len(l["text"]) > 25]
    return len(long) >= 3 and sum(abs(b[3] - b[1]) > abs(b[2] - b[0]) for b in long) > len(long) / 2


def mean_score(result):
    return sum(l["score"] for l in result["lines"]) / max(len(result["lines"]), 1)


def ocr_paper(pdf):
    out = OCR_DIR / pdf.parent.name / f"{pdf.stem}.json"
    if out.exists():
        return f"skip {pdf.name}"
    t = time.time()
    pages = []
    for page in pymupdf.open(pdf):
        pages += ocr_page(page)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": pdf.name, "pages": pages}), encoding="utf-8")
    return f"done {pdf.name}: {len(pages)} pages in {time.time() - t:.0f}s"


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    papers = sorted(DATA_DIR.glob("*/*_Questions.pdf"))
    print(f"{len(papers)} papers, {workers} workers", flush=True)
    with Pool(workers) as pool:
        for i, msg in enumerate(pool.imap_unordered(ocr_paper, papers), 1):
            print(f"[{i}/{len(papers)}] {msg}", flush=True)


if __name__ == "__main__":
    main()

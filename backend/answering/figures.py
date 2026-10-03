"""Images for figures: scanned exam pages for past-paper questions, and figure slides from the lecture decks."""
import functools
import json
from pathlib import Path

import pymupdf

from backend import attachments, config

def exam_page_blocks(items):
    """The scanned pages a past-paper question spans, as image blocks, plus a label like "2-3"."""
    src = items[0]
    pdf = config.DATA_DIR / src["course"] / src["source"]
    ocr_file = config.OCR_DIR / src["course"] / f"{Path(src['source']).stem}.json"
    pages = sorted({p for c in items if c["pages"] for p in range(int(c["pages"].split("-")[0]),
                                                                  int(c["pages"].split("-")[-1]) + 1)})
    if not pdf.exists() or not ocr_file.exists() or not pages:
        return [], ""
    doc = pymupdf.open(pdf)
    if len(doc) != len(json.loads(ocr_file.read_text(encoding="utf-8"))["pages"]):
        return [], ""  # sideways two-up scan: OCR page numbers don't match the PDF's pages
    pages = pages[:config.MAX_FIGURE_PAGES]
    blocks = [attachments.image_block(doc[p - 1].get_pixmap(dpi=config.FIGURE_PAGE_DPI).tobytes("png"), "image/png")
              for p in pages if p <= len(doc)]
    return blocks, f"{pages[0]}-{pages[-1]}" if len(pages) > 1 else str(pages[0])


@functools.lru_cache(maxsize=64)
def open_pdf(course, source):
    return pymupdf.open(config.DATA_DIR / course / source)


@functools.lru_cache(maxsize=8192)
def slide_has_figure(course, source, page):
    """A sizeable picture, or a vector diagram (many drawn shapes), on this slide."""
    p = open_pdf(course, source)[page - 1]
    area = abs(p.rect)
    picture = sum(abs(pymupdf.Rect(i["bbox"]) & p.rect) for i in p.get_image_info()) / area
    # text slides have ~1-10 drawn shapes (bullets, rules, boxes); a UML diagram had 32, graphs 60+
    return picture > 0.15 or len(p.get_drawings()) >= 20


def slide_image_blocks(chunks, limit=None):
    """Labelled image blocks for the figure slides in lecture chunks, best-ranked chunks first. The slide text
    is already in the excerpts; the images add the diagrams and worked examples text extraction can't capture."""
    blocks, used = [], []
    for course, source, page in figure_slides(chunks, limit):
        pix = open_pdf(course, source)[page - 1].get_pixmap(dpi=config.SLIDE_IMAGE_DPI)
        blocks += [{"type": "text", "text": f"[Slide image: {source}, slide {page}]"},
                   attachments.image_block(pix.tobytes("png"), "image/png")]
        used.append(f"{source} slide {page}")
    return blocks, used


def figure_slides(chunks, limit=None):
    """(course, source, page) of up to `limit` figure slides in the chunks; animation steps keep their last frame."""
    limit = config.MAX_SLIDE_IMAGES if limit is None else limit
    picks = []  # (course, source, page, words)
    for c in chunks:
        if c.get("kind", "lecture") != "lecture" or not c.get("pages"):
            continue
        first, last = (int(x) for x in (c["pages"].split("-") + [c["pages"]])[:2])
        for page in range(first, last + 1):
            if not slide_has_figure(c["course"], c["source"], page):
                continue
            words = slide_words(c["course"], c["source"], page)
            prev = picks[-1] if picks else None
            if prev and prev[1] == c["source"] and prev[2] == page - 1 and \
                    len(words & prev[3]) / max(len(words | prev[3]), 1) >= 0.88:
                picks[-1] = (c["course"], c["source"], page, words)  # animation step: keep the later frame
            elif not any(p[1] == c["source"] and p[2] == page for p in picks):
                picks.append((c["course"], c["source"], page, words))
    return [(course, source, page) for course, source, page, _ in picks[:limit]]


@functools.lru_cache(maxsize=8192)
def slide_words(course, source, page):
    """A slide's set of words. Consecutive slides sharing at least 88% are steps of one animation (measured: animation frames 90-100%, two different use case diagrams 82%) (comparing
    only the first line failed: some decks repeat the same header on every slide)."""
    return frozenset(open_pdf(course, source)[page - 1].get_text().split())

"""Turn OCR output of past papers (ocr/<course>/<paper>.json) into exam question parts.

One item per top-level part, e.g. "Q2(b)" including its (i), (ii)... and the question's shared stem.
Layout rules come from NTU papers: question numbers at the left margin ("1."), parts one indent in ("(a)"),
marks right-aligned ("(6 marks)"). The cover page's numbered instructions carry no marks and are dropped.
"""
import json
import re

from backend import config

OCR_DIR = config.OCR_DIR
MIN_SCORE = 0.7  # lower-confidence lines are mostly text garbled by the diagonal watermark
A4_RATIO = 841.92 / 595.32

NOISE_RE = re.compile(
    r"copyright act|technological university library|continues on page|"
    r"^(sc|ce|cz)\s?\d{4}(\s*/\s*(sc|ce|cz)\s?\d{4})*$",
    re.I,
)
END_RE = re.compile(r"^\W*end of (the )?paper", re.I)
QNUM_RE = re.compile(r"^Q?(\d{1,2})(?:\s*[.,:]\s*|\s+|$)(.*)$")  # "1.", "Q1.", or "2" when OCR drops the dot
PART_RE = re.compile(r"^\(([a-h]|\d{1,2})\)\s*(.*)$")  # "(a)", or "(1)" for numbered MCQ items
MARKS_RE = re.compile(r"\((\d{1,2}(?:\.\d)?)\s*marks?\)", re.I)  # online exams use "(2.5 marks)"
TOTAL_RE = re.compile(r"\(\s*total\s*:?\s*(\d{1,3}(?:\.\d)?)\s*marks?\s*\)", re.I)  # MCQ blocks: "(Total: 80 marks)"
FIGURE_RE = re.compile(r"\b(figure|fig\.|table)\s*Q?\d", re.I)
NAME_RE = re.compile(r"(?P<course>\w+?)_AY(?P<y1>\d{2})(?P<y2>\d{2})_S(?P<sem>\d)")


def paper_meta(source):
    m = NAME_RE.match(source)
    return {"year": f"AY20{m['y1']}/{m['y2']}", "sem": int(m["sem"])} if m else {"year": "?", "sem": 0}


def reading_order(page):
    """Lines sorted top-to-bottom, left-to-right, with lines on the same row (within 15 px) kept together."""
    height = page["width"] * A4_RATIO
    lines = [l for l in page["lines"] if l["score"] >= MIN_SCORE and not NOISE_RE.search(l["text"].strip())
             and not (l["box"][1] > 0.95 * height and len(l["text"]) < 6)]
    lines.sort(key=lambda l: l["box"][1])
    rows, row = [], []
    for l in lines:
        if row and l["box"][1] - row[0]["box"][1] > 15:
            rows.append(sorted(row, key=lambda x: x["box"][0]))
            row = []
        row.append(l)
    if row:
        rows.append(sorted(row, key=lambda x: x["box"][0]))
    return [l for r in rows for l in r]


def split_paper(ocr):
    """Returns exam items: {question, part, marks, text, pages, has_figure, dropped_lines}."""
    lines = []
    for pno, page in enumerate(ocr["pages"], 1):
        lines += [{**l, "page": pno} for l in reading_order(page)]
    end = next((i for i, l in enumerate(lines) if END_RE.search(l["text"])), None)
    if end is not None:  # pages after this are exam-hall instructions, not questions
        lines = lines[:end]
    else:  # no end marker: cut after the last marks line
        last = max((i for i, l in enumerate(lines) if MARKS_RE.search(l["text"])), default=len(lines) - 1)
        lines = lines[:last + 1]
    part_xs = sorted(l["box"][0] for l in lines if PART_RE.match(l["text"]))
    part_x = part_xs[len(part_xs) // 2] if part_xs else None
    # question numbers sit left of the part labels; fall back to 17% of page width if no parts found
    qnum_max_x = part_x - 50 if part_x else 0.17 * ocr["pages"][0]["width"]

    questions, cur = [], None
    for l in lines:
        m = QNUM_RE.match(l["text"].strip())
        prev = cur["question"] if cur else 0
        # numbers only step up by 1 (2 if OCR missed a label) or restart at 1; rejects stray "90 ms" lines
        if m and l["box"][0] < qnum_max_x and (int(m[1]) == 1 or prev < int(m[1]) <= prev + 2):
            cur = {"question": int(m[1]), "lines": []}
            questions.append(cur)
            if m[2]:  # e.g. "3.(a) Describe...": the rest starts at the part column
                box = [part_x or l["box"][0]] + l["box"][1:]
                cur["lines"].append({**l, "text": m[2], "box": box})
        elif cur:
            cur["lines"].append(l)
    # instruction items on the cover page have no marks
    questions = [q for q in questions if any(MARKS_RE.search(l["text"]) or TOTAL_RE.search(l["text"])
                                             for l in q["lines"])]

    items = []
    for q in questions:
        stem, parts = [], []
        for l in q["lines"]:
            m = PART_RE.match(l["text"].strip())
            if m and (part_x is None or abs(l["box"][0] - part_x) < 60):
                parts.append({"part": m[1], "lines": [{**l, "text": m[2]}] if m[2] else []})
            elif parts:
                parts[-1]["lines"].append(l)
            else:
                stem.append(l)
        if parts and any(MARKS_RE.search(l["text"]) for l in stem):
            # marks before the first label: OCR missed that part's label (e.g. "(a)"), so it's a part, not a stem
            first = parts[0]["part"]
            prev = str(int(first) - 1) if first.isdigit() else chr(ord(first) - 1)
            parts.insert(0, {"part": prev if first not in ("a", "1") else "", "lines": stem})
            stem = []
        total = next((float(m[1]) for l in stem if (m := TOTAL_RE.search(l["text"]))), 0)
        start = len(items)
        for p in parts or [{"part": "", "lines": []}]:
            # numbered MCQ items are self-contained; their shared stem is just answering instructions
            body = p["lines"] if p["part"].isdigit() else stem + p["lines"]
            text = "\n".join(l["text"] for l in body).strip()
            items.append({
                "question": q["question"],
                "part": p["part"],
                "marks": round(sum(float(x) for x in MARKS_RE.findall(text)), 1),
                "text": text,
                "pages": sorted({l["page"] for l in body}),
                "has_figure": bool(FIGURE_RE.search(text)),
            })
        if total and not any(it["marks"] for it in items[start:]):  # MCQs: share the block total equally
            for it in items[start:]:
                it["marks"] = round(total / (len(items) - start), 1)
    return items


def load_exam_chunks():
    """All exam items as index chunks (same shape as lecture chunks, plus exam metadata)."""
    chunks = []
    for f in sorted(OCR_DIR.glob("*/*.json")):
        ocr = json.loads(f.read_text(encoding="utf-8"))
        meta = paper_meta(ocr["source"])
        for it in split_paper(ocr):
            label = f"Q{it['question']}" + (f"({it['part']})" if it["part"] else "")
            chunks.append({
                "course": f.parent.name, "source": ocr["source"], "kind": "exam",
                "pages": "-".join(map(str, it["pages"][:1] + it["pages"][-1:])) if it["pages"] else "",
                "label": label, **meta, "marks": it["marks"], "has_figure": it["has_figure"],
                "text": it["text"],
            })
    return chunks

"""Draws the README diagrams (docs/*.svg) in one shared style: rows of boxes, result boxes at the right end.

Each SVG follows the reader's light or dark theme. Run after changing a diagram:
    python docs/diagrams.py
"""
from pathlib import Path

OUT = Path(__file__).parent
W, H = 170, 62  # box size
COLS = [150, 370, 590, 810, 1030, 1250]  # box left edges

STYLE = """
  <style>
    :root { --panel:#f6f8fa; --line:#57606a; --text:#1f2328; --sub:#57606a;
            --gen:#fff4e5; --genB:#d97706; --chk:#eef4ff; --chkB:#3b6fd8; --inp:#e8f7ef; --inpB:#1f9d63;
            --ans:#ffffff; --ansB:#8c959f; --dec:#f5efff; --decB:#8250df; --hint:#1f9d63; }
    @media (prefers-color-scheme: dark) {
      :root { --panel:#161b22; --line:#8b949e; --text:#e6edf3; --sub:#9aa4af;
              --gen:#3a2716; --genB:#f0883e; --chk:#16233d; --chkB:#6e9bf5; --inp:#10301f; --inpB:#3fb97a;
              --ans:#1c2128; --ansB:#8b949e; --dec:#271c3d; --decB:#b392f0; --hint:#3fb97a; }
    }
    .panel { fill: var(--panel); }
    .box { stroke-width: 1.6; }
    .inp { fill: var(--inp); stroke: var(--inpB); }
    .gen { fill: var(--gen); stroke: var(--genB); }
    .chk { fill: var(--chk); stroke: var(--chkB); }
    .ans { fill: var(--ans); stroke: var(--ansB); }
    .dec { fill: var(--dec); stroke: var(--decB); stroke-dasharray: 5 3; }
    .t { fill: var(--text); font: 600 15px -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
    .s { fill: var(--sub); font: 12.5px -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; }
    .lab { fill: var(--sub); font: 12px ui-monospace, "SFMono-Regular", Consolas, monospace; }
    .row { fill: var(--sub); font: 600 12.5px ui-monospace, "SFMono-Regular", Consolas, monospace; letter-spacing: .08em; }
    .ln { stroke: var(--line); stroke-width: 1.5; fill: none; }
    .hint { stroke: var(--hint); stroke-width: 1.5; fill: none; stroke-dasharray: 6 4; }
    .hl { fill: var(--hint); font: 12px ui-monospace, "SFMono-Regular", Consolas, monospace; }
    .ah { fill: var(--line); }
    .ahh { fill: var(--hint); }
  </style>
  <defs>
    <marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" class="ah" /></marker>
    <marker id="h" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0L10 5L0 10z" class="ahh" /></marker>
  </defs>"""


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Diagram:
    def __init__(self, width, height, label):
        self.w, self.h, self.label, self.parts = width, height, label, []

    def box(self, x, y, title, sub="", kind="chk", w=W, h=H):
        self.parts.append(f'<rect class="box {kind}" x="{x}" y="{y}" width="{w}" height="{h}" rx="9" />')
        if sub:
            self.parts.append(f'<text class="t" x="{x + 16}" y="{y + h / 2 - 5}">{esc(title)}</text>'
                              f'<text class="s" x="{x + 16}" y="{y + h / 2 + 15}">{esc(sub)}</text>')
        else:
            self.parts.append(f'<text class="t" x="{x + 16}" y="{y + h / 2 + 5}">{esc(title)}</text>')

    def line(self, d, arrow=True, hint=False):
        cls, mark = ("hint", "h") if hint else ("ln", "a")
        end = f' marker-end="url(#{mark})"' if arrow else ""
        self.parts.append(f'<path class="{cls}" d="{d}"{end} />')

    def text(self, x, y, s, cls="lab", anchor="start"):
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        for i, part in enumerate(s.split("\n")):
            self.parts.append(f'<text class="{cls}" x="{x}" y="{y + 16 * i}"{a}>{esc(part)}</text>')

    def row(self, y, s):
        for i, part in enumerate(s.split("\n")):
            self.parts.append(f'<text class="row" x="24" y="{y + 26 + 18 * i}">{esc(part)}</text>')

    def right(self, col, y, label=None):
        """Arrow from the box in COLS[col] to the next column, at row y."""
        x0, x1, cy = COLS[col] + W, COLS[col + 1], y + H / 2
        self.line(f"M{x0} {cy}H{x1 - 2}")
        if label:
            self.text(x0 + 6, cy - 7, label)

    def save(self, name):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" role="img" '
               f'aria-label="{esc(self.label)}">{STYLE}\n  <rect class="panel" x="0" y="0" width="{self.w}" '
               f'height="{self.h}" rx="14" />\n  ' + "\n  ".join(self.parts) + "\n</svg>\n")
        (OUT / name).write_text(svg, encoding="utf-8")
        print("wrote", name)


def overview():
    d = Diagram(1460, 560, "Whole pipeline: the message is read, its intent and course found, slides and past papers "
                           "searched, then one of three paths produces the answer.")
    y = 60
    d.row(y, "UNDERSTAND\n& SEARCH")
    d.box(COLS[0], y, "Student message", "text, photo or PDF", "inp")
    d.box(COLS[1], y, "Read attachment", "RapidOCR, if a file")
    d.box(COLS[2], y, "Detect intent", "rules, no model call")
    d.box(COLS[3], y, "Pick the course", "router")
    d.box(COLS[4], y, "Hybrid search", "slides + past papers")
    for c in range(4):
        d.right(c, y)
    # fan out by intent
    d.line(f"M{COLS[4] + W / 2} {y + H}V170H480V481", arrow=False)
    rows = [(230, "PAST_PAPER", "List real past-year questions", "index search only, no model", "ans",
             "Answer", "exam questions + marks"),
            (340, "GENERATE", "Write practice questions", "Claude Sonnet, streamed", "gen",
             "Answer", "questions + answers"),
            (450, "QA / SOLVE", "Corrective answer loop", "slides → figures → web → model", "gen",
             "Answer", "checked, with its sources")]
    for ry, label, title, sub, kind, at, asub in rows:
        d.row(ry, label)
        d.line(f"M480 {ry + H / 2}H{COLS[2] - 2}")
        d.box(COLS[2], ry, title, sub, "chk" if label == "PAST_PAPER" else kind, w=390)
        d.line(f"M{COLS[2] + 390} {ry + H / 2}H{COLS[5] - 2}")
        d.box(COLS[5], ry, at, asub, "ans")
    d.text(150, 266, "\"Past year questions\non deadlock\"")
    d.text(150, 376, "\"Give me 2 practice\nquestions on paging\"")
    d.text(150, 486, "\"Explain CRC\" or\n\"Hint for AY2526 Q1\"")
    d.text(COLS[2] + 390 + 10, 254, "no model call: instant")
    d.text(COLS[2] + 390 + 10, 474, "see the answer loop below")
    d.save("pipeline-overview.svg")


def ingestion():
    d = Diagram(1460, 360, "Ingestion: slides are extracted and merged into chunks, past papers are OCR'd and split "
                           "into question parts; both are embedded and keyword-indexed into one index.")
    r1, r2 = 70, 230
    d.row(r1, "LECTURE\nSLIDES")
    d.row(r2, "PAST\nPAPERS")
    d.box(COLS[0], r1, "64 slide decks", "text-based PDFs", "inp")
    d.box(COLS[1], r1, "Extract text", "PyMuPDF")
    d.box(COLS[2], r1, "Merge into chunks", "~1,200 chars, [slide N]", "gen")
    d.box(COLS[0], r2, "75 past papers", "scanned images", "inp")
    d.box(COLS[1], r2, "OCR", "RapidOCR, 200 dpi")
    d.box(COLS[2], r2, "Split into parts", "Q2(b): stem, marks", "gen")
    for r in (r1, r2):
        d.right(0, r)
        d.right(1, r)
    d.text(COLS[2] + 8, r1 + H + 20, "skip near-empty slides,\nhard-split dense ones")
    d.text(COLS[2] + 8, r2 + H + 20, "layout rules: margins,\nindents, (6 marks)")
    # both chunk sets feed both indexes
    bus = 785
    d.line(f"M{COLS[2] + W} {r1 + H / 2}H{bus}", arrow=False)
    d.line(f"M{COLS[2] + W} {r2 + H / 2}H{bus}", arrow=False)
    d.line(f"M{bus} {r1 + H / 2}V{r2 + H / 2}", arrow=False)
    d.line(f"M{bus} {r1 + H / 2}H{COLS[3] - 2}")
    d.line(f"M{bus} {r2 + H / 2}H{COLS[3] - 2}")
    d.box(COLS[3], r1, "Embed", "bge-small, 384-d")
    d.box(COLS[3], r2, "Keyword index", "BM25")
    d.line(f"M{COLS[3] + W} {r1 + H / 2}H{COLS[5] - 2}")
    d.line(f"M{COLS[3] + W} {r2 + H / 2}H{COLS[5] - 2}")
    d.box(COLS[5], r1, "Saved to disk", "vectors.npy + chunks", "ans")
    d.box(COLS[5], r2, "Not saved", "rebuilt at startup", "ans")
    d.text(COLS[3] + W + 10, r1 + H / 2 - 7, "slow (~3.5 min): computed once")
    d.text(COLS[3] + W + 10, r1 + H / 2 + 19, "1,879 chunks: 962 slide + 917 exam")
    d.text(COLS[3] + W + 10, r2 + H / 2 - 7, "fast (~0.5 s): from chunks.json")
    d.text(COLS[3] + W + 10, r2 + H / 2 + 19, "in memory, at every start")
    d.save("build-index.svg")


def routing():
    d = Diagram(1460, 520, "Routing: a course code wins, then the current course if the question still fits, then "
                           "the best-matching course; if two courses are close, the student is asked.")
    r1, r2, r3, r4 = 60, 180, 300, 420
    d.row(r1, "1 · NAMED")
    d.row(r2, "2 · STICKY")
    d.row(r3, "3 · BEST\nMATCH")
    d.row(r4, "4 · UNSURE")
    d.box(COLS[0], r1, "Message", "", "inp")
    d.box(COLS[1], r1, "Course code?", "SC2008, CE2008, CZ2008", "dec")
    d.right(0, r1)
    d.line(f"M{COLS[1] + W} {r1 + H / 2}H{COLS[5] - 2}")
    d.text(COLS[1] + W + 8, r1 + H / 2 - 7, "yes")
    d.box(COLS[5], r1, "Course", "the one named", "ans")
    d.line(f"M{COLS[1] + W / 2} {r1 + H}V{r2 - 2}")
    d.text(COLS[1] + W / 2 + 6, r1 + H + 34, "no")
    d.box(COLS[1], r2, "Current course?", "still ≥ 10% likely", "dec")
    d.line(f"M{COLS[1] + W} {r2 + H / 2}H{COLS[5] - 2}")
    d.text(COLS[1] + W + 8, r2 + H / 2 - 7, "yes: shared terms stay with the course you're studying")
    d.box(COLS[5], r2, "Course", "stay on it", "ans")
    d.line(f"M{COLS[1] + W / 2} {r2 + H}V{r3 - 2}")
    d.text(COLS[1] + W / 2 + 6, r2 + H + 34, "no, or none yet")
    d.box(COLS[1], r3, "Score courses", "best chunk → softmax")
    d.right(1, r3)
    d.box(COLS[2], r3, "Top two close?", "within 0.3", "dec")
    d.line(f"M{COLS[2] + W} {r3 + H / 2}H{COLS[5] - 2}")
    d.text(COLS[2] + W + 8, r3 + H / 2 - 7, "no")
    d.box(COLS[5], r3, "Course", "the top one", "ans")
    d.line(f"M{COLS[2] + W / 2} {r3 + H}V{r4 + H / 2}H{COLS[5] - 2}")
    d.text(COLS[2] + W / 2 + 6, r3 + H + 34, "yes")
    d.box(COLS[5], r4, "Ask the student", "SC2005 or SC2107?", "ans")
    d.text(150, 500, "Measured: right course 92%, asks 7%, wrong 0.6%. Once the student picks, the original question is answered.",
           cls="s")
    d.save("routing.svg")


def retrieval():
    d = Diagram(1460, 540, "Retrieval: the query, its step-back rewrites or sub-questions are embedded for a cosine "
                           "ranking; the student's own wording also gets a BM25 ranking; both are merged with RRF.")
    r1, r2, r3, r4 = 60, 180, 300, 420
    d.row(r1, "BROAD")
    d.row(r2, "AS TYPED")
    d.row(r3, "MULTI-PART")
    d.row(r4, "KEYWORDS")
    d.box(COLS[0], r2, "Search query", "the student's topic", "inp")
    d.right(0, r2)
    d.box(COLS[1], r2, "Broad or multi?", "specificity score, cues", "dec")
    d.box(COLS[2], r1, "3 step-back rewrites", "qwen2.5:3b, local", "gen")
    d.box(COLS[2], r2, "Query as typed", "most questions")
    d.box(COLS[2], r3, "Sub-questions", "qwen2.5:3b, local", "gen")
    d.line(f"M{COLS[1] + W / 2} {r2}V{r1 + H / 2}H{COLS[2] - 2}")
    d.text(COLS[1] + W / 2 + 8, r1 + H / 2 - 7, "broad")
    d.right(1, r2, "no")
    d.line(f"M{COLS[1] + W / 2} {r2 + H}V{r3 + H / 2}H{COLS[2] - 2}")
    d.text(COLS[1] + W / 2 + 8, r3 + H / 2 - 7, "multi-part")
    # all query sets -> embed (rewrites keep the original query too)
    d.box(COLS[3], r2, "Embed + cosine", "bge-small, one ranking", "chk")
    d.line(f"M{COLS[2] + W} {r1 + H / 2}H{COLS[3] + 40}V{r2 - 2}")
    d.right(2, r2)
    d.line(f"M{COLS[2] + W} {r3 + H / 2}H{COLS[3] + 40}V{r2 + H + 2}")
    # keywords: always the student's own wording
    d.line(f"M{COLS[0] + W / 2} {r2 + H}V{r4 + H / 2}H{COLS[3] - 2}")
    d.text(COLS[0] + W / 2 + 8, r4 + H / 2 - 7, "the student's own wording only")
    d.box(COLS[3], r4, "BM25 ranking", "exact keyword match", "chk")
    d.text(COLS[3], r4 + H + 20, "e.g. CSMA/CD, TA0CCR0, 802.11")
    # merge
    d.box(COLS[4], r3, "RRF merge", "rank fusion, k = 60", "gen")
    d.line(f"M{COLS[3] + W} {r2 + H / 2}H{COLS[4] + W / 2}V{r3 - 2}")
    d.line(f"M{COLS[3] + W} {r4 + H / 2}H{COLS[4] + W / 2}V{r3 + H + 2}")
    d.text(COLS[3] + W + 8, r2 + H / 2 - 7, "per query")
    d.text(COLS[3] + W + 8, r4 + H / 2 - 7, "in parallel")
    d.right(4, r3)
    d.box(COLS[5], r3, "Top chunks", "6, or 12 when broad", "ans")
    d.text(COLS[5], r3 + H + 20, "only the chosen course")
    d.text(COLS[2], r3 + H + 20, "both are searched together\nwith the original query")
    d.save("retrieval.svg")


def corrective_loop():
    d = Diagram(1460, 790, "Corrective answer loop: each source (slides, slides with figures, web, model knowledge) "
                           "has its own row ending in an answer; a failed answer drops to the row below.")
    r1, r2, r3, r4 = 80, 270, 460, 650
    d.row(r1, "1 · COURSE\nSLIDES")
    d.row(r2, "2 · SLIDES +\nFIGURES")
    d.row(r3, "3 · WEB")
    d.row(r4, "4 · MODEL\n(RARE)")

    def checked_row(y, gen_sub, hal_sub, answer_sub, retry_label):
        d.box(COLS[2], y, "Generate", gen_sub, "gen")
        d.box(COLS[3], y, "Hallucination check", hal_sub)
        d.box(COLS[4], y, "Answer check", "answers the question?")
        d.box(COLS[5], y, "Answer", answer_sub, "ans")
        d.right(2, y, "draft" if y == r1 else None)
        d.right(3, y, "ok")
        d.right(4, y, "yes")
        d.line(f"M{COLS[3] + 50} {y}V{y - 26}H{COLS[2] + 120}V{y - 2}")
        d.text(COLS[2] + 195, y - 34, retry_label, anchor="middle")

    def failures(y, to_x, to_y):
        for x, label in ((COLS[2] + 85, "INSUFFICIENT"), (COLS[3] + 85, "still not grounded"),
                         (COLS[4] + 85, "doesn't answer")):
            d.line(f"M{x} {y + H}V{y + H + 50}", arrow=False)
            d.text(x + 6, y + H + 24, label)
        d.line(f"M{COLS[4] + 85} {y + H + 50}H{to_x}V{to_y - 2}")

    # row 1
    d.box(COLS[0], r1, "Retrieve", "hybrid search, top 6", "inp")
    d.right(0, r1)
    d.box(COLS[1], r1, "Grade chunks", "Haiku keeps relevant")
    d.right(1, r1, "kept")
    checked_row(r1, "Sonnet · slide text", "claims supported?", "from slides", "not grounded: retry once with feedback")
    d.line(f"M{COLS[3] + 140} {r1}V{r1 - 20}H{COLS[5] + 85}V{r1 - 2}", hint=True)
    d.text(COLS[4] + 112, r1 - 28, "hint: skip the answer check", cls="hl", anchor="middle")
    failures(r1, COLS[1] + 85, r2)
    d.line(f"M{COLS[1] + 20} {r1 + H}V{r1 + H + 72}H345V{r3 + H / 2}H{COLS[1] - 2}")
    d.text(335, 400, "nothing\nrelevant", anchor="end")
    # row 2
    d.box(COLS[1], r2, "Figures left?", "unused slide diagrams", "dec")
    d.right(1, r2, "yes")
    checked_row(r2, "slide text + images", "Sonnet reads images", "from slides", "not grounded: retry once")
    d.line(f"M{COLS[1] + 85} {r2 + H}V{r3 - 2}")
    d.text(COLS[1] + 77, r2 + H + 40, "no (none,\nor used)", anchor="end")
    failures(r2, COLS[1] + 135, r3)
    # row 3
    d.box(COLS[1], r3, "Web search", "Haiku · ≤ 3 searches")
    d.right(1, r3, "found")
    checked_row(r3, "from the web report", "vs the web report", "from web", "not grounded: retry once")
    d.line(f"M{COLS[1] + 85} {r3 + H}V{r3 + H + 78}H{COLS[2] + 30}V{r4 - 2}")
    d.text(COLS[1] + 91, r3 + H + 38, "no results")
    failures(r3, COLS[2] + 85, r4)
    # row 4
    d.box(COLS[2], r4, "Generate", "own knowledge, labelled", "gen")
    d.box(COLS[5], r4, "Answer", "from knowledge", "ans")
    d.line(f"M{COLS[2] + W} {r4 + H / 2}H{COLS[5] - 2}")
    d.text((COLS[2] + W + COLS[5]) / 2, r4 + H / 2 - 7, "no checks", anchor="middle")
    d.line("M150 756H190", hint=True)
    d.text(200, 760, "Hints skip the answer check in every row: once grounded, a hint goes straight to the answer.",
           cls="s")
    d.save("answer-loop.svg")


if __name__ == "__main__":
    overview()
    ingestion()
    routing()
    retrieval()
    corrective_loop()

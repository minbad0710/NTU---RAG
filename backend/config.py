"""Settings shared by the whole backend: paths, models and the tuning knobs of each pipeline stage.

Modules read these as config.NAME at call time, so the eval scripts can change a setting for one run.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent  # the project folder
DATA_DIR = ROOT / "data"  # data/<course>/*.pdf: lecture slides and scanned past papers (*_Questions.pdf)
OCR_DIR = ROOT / "ocr"  # OCR output of the past papers (backend/ingest/ocr_papers.py)
INDEX_DIR = ROOT / "index"  # the search index, one folder per embedding model
EMBED_MODEL = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
CLAUDE_MODEL = "claude-sonnet-5-5"
MAX_CHARS = 1200  # target chunk size; slides are short so pages get merged
TOP_K = 6
RRF_K = 60  # reciprocal rank fusion constant when merging several queries
# Hybrid search: each query is also ranked with BM25 keyword matching, and that ranking is fused (RRF) with the
# embedding ranking. Keywords match special terms one-to-one (CSMA/CD, TA0CCR0, 802.11, Dijkstra) that
# embeddings blur. BM25_WEIGHT scales the keyword list's share of the fusion; 0 turns hybrid search off.
BM25_WEIGHT = 1.0
# How the two lists are merged: "rrf" (reciprocal rank fusion: ranks only) or "weighted" (each query's cosine and
# BM25 scores normalised to 0-1 within the course, then (1 - FUSION_ALPHA) * cosine + FUSION_ALPHA * BM25).
FUSION = "rrf"
FUSION_ALPHA = 0.3
BM25_K1 = 1.2  # term-frequency saturation
BM25_B = 0.75  # document-length normalisation
# bge v1.5 retrieves better when short queries carry this instruction (passages don't get it)
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: " #under stand by reading bge documentation
USE_QUERY_PREFIX = True
EXPAND = "auto"  # local-LLM query expansion, see prepare()
# Abstraction check (Q&A only): specificity = sum of IDF of the question's content words + ABSTRACT_W * gap
# between the best and 10th-best lecture chunk. Broad questions use common words and match many chunks
# about equally. Chosen on eval/datasets/testset.jsonl: catches 12/15 broad questions, 0/124 false alarms.
ABSTRACT_THRESHOLD = 12.0
ABSTRACT_W = 40.0
# Broad questions are rewritten into 3 whole-topic questions from different angles (step-back, slide terms,
# mechanisms); the rewrites only widen retrieval and Claude answers once from BROAD_K chunks. Answering each
# rewrite (or sub-question) separately and merging the answers lost to a single answer in blind judging
# (eval/answer_quality.py), so that approach was removed.
BROAD_K = 12
# Q&A and solve answers go through the corrective loop in corrective.py (LangGraph): course slides,
# then one round of web search, then (rarely) the model's own knowledge. The answering prompt tells Claude to
# reply with INSUFFICIENT when its sources don't answer the question.
INSUFFICIENT = "INSUFFICIENT_CONTEXT"
SOLVE_EXAMPLES_K = 3  # similar past-year questions shown when solving an exercise
MAX_HINTS = 2  # "another hint" after this many gives the full solution
# Solving a past-paper part that references a figure: attach the scanned page(s) to the answer call, since OCR
# only captures the figure's labels as fragments. Checks stay text-only.
ATTACH_FIGURE_PAGES = True
FIGURE_PAGE_DPI = 130  # ~1,500 input tokens per page
MAX_FIGURE_PAGES = 3
# Images of the figure slides in the kept chunks (diagrams and worked examples come through text extraction as
# scattered labels). "fallback": answer from slide text first and add the images only if that answer fails,
# before falling back to the web; "always": attach them on the first attempt; "never". The checks see them too.
SLIDE_IMAGES_MODE = "fallback"
SLIDE_IMAGE_DPI = 100  # a 16:9 slide at 100 dpi is about 1000x560 px, ~750 input tokens
MAX_SLIDE_IMAGES = 4
EXAM_K = {"past_paper": 8, "generate": 3}

COURSE_NAMES = {
    "SC2001": "Algorithm Design and Analysis",
    "SC2005": "Operating Systems",
    "SC2006": "Software Engineering",
    "SC2008": "Computer Networks",
    "SC2107": "Microprocessor Systems (ARM Cortex-M / MSP432)",
}

load_dotenv(ROOT / ".env")

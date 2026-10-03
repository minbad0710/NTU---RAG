"""Where the time goes for one answer: times each pipeline stage (prepare, each Claude call, Ollama) on a few
typical queries. Costs a few Claude calls per query. Run: python eval/latency.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import config, llm  # noqa: E402
from backend.answering import planner  # noqa: E402
from backend.retrieval import query  # noqa: E402
from backend.answering.session import ChatSession  # noqa: E402
from backend.retrieval.index import Index  # noqa: E402
from backend.retrieval.router import Router  # noqa: E402

QUERIES = [
    "Explain how CRC error detection works",        # normal Q&A
    "What is an operating system?",                 # broad: step-back rewrites via Ollama
    "Give me a hint for SC2008 AY2526 S2 Q1(15)",   # past-paper hint
    "Solve SC2001 AY1617 S2 Q4(c)",                 # past-paper full solution
]

log = []


def timed(name, fn):
    def wrap(*a, **k):
        t = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            log.append((name(*a, **k) if callable(name) else name, time.perf_counter() - t))
    return wrap


def ask_name(system, messages, max_tokens, stream, on_text=None, **kw):
    model = kw.get("model", config.CLAUDE_MODEL).replace("claude-", "")
    kind = "web" if kw.get("tools") else "json" if kw.get("output_config") else "answer"
    return f"claude {model} {kind} ({system[:28]!r})"


llm.ask = timed(ask_name, llm.ask)
query._generate = timed("ollama", query._generate)
planner.prepare = timed("prepare (total, incl. ollama/embed)", planner.prepare)

index = Index()
router = Router(index)
for q in QUERIES:
    session = ChatSession(index, router)
    log.clear()
    t0 = time.perf_counter()
    first = {}

    def emit(e):
        if e["type"] == "delta" and "text" not in first:
            first["text"] = time.perf_counter() - t0
        if e["type"] == "draft_reset":
            print("  [reset]", e["text"][:100])
        if e["type"] == "answer" and "answer" not in first:
            first["answer"] = time.perf_counter() - t0
            first["trace"] = e.get("trace")

    session.respond(q, emit=emit)
    total = time.perf_counter() - t0
    shown = f"first text {first['text']:.1f}s, " if "text" in first else "not streamed, "
    print(f"\n=== {q}  -> {shown}total {total:.1f}s")
    for name, secs in log:
        print(f"  {secs:6.1f}s  {name}")
    print("  trace:", first.get("trace"))

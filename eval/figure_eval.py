"""Does attaching the scanned page help on figure-based past-paper questions?

Runs the figure rows of eval/datasets/solve_set.jsonl through the corrective loop twice - with the page image attached
(config.ATTACH_FIGURE_PAGES = True, the default) and with OCR text only - and grades both against the reference
answers with the same judge as pipeline_eval.py. Results are cached in eval/results/figure_eval.json.

Usage: python eval/figure_eval.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"
RESULTS = ROOT / "eval" / "results"  # cached model outputs, so re-runs only pay for what is new
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from backend import config, llm  # noqa: E402
from backend.answering import corrective, planner  # noqa: E402
from backend.retrieval.index import Index  # noqa: E402
from backend.retrieval.router import Router  # noqa: E402
from pipeline_eval import JUDGE_SCHEMA, JUDGE_SYSTEM, PRICE_IN, PRICE_OUT, PRICE_SEARCH  # noqa: E402

CACHE = RESULTS / "figure_eval.json"
SCORE = {"correct": 1, "partial": 0.5, "wrong": 0}


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    index = Index()
    router = Router(index)
    rows = [json.loads(l) for l in (DATASETS / "solve_set.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip() and json.loads(l).get("figure")]
    results = {}
    for mode in ("page image", "OCR text only"):
        config.ATTACH_FIGURE_PAGES = mode == "page image"
        for r in rows:
            key = f"{mode}|{r['id']}"
            if key not in cache:
                plan = planner.prepare(r["prompt"], index, router)
                reply, source, trace, _, _ = corrective.answer_checked(r["prompt"], plan, [], log=None)
                content = (f"<question>\n{r['question']}\n</question>\n\n<reference_answer>\n{r['answer']}\n"
                           "Key points:\n" + "\n".join(f"- {k}" for k in r["key_points"]) +
                           f"\n</reference_answer>\n\n<solution>\n{reply}\n</solution>")
                judge = json.loads(llm.ask(JUDGE_SYSTEM, [{"role": "user", "content": content}], 8000, stream=False,
                                            output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}}))
                cache[key] = {"answer": reply, "source": source, "trace": trace, "attached": len(plan["attachments"]),
                              "judge": judge}
                CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
            results[key] = cache[key]
            print(f"  {mode:13} {r['id']}: {cache[key]['judge']['final_answer']}", flush=True)
    config.ATTACH_FIGURE_PAGES = True

    print(f"\n{'id':4} {'question':30} {'page image':>22} {'OCR text only':>22}")
    for r in rows:
        cells = []
        for mode in ("page image", "OCR text only"):
            res = results[f"{mode}|{r['id']}"]
            j = res["judge"]
            cells.append(f"{j['final_answer']} {min(j['key_points'], len(r['key_points']))}/{len(r['key_points'])} "
                         f"({res['source']})")
        print(f"{r['id']:4} {r['paper'] + ' ' + r['label']:30} {cells[0]:>22} {cells[1]:>22}")
    for mode in ("page image", "OCR text only"):
        js = [results[f"{mode}|{r['id']}"]["judge"] for r in rows]
        pts = sum(min(j["key_points"], len(r["key_points"])) / len(r["key_points"]) for j, r in zip(js, rows)) / len(rows)
        print(f"{mode:13}: final answers {100 * sum(SCORE[j['final_answer']] for j in js) / len(js):.0f}%, "
              f"key points {100 * pts:.0f}%")
    u = llm.USAGE
    print(f"Claude usage this run: {u['calls']} calls, {u['input']:,} input + {u['output']:,} output tokens, "
          f"{u['web_searches']} web searches = "
          f"${(u['input'] * PRICE_IN + u['output'] * PRICE_OUT) / 1e6 + u['web_searches'] * PRICE_SEARCH / 1000:.2f}")


if __name__ == "__main__":
    main()

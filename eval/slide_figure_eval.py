"""When should lecture slide images be attached: always, or only as a fallback after a text-only answer fails?

Two question groups:
  figure - eval/datasets/slide_figure_set.jsonl, answerable only from a lecture diagram; graded against reference answers
  normal - in-scope test-set questions the slide text answers; checked for which source answered
Each runs through the corrective loop under config.SLIDE_IMAGES_MODE = "always" and "fallback", recording whether
images were used and what each answer cost. Results are cached in eval/results/slide_figure_eval_v2.json.

Usage: python eval/slide_figure_eval.py
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
from pipeline_eval import IN_SCOPE_IDS, JUDGE_SCHEMA, JUDGE_SYSTEM, PRICE_IN, PRICE_OUT, PRICE_SEARCH  # noqa: E402

CACHE = RESULTS / "slide_figure_eval_v2.json"
SCORE = {"correct": 1, "partial": 0.5, "wrong": 0}
MODES = ("always", "fallback")


def cost(u):
    return (u.get("input", 0) * PRICE_IN + u.get("output", 0) * PRICE_OUT) / 1e6 + \
        u.get("web_searches", 0) * PRICE_SEARCH / 1000


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    index = Index()
    router = Router(index)
    figure = [json.loads(l) for l in (DATASETS / "slide_figure_set.jsonl").read_text(encoding="utf-8").splitlines()
              if l.strip()]
    normal = [json.loads(l) for l in (DATASETS / "testset.jsonl").read_text(encoding="utf-8").splitlines()
              if l.strip() and json.loads(l)["id"] in IN_SCOPE_IDS]
    cases = [("figure", r) for r in figure] + [("normal", r) for r in normal]

    for mode in MODES:
        config.SLIDE_IMAGES_MODE = mode
        for group, r in cases:
            key = f"{mode}|{r['id']}"
            if key not in cache:
                before = dict(llm.USAGE)
                plan = planner.prepare(r["question"], index, router, force_course=r["course"])
                reply, source, trace, _, _ = corrective.answer_checked(r["question"], plan, [], log=None)
                used = {k: llm.USAGE[k] - before.get(k, 0) for k in ("input", "output", "web_searches", "calls")}
                res = {"answer": reply, "source": source, "trace": trace, "usage": used,
                       "images": any(t.startswith("slide images:") for t in trace)}
                if group == "figure":
                    content = (f"<question>\n{r['question']}\n</question>\n\n<reference_answer>\n{r['answer']}\n"
                               "Key points:\n" + "\n".join(f"- {k}" for k in r["key_points"]) +
                               f"\n</reference_answer>\n\n<solution>\n{reply}\n</solution>")
                    res["judge"] = json.loads(llm.ask(
                        JUDGE_SYSTEM, [{"role": "user", "content": content}], 8000, stream=False,
                        output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}}))
                cache[key] = res
                CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
            print(f"  {mode:8} {r['id']}: {cache[key]['source']}", flush=True)
    config.SLIDE_IMAGES_MODE = "fallback"

    print(f"\n{'id':11} {'group':6} | {'always':^30} | {'fallback':^30}")
    for group, r in cases:
        cells = []
        for mode in MODES:
            res = cache[f"{mode}|{r['id']}"]
            verdict = res["judge"]["final_answer"] if "judge" in res else "-"
            cells.append(f"{verdict:8} {res['source']:6} {'img' if res['images'] else '   '} ${cost(res['usage']):.3f}")
        print(f"{r['id']:11} {group:6} | {cells[0]:30} | {cells[1]:30}")
    for group in ("figure", "normal"):
        rows = [r for g, r in cases if g == group]
        for mode in MODES:
            rs = [cache[f"{mode}|{r['id']}"] for r in rows]
            acc = (f"correct {100 * sum(SCORE[x['judge']['final_answer']] for x in rs) / len(rs):.0f}%, "
                   if group == "figure" else "")
            print(f"{group:6} {mode:8}: {acc}from slides {sum(x['source'] == 'slides' for x in rs)}/{len(rs)}, "
                  f"images used {sum(x['images'] for x in rs)}/{len(rs)}, avg cost ${sum(cost(x['usage']) for x in rs) / len(rs):.3f}, "
                  f"avg calls {sum(x['usage']['calls'] for x in rs) / len(rs):.1f}")


if __name__ == "__main__":
    main()

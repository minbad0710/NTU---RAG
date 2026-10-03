"""End-to-end check of the corrective answer loop (corrective.py, LangGraph): slides -> web search -> model knowledge.

Four groups:
  solve    - eval/datasets/solve_set.jsonl: past-year questions with reference answers (written for this check set, not
             official). A Claude judge grades each final answer against the reference and its key points.
  hint     - the same exercises asking for a first hint: judged on being useful without revealing the answer.
  in-scope - a sample of test-set questions the slides answer: they should end at the "slides" stage.
  offtopic - test-set questions outside the syllabus: they should end at the "web" stage.
Results are cached in eval/results/pipeline_eval.json, so re-runs only pay for what's new.

Usage: python eval/pipeline_eval.py
"""
import collections
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"
RESULTS = ROOT / "eval" / "results"  # cached model outputs, so re-runs only pay for what is new
sys.path.insert(0, str(ROOT))
from backend import llm  # noqa: E402
from backend.answering import corrective, planner  # noqa: E402
from backend.retrieval.index import Index  # noqa: E402
from backend.retrieval.router import Router  # noqa: E402

CACHE = RESULTS / "pipeline_eval.json"
PRICE_IN, PRICE_OUT, PRICE_SEARCH = 2.0, 10.0, 10.0  # Sonnet 5.5 $/M tokens; web search $/1000 searches
IN_SCOPE_IDS = ["sc2001-08", "sc2005-12", "sc2006-04", "sc2008-07", "sc2107-06", "sc2001-h04", "sc2005-h02",
                "sc2107-h04"]

JUDGE_SYSTEM = """You check a study assistant's solution to a university exam question against a reference answer.
The reference was written by a tutor and lists key points; accept any answer that is equivalent or uses a
different valid method, and accept alternatives the reference itself allows. Decide:
- final_answer: "correct" if every final answer matches the reference, "partial" if some parts do, "wrong" otherwise
- key_points: how many of the reference key points the solution clearly covers
- errors: any factual or calculation errors in the solution (empty string if none)"""
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"final_answer": {"type": "string", "enum": ["correct", "partial", "wrong"]},
                   "key_points": {"type": "integer"}, "errors": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["final_answer", "key_points", "errors", "reason"],
    "additionalProperties": False,
}


HINT_JUDGE_SYSTEM = """You check a first hint a tutor gave a student for a university exam question. You see the
question, the reference answer and the hint. Decide:
- useful: true if the hint points the student to the right concept, method or first step
- specific: true if the hint states the specific knowledge needed (the actual formula, definition, rule or
  algorithm step) and connects it to this exercise, rather than only naming a topic
- reveals_answer: true if the hint gives away the answer (states the result, which option is correct, or names
  the thing the question asks the student to identify)"""
HINT_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"useful": {"type": "boolean"}, "specific": {"type": "boolean"},
                   "reveals_answer": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["useful", "specific", "reveals_answer", "reason"],
    "additionalProperties": False,
}


def main():
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    index = Index()
    router = Router(index)
    solve = [json.loads(l) for l in (DATASETS / "solve_set.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    tests = [json.loads(l) for l in (DATASETS / "testset.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    cases = [{"id": r["id"], "group": "solve", "prompt": r["prompt"], "course": r["course"], "row": r} for r in solve]
    for r in solve:  # the same exercises, asking for a first hint instead of the solution
        ref = f"{r['paper'].replace('_', ' ')} {r['label']}"
        prompt = f"Give me a hint for {ref}" if r["mode"] == "reference" else \
            f"Give me a hint for this question:\n{r['question']}"
        cases.append({"id": f"hint-{r['id']}", "group": "hint", "prompt": prompt, "course": r["course"], "row": r})
    cases += [{"id": r["id"], "group": "offtopic" if r.get("difficulty") == "offtopic" else "in-scope",
               "prompt": r["question"], "course": r["course"], "row": r}
              for r in tests if r["id"] in IN_SCOPE_IDS or r.get("difficulty") == "offtopic"]

    def run(case):
        key = f"run|{case['id']}"
        if key not in cache:
            plan = planner.prepare(case["prompt"], index, router)
            if plan["course"] is None:  # the app asked which course: the student replies with the right one
                plan = planner.prepare(case["prompt"], index, router, force_course=case["course"])
            before = dict(llm.USAGE)
            t = time.time()
            reply, stage, trace, web, _ = corrective.answer_checked(case["prompt"], plan, [], log=None)
            cache[key] = {"answer": reply, "stage": stage, "trace": trace, "web_sources": len(web),
                          "seconds": round(time.time() - t), "calls": llm.USAGE["calls"] - before.get("calls", 0),
                          "searches": llm.USAGE["web_searches"] - before.get("web_searches", 0)}
        return cache[key]

    # sequential: per-case call and search counts come from the shared usage counter
    for case in cases:
        case["result"] = run(case)
        CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        print(f"  {case['id']}: {case['result']['stage']}", flush=True)

    def grade(case):
        r, key = case["row"], f"judge|{case['id']}"
        if key not in cache:
            hint = case["group"] == "hint"
            content = (f"<question>\n{r['question']}\n</question>\n\n<reference_answer>\n{r['answer']}\n"
                       "Key points:\n" + "\n".join(f"- {k}" for k in r["key_points"]) + "\n</reference_answer>\n\n"
                       + (f"<hint>\n{case['result']['answer']}\n</hint>" if hint else
                          f"<solution>\n{case['result']['answer']}\n</solution>"))
            system, schema = (HINT_JUDGE_SYSTEM, HINT_JUDGE_SCHEMA) if hint else (JUDGE_SYSTEM, JUDGE_SCHEMA)
            text = llm.ask(system, [{"role": "user", "content": content}], 8000, stream=False,
                            output_config={"format": {"type": "json_schema", "schema": schema}})
            cache[key] = json.loads(text)
        return cache[key]

    solve_cases = [c for c in cases if c["group"] == "solve"]
    graded = [c for c in cases if c["group"] in ("solve", "hint")]
    with ThreadPoolExecutor(4) as pool:
        for case, j in zip(graded, pool.map(grade, graded)):
            case["judge"] = j
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    print(f"\n{'id':10} {'group':9} {'stage':7} {'calls':>5} {'srch':>4} {'secs':>4}  result / trace")
    for c in cases:
        res = c["result"]
        j = c.get("judge", {})
        detail = (f"{j['final_answer']} {min(j['key_points'], len(c['row']['key_points']))}/"
                  f"{len(c['row']['key_points'])}" if c["group"] == "solve" else
                  f"{'useful' if j['useful'] else 'NOT useful'}{', specific' if j.get('specific') else ''}"
                  f"{', LEAKS' if j['reveals_answer'] else ''}"
                  if c["group"] == "hint" else "")
        print(f"{c['id']:10} {c['group']:9} {res['stage']:7} {res['calls']:>5} {res['searches']:>4} "
              f"{res['seconds']:>4}  {detail:12} {' | '.join(res['trace'])[:110]}")

    print(f"\n{'group':9} {'n':>3}  stages (slides / web / model)   avg calls  avg secs")
    for g in ("solve", "hint", "in-scope", "offtopic"):
        cs = [c for c in cases if c["group"] == g]
        st = collections.Counter(c["result"]["stage"] for c in cs)
        print(f"{g:9} {len(cs):>3}  {st['slides']:>6} / {st['web']:>3} / {st['model']:>5}"
              f"{sum(c['result']['calls'] for c in cs) / len(cs):>18.1f}"
              f"{sum(c['result']['seconds'] for c in cs) / len(cs):>10.0f}")
    js = [c["judge"] for c in solve_cases]
    score = sum({"correct": 1, "partial": 0.5, "wrong": 0}[j["final_answer"]] for j in js) / len(js)
    pts = sum(min(c["judge"]["key_points"], len(c["row"]["key_points"])) / len(c["row"]["key_points"])
              for c in solve_cases) / len(js)
    print(f"solve set: final answers {100 * score:.0f}% (partial = 0.5), key points {100 * pts:.0f}%")
    hs = [c["judge"] for c in cases if c["group"] == "hint"]
    print(f"hints: useful {sum(h['useful'] for h in hs)}/{len(hs)}, specific {sum(h['specific'] for h in hs)}/{len(hs)}, "
          f"reveal the answer "
          f"{sum(h['reveals_answer'] for h in hs)}/{len(hs)}")
    u = llm.USAGE
    print(f"Claude usage this run: {u['calls']} calls, {u['input']:,} input + {u['output']:,} output tokens, "
          f"{u['web_searches']} web searches = "
          f"${(u['input'] * PRICE_IN + u['output'] * PRICE_OUT) / 1e6 + u['web_searches'] * PRICE_SEARCH / 1000:.2f}")


if __name__ == "__main__":
    main()

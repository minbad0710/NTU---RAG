"""Score the pipeline (intent, router, retrieval) against eval/datasets/testset.jsonl. No Claude calls.

Usage: python eval/run_eval.py [--model M] [--margin 0.3] [--no-strip] [--no-prefix]
                               [--expand off|rewrite|decompose|auto] [--no-abstract] [--verbose]
"""
import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"
RESULTS = ROOT / "eval" / "results"  # cached model outputs, so re-runs only pay for what is new
sys.path.insert(0, str(ROOT))
from backend import config  # noqa: E402
from backend.answering import planner  # noqa: E402
from backend.retrieval import query  # noqa: E402
from backend.retrieval.index import Index  # noqa: E402
from backend.retrieval.router import Router  # noqa: E402

KS = (1, 3, 6)
LLM_CACHE = RESULTS / "llm_cache.json"


def cache_llm_to_disk():
    """Reuse local-LLM outputs across eval runs (keyed by model + prompt), so configs compare the same rewrites."""

    cache = json.loads(LLM_CACHE.read_text(encoding="utf-8")) if LLM_CACHE.exists() else {}
    generate = query._generate

    def cached(prompt, **kwargs):
        key = f"{query.LOCAL_MODEL}\n{prompt}"
        if key not in cache:
            cache[key] = generate(prompt, **kwargs)
            LLM_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        return cache[key]

    query._generate = cached


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.EMBED_MODEL)
    ap.add_argument("--margin", type=float, default=None, help="ask threshold (0 = never ask)")
    ap.add_argument("--no-strip", action="store_true", help="don't strip request words before searching")
    ap.add_argument("--no-prefix", action="store_true", help="no bge query instruction")
    ap.add_argument("--expand", default=config.EXPAND, choices=["off", "rewrite", "decompose", "auto"])
    ap.add_argument("--no-abstract", action="store_true", help="no step-back rewrites for broad questions")
    ap.add_argument("--bm25-weight", type=float, default=config.BM25_WEIGHT, help="keyword share of hybrid search (0 = off)")
    ap.add_argument("--verbose", action="store_true", help="list misroutes and retrieval misses")
    args = ap.parse_args()

    config.USE_QUERY_PREFIX = not args.no_prefix
    config.BM25_WEIGHT = args.bm25_weight
    if args.expand != "off" or not args.no_abstract:
        cache_llm_to_disk()
    rows = [json.loads(l) for l in (DATASETS / "testset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    index = Index(args.model)
    router = Router(index, **({} if args.margin is None else {"margin": args.margin}))

    stats = collections.defaultdict(collections.Counter)
    notes, expand_time = [], 0.0
    for r in rows:
        t = time.perf_counter()
        plan = planner.prepare(r["question"], index, router, strip=not args.no_strip,
                           expand=args.expand, abstract=not args.no_abstract)
        stats["llm"].update(n=1, called=len(plan["queries"]) > 1)
        expand_time += time.perf_counter() - t

        if r["course"] is None:
            stats["ambiguous"].update(n=1, asked=plan["course"] is None)
            continue

        group = r.get("difficulty", "easy")
        # if the router asked, assume the student replies with the right course
        answered = plan if plan["course"] else planner.prepare(r["question"], index, router, strip=not args.no_strip,
                                                           expand=args.expand, abstract=not args.no_abstract,
                                                           force_course=r["course"])
        hits = [c["source"] for c in answered["hits"]]
        want = set(r["expected_sources"])
        if group == "offtopic":  # no slide answers these (they test the web fallback in pipeline_eval.py)
            continue
        if r["intent"] == "qa":  # abstraction check only applies to Q&A
            flagged = bool(answered["specificity"] < config.ABSTRACT_THRESHOLD)  # numpy bools OR instead of add
            stats["abstraction"].update(n=1, pos=group == "abstract", caught=flagged and group == "abstract",
                                        false_alarm=flagged and group != "abstract")
        if group == "abstract":
            stats["abstract"].update(covered=len(want & set(hits[:6])), wanted=len(want))
        if "exam_keywords" in r:  # past-paper lookup: is each returned question part on topic?
            on_topic = [bool(re.search(r["exam_keywords"], c["text"], re.I)) for c in answered["exam_hits"][:5]]
            stats["exam"].update(n=1, relevant=sum(on_topic), returned=len(on_topic), hit3=any(on_topic[:3]))
            if not any(on_topic[:3]):
                notes.append(f"  exam miss {r['id']}: {r['question'][:55]!r} got="
                             f"{[c['source'][:17] + ' ' + c['label'] for c in answered['exam_hits'][:3]]}")
        res = collections.Counter(
            n=1,
            intent=plan["intent"] == r["intent"],
            route_ok=plan["course"] == r["course"],
            route_wrong=plan["course"] not in (None, r["course"]),
            route_ask=plan["course"] is None,
            **{f"hit@{k}": bool(want & set(hits[:k])) for k in KS},
        )
        if "expected_parts" in r:  # multi-part: every part must be covered
            res["parts"] = 1
            res["all_parts@6"] = all(set(p) & set(hits) for p in r["expected_parts"])
        for key in (group, "ALL"):
            stats[key].update(res)

        if res["route_wrong"]:
            notes.append(f"  misroute  {r['id']}: {r['question'][:55]!r} -> {plan['course']}")
        if not res["intent"]:
            notes.append(f"  intent    {r['id']}: {r['question'][:55]!r} -> {plan['intent']}")
        if not res["hit@6"]:
            notes.append(f"  miss@6    {r['id']}: {r['question'][:55]!r} queries={plan['queries']} got={hits[:3]}")

    pct = lambda s, key: f"{100 * s[key] / s['n']:5.1f}%" if s["n"] else "   - "
    print(f"model={args.model} margin={router.margin} strip={not args.no_strip} "
          f"prefix={not args.no_prefix} expand={args.expand}")
    print(f"{'group':6} {'n':>3} | {'intent':>6} | {'route ok':>8} {'wrong':>6} {'asked':>6} | "
          + " ".join(f"{'hit@' + str(k):>6}" for k in KS) + " | all parts@6")
    for g in ("easy", "hard", "multi", "abstract", "ALL"):
        s = stats[g]
        if not s["n"]:
            continue
        parts = f"{100 * s['all_parts@6'] / s['parts']:5.1f}%" if s["parts"] else ""
        print(f"{g:6} {s['n']:>3} | {pct(s, 'intent'):>6} | {pct(s, 'route_ok'):>8} {pct(s, 'route_wrong'):>6} "
              f"{pct(s, 'route_ask'):>6} | " + " ".join(f"{pct(s, f'hit@{k}'):>6}" for k in KS) + f" | {parts}")
    a = stats["ambiguous"]
    print(f"ambiguous: asked {a['asked']}/{a['n']}   |   local LLM called on {pct(stats['llm'], 'called')} of questions"
          f"   |   avg query prep {1000 * expand_time / len(rows):.0f} ms")
    ab, s = stats["abstraction"], stats["abstract"]
    if ab["pos"]:
        print(f"abstraction check (Q&A, threshold {config.ABSTRACT_THRESHOLD}): caught {ab['caught']}/{ab['pos']} broad, "
              f"false alarms {ab['false_alarm']}/{ab['n'] - ab['pos']} specific   |   broad questions: "
              f"{100 * s['covered'] / s['wanted']:.0f}% of relevant lecture files in top 6")
    e = stats["exam"]
    if e["n"]:
        print(f"past-paper lookup ({e['n']} questions): precision@5 "
              f"{100 * e['relevant'] / max(e['returned'], 1):.0f}%, on-topic part in top 3 for {e['hit3']}/{e['n']}")
    if args.verbose:
        print("\n".join(notes))


if __name__ == "__main__":
    main()

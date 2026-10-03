"""Blind pairwise answer-quality check of how slide (Q&A) questions are answered.

Compares, per question:
  fusion - the app's broad-question path: 3 step-back rewrites (local LLM) widen retrieval to 12 chunks; one answer
  direct - one answer from the top 12 chunks of the original question
Earlier results on the 12 broad questions (fusion vs direct: 4-4, 4 ties; specific: 3-1, 8 ties) led to removing
two other approaches: answering 3 rewrites separately and merging (4-7) and 3 sub-questions merged (1-10).
Question sets:
  broad    - the broad test questions the abstraction check flags (the app rewrites these)
  specific - 6 easy + 6 hard (paraphrased) test questions, forced through the same path to see if rewriting
             helps questions the app would normally answer directly
A Claude judge scores both answers (1-5 on coverage, accuracy, organisation, conciseness) and picks a winner.
Each pair is judged twice with the order swapped; a win counts only if both orders agree, otherwise it's a tie.
Answers and judgments are cached in eval/results/answer_quality.json, so re-runs only pay for what's new.

Usage: python eval/answer_quality.py [--sets broad,specific]
"""
import argparse
import collections
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "eval" / "datasets"
RESULTS = ROOT / "eval" / "results"  # cached model outputs, so re-runs only pay for what is new
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from backend import config, llm  # noqa: E402
from backend.answering import planner, prompts  # noqa: E402
from backend.retrieval.index import Index  # noqa: E402
from backend.retrieval.router import Router  # noqa: E402
from run_eval import cache_llm_to_disk  # noqa: E402

CACHE = RESULTS / "answer_quality.json"
CRITERIA = ("coverage", "accuracy", "organization", "conciseness")
PRICE_IN, PRICE_OUT = 2.0, 10.0  # Claude Sonnet 5.5, $ per million tokens
SPECIFIC_IDS = [  # spread over the 5 courses; the hard ones include retrieval misses, where rewriting may help
    "sc2001-08", "sc2005-07", "sc2006-04", "sc2008-07", "sc2107-06", "sc2005-12",
    "sc2001-h04", "sc2005-h02", "sc2107-h04", "sc2008-h03", "sc2006-h02", "sc2107-h02",
]

JUDGE_SYSTEM = """You grade answers from a study assistant for the NTU course {course} {name}.
A student preparing for the exam asked a question. You get the lecture excerpts the assistant could use
and two answers, A and B. Score each answer from 1 (poor) to 5 (excellent) on:
- coverage: answers everything the question asks, as far as the course's slides cover it
- accuracy: agrees with the excerpts and contains no errors (general knowledge clearly marked as such is fine)
- organization: easy to follow and revise from
- conciseness: no padding or repetition for the amount of content
Then pick the answer the student would rather receive, or "tie" if they are equally useful.
Judge substance, not length: a longer answer is better only if the extra content is relevant and correct."""

SCORE = {"type": "object", "properties": {c: {"type": "integer"} for c in CRITERIA},
         "required": list(CRITERIA), "additionalProperties": False}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"A": SCORE, "B": SCORE, "winner": {"type": "string", "enum": ["A", "B", "tie"]},
                   "reason": {"type": "string"}},
    "required": ["A", "B", "winner", "reason"],
    "additionalProperties": False,
}


def generate(question, plan):
    system = prompts.system_prompt(plan["course"], plan["intent"])
    content = prompts.final_content(question, plan)
    return llm.ask(system, [{"role": "user", "content": content}], 12000, stream=False)


def judge(row, excerpts, first, second):
    content = (f"{prompts.format_context(excerpts)}\n\n<question>{row['question']}</question>\n\n"
               f"<answer_A>\n{first}\n</answer_A>\n\n<answer_B>\n{second}\n</answer_B>")
    system = JUDGE_SYSTEM.format(course=row["course"], name=config.COURSE_NAMES[row["course"]])
    text = llm.ask(system, [{"role": "user", "content": content}], 8000, stream=False,
                    output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}})
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default="broad,specific")
    args = ap.parse_args()
    cands, sets = ["fusion"], args.sets.split(",")

    cache_llm_to_disk()  # reuse the eval's cached local-LLM outputs
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    index = Index()
    router = Router(index)
    rows = [json.loads(l) for l in (DATASETS / "testset.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    selected = [(r, "broad") for r in rows if r.get("difficulty") == "abstract" and "broad" in sets]
    selected += [(r, "specific") for r in rows if r["id"] in SPECIFIC_IDS and "specific" in sets]

    # plans for every (question, mode); broad questions not flagged by the threshold are skipped
    cases = []
    for r, group in selected:
        threshold = config.ABSTRACT_THRESHOLD if group == "broad" else math.inf
        plans = {"fusion": planner.prepare(r["question"], index, router, force_course=r["course"],
                                       abstract_threshold=threshold)}
        if group == "broad" and not plans["fusion"]["broad"]:
            continue
        direct = planner.prepare(r["question"], index, router, force_course=r["course"], abstract=False)
        direct["hits"] = index.search(index.embed_queries(direct["queries"]), r["course"], 12, texts=direct["queries"])
        plans["direct"] = direct
        seen, excerpts = set(), []
        for p in plans.values():
            for c in p["hits"]:
                if (c["source"], c["pages"]) not in seen:
                    seen.add((c["source"], c["pages"]))
                    excerpts.append(c)
        cases.append({"row": r, "group": group, "plans": plans, "excerpts": excerpts})
    print(f"{len(cases)} questions ({', '.join(f'{g}: {sum(c['group'] == g for c in cases)}' for g in sets)}); "
          f"comparing {', '.join(cands)} against direct")

    def answers(case):
        out = {}
        for mode, plan in case["plans"].items():
            key = f"{mode}|{case['row']['id']}"
            if key not in cache:
                cache[key] = generate(case["row"]["question"], plan)
            out[mode] = cache[key]
        return out

    with ThreadPoolExecutor(3) as pool:
        for case, ans in zip(cases, pool.map(answers, cases)):
            case["answers"] = ans
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    def judgments(case):
        out = {}
        for cand in cands:
            for order in ((cand, "direct"), ("direct", cand)):
                key = f"judge|{case['row']['id']}|{order[0]}-{order[1]}"
                if key not in cache:
                    a = case["answers"]
                    cache[key] = judge(case["row"], case["excerpts"], a[order[0]], a[order[1]])
                out[order] = cache[key]
        return out

    with ThreadPoolExecutor(3) as pool:
        for case, js in zip(cases, pool.map(judgments, cases)):
            case["judgments"] = js
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    for cand in cands:
        print(f"\n===== {cand} vs direct =====")
        print(f"{'question':50} {'set':8} {cand:>7} {'direct':>6}  winner   words {cand}/direct")
        summary = {g: {"win": collections.Counter(), "scores": {m: collections.defaultdict(list) for m in
                                                                 (cand, "direct")}, "words": []} for g in sets}
        for case in cases:
            votes, per_mode = [], collections.defaultdict(list)
            s = summary[case["group"]]
            for order in ((cand, "direct"), ("direct", cand)):
                j = case["judgments"][order]
                for label, mode in zip("AB", order):
                    for c in CRITERIA:
                        s["scores"][mode][c].append(j[label][c])
                        per_mode[mode].append(j[label][c])
                votes.append({"A": order[0], "B": order[1], "tie": "tie"}[j["winner"]])
            result = votes[0] if votes[0] == votes[1] else "tie"
            s["win"][result] += 1
            words = [len(case["answers"][m].split()) for m in (cand, "direct")]
            s["words"].append(words)
            print(f"{case['row']['question'][:50]:50} {case['group']:8} "
                  f"{sum(per_mode[cand]) / 8:7.2f} {sum(per_mode['direct']) / 8:6.2f}  {result:8} {words[0]}/{words[1]}")
        for g, s in summary.items():
            n = sum(s["win"].values())
            if not n:
                continue
            print(f"\n  {g} ({n}): {cand} wins {s['win'][cand]}, direct wins {s['win']['direct']}, "
                  f"tie/inconsistent {s['win']['tie']}")
            for c in CRITERIA:
                a, b = (sum(s["scores"][m][c]) / len(s["scores"][m][c]) for m in (cand, "direct"))
                print(f"    {c:13} {cand} {a:.2f}  direct {b:.2f}")
            print(f"    avg words     {cand} {sum(w[0] for w in s['words']) / n:.0f}  "
                  f"direct {sum(w[1] for w in s['words']) / n:.0f}")
    u = llm.USAGE
    print(f"\nClaude usage this run: {u['calls']} calls, {u['input']:,} input + {u['output']:,} output tokens "
          f"= ${(u['input'] * PRICE_IN + u['output'] * PRICE_OUT) / 1e6:.2f}")


if __name__ == "__main__":
    main()

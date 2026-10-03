# Evaluation

| Script | What it checks | Cost |
|---|---|---|
| `run_eval.py` | Intent, routing, retrieval, abstraction threshold, past-paper lookup on `testset.jsonl` | Free (local LLM only) |
| `answer_quality.py` | Blind pairwise answer quality: broad-question fusion vs direct answer | Claude calls (cached) |
| `pipeline_eval.py` | The corrective chain (slides -> web -> model): which stage answers, solve-set correctness | Claude calls + web searches (cached) |
| `latency.py` | Time per stage (prepare, Ollama, each Claude call) and time to first streamed text, on 4 typical queries | ~20 Claude calls |
| `figure_eval.py` | Past-paper questions with figures: scanned page attached vs OCR text only | Claude calls (cached) |
| `slide_figure_eval.py` | Slide images on every answer ("always") vs only after a failed text answer ("fallback") | Claude calls (cached) |

Run them from the project folder, e.g. `.venv/Scripts/python eval/run_eval.py`.

- `datasets/`: the test sets (`testset.jsonl`, `solve_set.jsonl`, `slide_figure_set.jsonl`).
- `results/`: cached model outputs and judgments, so re-runs only pay for new cases. Delete a file to re-run that eval from scratch. `results/archive/` holds caches from earlier pipeline versions; no script reads them.

`solve_set.jsonl` holds 16 past-year questions with reference answers and key points written for this check set (not official solutions). `id`, `course`, `paper`, `label`, `prompt` (how the student asks: by reference or pasted text), `mode`, `question`, `type` (mcq/calculation/explain), `answer`, `key_points`, `in_slides`.

# Test set

`testset.jsonl` has one test question per line:

| Field | Meaning |
|---|---|
| `id` | Unique id, `<course>-<nn>` or `ambig-<nn>` |
| `question` | What the student types. Mixed style on purpose: full sentences, lowercase shorthand, a few with the course code |
| `course` | The course the router should pick. `null` means the question is ambiguous and the router should ask |
| `intent` | `qa` (explain), `past_paper` (find past-year questions) or `generate` (make practice questions) |
| `expected_sources` | Lecture files that answer the question. Retrieval counts as a hit if **any** of them is in the top-k |
| `confusable_with` | Optional. Other courses a naive router might pick |
| `difficulty` | Optional. `hard`: paraphrased without the slides' key terms, the way a student who doesn't know the term would ask. `multi`: asks about two or more things from different lectures. `abstract`: a broad question covering a whole topic ("Explain the data link layer"), used to test the abstraction threshold. `offtopic`: a plausible question the slides don't cover, used to test the web fallback (excluded from retrieval metrics). Missing means easy |
| `exam_keywords` | Only on `past_paper` rows. Case-insensitive regex; a returned past-paper question part counts as on-topic if its OCR text matches. Approximate labels, used for precision@5 and "on-topic part in top 3" |
| `expected_parts` | Only on `multi` rows. One list of acceptable files per part; "all parts@6" counts a hit only if every part is covered in the top 6 |

## What it measures

- **Router accuracy:** predicted course == `course`. For `null` rows, the router should flag low confidence rather than guess.
- **Intent accuracy:** predicted intent == `intent`.
- **Retrieval hit@k:** at least one of the `expected_sources` appears in the top-k chunks, with retrieval restricted to the correct course.

`past_paper` and `generate` rows reuse the lecture files as `expected_sources`, because they test whether the topic is identified correctly. Checking which specific past-paper questions come back can be added once the papers have been OCR'd.

"""Pick one course per question: explicit course code > sticky current course > best-matching chunk.

Routing by the course of the best-matching chunk beat a logistic-regression classifier trained on the
chunks (98% vs ~70% on eval/datasets/testset.jsonl): questions and slides embed differently, and the retrieval
model is trained for exactly that gap.
"""
import re

import numpy as np

COURSE_RE = re.compile(r"\b(?:SC|CE|CZ)\s?(\d{4})\b", re.I)  # slides use SC/CE/CZ prefixes for the same course
MARGIN = 0.3  # ask the user when the top two courses' probabilities are closer than this
TEMPERATURE = 0.02  # turns best-chunk cosine scores per course into probabilities
STICKY_MIN = 0.1  # stay on the current course unless it gets less than this


def explicit_course(text, labels):
    for digits in COURSE_RE.findall(text):
        if f"SC{digits}" in labels:
            return f"SC{digits}"
    return None


class Router:
    def __init__(self, index, margin=MARGIN):
        self.index, self.margin = index, margin
        self.labels = sorted(set(index.courses))
        is_lecture = getattr(index, "kinds", np.full(len(index.courses), "lecture")) == "lecture"
        self.masks = [(index.courses == c) & is_lecture for c in self.labels]

    def probs(self, qvec):
        sims = self.index.vecs @ qvec
        best = np.array([sims[m].max() for m in self.masks])
        p = np.exp((best - best.max()) / TEMPERATURE)
        return dict(zip(self.labels, p / p.sum()))

    def route(self, text, qvecs, current=None):
        """Returns (course or None if unsure, probabilities per course)."""
        code = explicit_course(text, self.labels)
        if code:
            return code, {c: float(c == code) for c in self.labels}
        qvec = np.atleast_2d(qvecs).mean(axis=0)
        p = self.probs(qvec / np.linalg.norm(qvec))
        if current and p.get(current, 0) >= STICKY_MIN:
            return current, p
        (c1, p1), (_, p2) = sorted(p.items(), key=lambda kv: -kv[1])[:2]
        return (c1 if p1 - p2 >= self.margin else None), p

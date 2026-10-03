"""BM25 keyword search over the chunks, the lexical half of hybrid search (see Index.search).

Tokens keep compound terms whole as well as their parts, so "CSMA/CD" matches as "csma/cd" (exact) and also as
"csma" and "cd"; the same for "802.11", "TA0CCR0" and "bellman-ford".
"""
import collections
import math
import re

import numpy as np

from backend import config
from backend.retrieval.query import STOPWORDS

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./_-][a-z0-9]+)*")


def tokens(text):
    out = []
    for t in TOKEN_RE.findall(text.lower()):
        parts = re.split(r"[./_-]", t)
        out += ([t] if len(parts) > 1 else []) + [p for p in parts if p]
    return [t for t in out if t not in STOPWORDS]


class BM25:
    def __init__(self, texts):
        docs = [collections.Counter(tokens(t)) for t in texts]
        self.n = len(docs)
        self.lengths = np.array([sum(d.values()) for d in docs], dtype=np.float32)
        self.avg_len = float(self.lengths.mean()) if self.n else 1.0
        postings = collections.defaultdict(lambda: ([], []))  # term -> (doc ids, term counts)
        for i, d in enumerate(docs):
            for term, tf in d.items():
                postings[term][0].append(i)
                postings[term][1].append(tf)
        self.postings = {t: (np.array(ids), np.array(tfs, dtype=np.float32)) for t, (ids, tfs) in postings.items()}

    def scores(self, text):
        """BM25 score of every chunk for one query (0 where no query term occurs)."""
        out = np.zeros(self.n, dtype=np.float32)
        k1, b = config.BM25_K1, config.BM25_B
        norm = k1 * (1 - b + b * self.lengths / self.avg_len)
        for term in set(tokens(text)):
            if term not in self.postings:
                continue
            ids, tf = self.postings[term]
            idf = math.log(1 + (self.n - len(ids) + 0.5) / (len(ids) + 0.5))
            out[ids] += idf * tf * (k1 + 1) / (tf + norm[ids])
        return out

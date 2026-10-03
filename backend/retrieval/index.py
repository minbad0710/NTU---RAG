"""The search index: lecture chunks and past-paper question parts with their embeddings, searched with numpy."""
import collections
import json
import math
import re

import numpy as np

from backend import config
from backend.ingest.build_index import build_index
from backend.retrieval import embedding, query
from backend.retrieval.keyword import BM25


class Index:
    def __init__(self, model=config.EMBED_MODEL):
        d = embedding.index_dir(model)
        if not (d / "chunks.json").exists():
            build_index(model)
        self.model = model
        self.vecs = np.load(d / "vectors.npy")
        self.chunks = json.loads((d / "chunks.json").read_text(encoding="utf-8"))
        self.courses = np.array([c["course"] for c in self.chunks])
        self.kinds = np.array([c.get("kind", "lecture") for c in self.chunks])
        lectures = [c for c in self.chunks if c.get("kind", "lecture") == "lecture"]
        self.df = collections.Counter(w for c in lectures for w in set(query.words(c["text"])))
        self.n_lectures = len(lectures)
        # keyword index over the same text that was embedded (file name + chunk), built in about a second
        self.bm25 = BM25([f"{c['source']}\n{c['text']}" for c in self.chunks])

    def embed_queries(self, texts):
        return embedding.embed(texts, self.model, is_query=True)

    def search(self, qvecs, course=None, k=config.TOP_K, kind="lecture", texts=None):
        """Top-k chunks for one or more queries, merged with reciprocal rank fusion (RRF).

        Hybrid search: each query vector gives a cosine ranking, and each query text (texts, in the same order)
        a BM25 keyword ranking among this course's chunks; all rankings are fused. A keyword ranking only
        credits chunks that contain a query term, so a query with no matching term changes nothing.
        config.FUSION picks how the lists are merged (see _weighted for the score-based alternative)."""
        if config.FUSION == "weighted":
            return self._weighted(qvecs, course, k, kind, texts)
        fused = np.zeros(len(self.chunks))
        for qv in np.atleast_2d(qvecs):
            scores = self.vecs @ qv
            ranks = np.empty(len(scores))
            ranks[np.argsort(-scores)] = np.arange(len(scores))
            fused += 1.0 / (config.RRF_K + ranks)
        allowed = self.kinds == kind
        if course:
            allowed &= self.courses == course
        if texts and config.BM25_WEIGHT:
            for text in texts:
                scores = np.where(allowed, self.bm25.scores(text), 0)
                hits = np.flatnonzero(scores > 0)
                order = hits[np.argsort(-scores[hits])]
                fused[order] += config.BM25_WEIGHT / (config.RRF_K + np.arange(len(order)))
        fused[~allowed] = -1
        top = [i for i in np.argsort(-fused)[:k] if fused[i] > -1]
        return [self.chunks[i] for i in top]

    def specificity(self, topic, qvec, course):
        """Low = broad question (see config.ABSTRACT_THRESHOLD)."""
        idf = sum(math.log((self.n_lectures + 1) / (self.df[w] + 1)) for w in query.content_words(topic))
        scores = np.sort(self.vecs[(self.courses == course) & (self.kinds == "lecture")] @ qvec)[::-1]
        return idf + config.ABSTRACT_W * (scores[0] - scores[min(9, len(scores) - 1)])

    def find_exam(self, ref, course=None):
        """Past-paper parts named by a reference like AY2015/16 S2 Q4(a); every part of Q4 if no part is given."""
        found = []
        for c in self.chunks:
            if c.get("kind") != "exam" or c["year"] != ref["year"] or (course and c["course"] != course):
                continue
            if ref["sem"] and c["sem"] != ref["sem"]:
                continue
            m = re.match(r"Q(\d+)(?:\((\w+)\))?$", c["label"])
            if m and int(m[1]) == ref["q"] and not (ref["part"] and m[2] and m[2].lower() != ref["part"]):
                found.append(c)
        return found

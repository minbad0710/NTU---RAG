"""Local embeddings (fastembed, bge family) and where each model's index is stored."""
import numpy as np
from fastembed import TextEmbedding

from backend import config

_embedders = {}


def embed(texts, model=config.EMBED_MODEL, is_query=False):
    if model not in _embedders:
        _embedders[model] = TextEmbedding(model)
    if is_query and config.USE_QUERY_PREFIX and "bge" in model.lower():
        texts = [config.BGE_QUERY_PREFIX + t for t in texts]
    vecs = np.array(list(_embedders[model].embed(texts)), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def index_dir(model):
    return config.INDEX_DIR / model.split("/")[-1]

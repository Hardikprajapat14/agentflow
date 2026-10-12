"""Free, local embeddings. No API key and no network calls at query time."""
import logging
import threading

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_model = None
_hasher = None


def _fastembed():
    global _model
    with _lock:
        if _model is None:
            from fastembed import TextEmbedding

            _model = TextEmbedding(model_name=get_settings().embedding_model)
    return _model


def _hashing():
    global _hasher
    if _hasher is None:
        from sklearn.feature_extraction.text import HashingVectorizer

        _hasher = HashingVectorizer(n_features=get_settings().embedding_dim, alternate_sign=False, norm="l2",
                                    ngram_range=(1, 2), stop_words="english")
    return _hasher


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    s = get_settings()
    if s.embedding_backend == "hashing":
        mat = _hashing().transform(texts).toarray()
        return [row.astype(float).tolist() for row in mat]
    vectors = list(_fastembed().embed(texts, batch_size=32))
    out = []
    for v in vectors:
        v = np.asarray(v, dtype=float)
        n = np.linalg.norm(v)
        out.append((v / n if n else v).tolist())
    if out and len(out[0]) != s.embedding_dim:
        raise RuntimeError(
            f"Embedding model returned {len(out[0])} dims but EMBEDDING_DIM={s.embedding_dim}. "
            "Update EMBEDDING_DIM and the database migration to match."
        )
    return out


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]

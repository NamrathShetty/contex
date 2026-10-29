"""Text embeddings for the semantic layer.

Follows the optional-dependency pattern used by ``tokens.py``: if
``sentence-transformers`` is installed it is used for true semantic embeddings;
otherwise we fall back to a deterministic, dependency-free lexical hashing
vector so the semantic layer works offline (it then measures lexical overlap, a
reasonable proxy). The active backend is reported via ``EMBEDDER_LABEL``.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_LEXICAL_DIM = 512


def _lexical_vector(text: str) -> list[float]:
    """Deterministic L2-normalized term-frequency hash vector (no dependencies)."""
    vec = [0.0] * _LEXICAL_DIM
    for token in _WORD_RE.findall(text.lower()):
        digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        vec[digest % _LEXICAL_DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in vec))
    if norm > 0.0:
        vec = [value / norm for value in vec]
    return vec


try:
    from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

    _MODEL: "SentenceTransformer | None" = None

    def _backend_embed(texts: list[str]) -> list[list[float]]:
        global _MODEL
        if _MODEL is None:
            _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        vectors = _MODEL.encode(texts, normalize_embeddings=True)
        return [[float(v) for v in row] for row in vectors]

    EMBEDDER_LABEL = "sentence-transformers all-MiniLM-L6-v2"

except Exception:
    _backend_embed = None  # type: ignore[assignment]
    EMBEDDER_LABEL = "lexical hashing (offline)"


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Embed a batch of texts, falling back to the lexical vector on any failure."""
    items = [text or "" for text in texts]
    if not items:
        return []
    if _backend_embed is not None:
        try:
            return _backend_embed(items)
        except Exception:
            pass
    return [_lexical_vector(text) for text in items]


def embed_text(text: str) -> list[float]:
    """Embed a single text."""
    return embed_texts([text])[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity clamped to [0.0, 1.0]; 0.0 for empty/mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))

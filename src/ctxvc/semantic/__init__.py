"""Semantic layer: meaning-aware operations over the canonical content store.

This package is a thin, optional *analysis* layer. It never participates in
object identity or storage (those stay content-hash based and deterministic);
it only interprets the meaning of already-stored content via embeddings.

Public API:
    embeddings: embed_text, embed_texts, cosine_similarity, EMBEDDER_LABEL
    diff:       compare_texts, classify_change, detect_renames, RENAME_THRESHOLD
    search:     search_files, search_snapshots
"""
from __future__ import annotations

from ctxvc.semantic.embeddings import (
    EMBEDDER_LABEL,
    cosine_similarity,
    embed_text,
    embed_texts,
)
from ctxvc.semantic.diff import (
    RENAME_THRESHOLD,
    classify_change,
    compare_texts,
    detect_renames,
)
from ctxvc.semantic.search import search_files, search_snapshots

__all__ = [
    "EMBEDDER_LABEL",
    "cosine_similarity",
    "embed_text",
    "embed_texts",
    "RENAME_THRESHOLD",
    "classify_change",
    "compare_texts",
    "detect_renames",
    "search_files",
    "search_snapshots",
]

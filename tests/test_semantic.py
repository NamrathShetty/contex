"""Tests for the semantic layer (embeddings + local search)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ctxvc.semantic import cosine_similarity, embed_text, search_files


def test_embed_returns_vector() -> None:
    vector = embed_text("hello world")
    assert isinstance(vector, list)
    assert vector


def test_identical_text_is_maximally_similar() -> None:
    vector = embed_text("database migrations")
    assert cosine_similarity(vector, vector) > 0.99


def test_search_files_ranks_relevant_first(
    tool_root: Path, make_snapshot: Callable[..., str]
) -> None:
    make_snapshot(
        {
            "db.md": "database migrations using sqlite with write ahead logging",
            "vec.md": "vector embeddings power semantic search and similarity ranking",
        }
    )
    results = search_files(tool_root, "vector embeddings semantic similarity", top_k=2)
    assert results
    assert results[0]["path"] == "vec.md"

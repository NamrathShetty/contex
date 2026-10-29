"""Tests for the Qdrant-backed vector index using an in-memory Qdrant.

Skipped automatically if ``qdrant-client`` is not installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

pytest.importorskip("qdrant_client")

from qdrant_client import QdrantClient  # noqa: E402

from ctxvc.errors import CtxvcError  # noqa: E402
from ctxvc.semantic import vindex  # noqa: E402
from ctxvc.semantic.vindex import QdrantIndex, search_index, sync_index  # noqa: E402


def _index() -> QdrantIndex:
    return QdrantIndex(name="team", collection="ctxvc", client=QdrantClient(":memory:"))


def test_sync_dedups_and_counts(make_snapshot: Callable[..., str], tool_root: Path) -> None:
    sid1 = make_snapshot(
        {"db.md": "database sqlite", "vec.md": "vector embeddings semantic search"}
    )
    make_snapshot(
        {"db.md": "database sqlite", "auth.md": "authentication login tokens"},
        parent=sid1,
    )
    index = _index()
    result = sync_index(tool_root, index)
    assert result["objects_indexed"] == 3  # db.md shared across snapshots
    assert index.count() == 3


def test_search_returns_relevant_hit(
    make_snapshot: Callable[..., str], tool_root: Path
) -> None:
    sid = make_snapshot(
        {"db.md": "database sqlite", "vec.md": "vector embeddings semantic search similarity"}
    )
    index = _index()
    sync_index(tool_root, index)
    hits = search_index(index, "vector embeddings semantic similarity search", top_k=2)
    assert hits[0]["path"] == "vec.md"
    assert sid in hits[0]["snapshots"]


def test_resync_is_idempotent(make_snapshot: Callable[..., str], tool_root: Path) -> None:
    make_snapshot({"a.md": "alpha text", "b.md": "beta text"})
    index = _index()
    sync_index(tool_root, index)
    sync_index(tool_root, index)
    assert index.count() == 2


def test_embedder_mismatch_rejected_then_rebuild(
    make_snapshot: Callable[..., str], tool_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_snapshot({"a.md": "alpha text"})
    index = _index()
    sync_index(tool_root, index)

    monkeypatch.setattr(vindex, "EMBEDDER_LABEL", "some-other-embedder v9")
    with pytest.raises(CtxvcError):
        sync_index(tool_root, index)

    # rebuild replaces the collection with the new embedder
    result = sync_index(tool_root, index, rebuild=True)
    assert result["objects_indexed"] == 1


def test_search_missing_collection_errors(tool_root: Path) -> None:
    index = QdrantIndex(name="empty", collection="nope", client=QdrantClient(":memory:"))
    with pytest.raises(CtxvcError):
        search_index(index, "anything")

"""Tests for the content-addressed object store."""
from __future__ import annotations

from pathlib import Path

from ctxvc.const import OBJECTS_DIR
from ctxvc.store import (
    build_snapshot_id,
    hash_text,
    object_exists,
    read_object,
    write_object,
)


def test_object_roundtrip(tool_root: Path) -> None:
    content_hash = write_object(tool_root, "hello world")
    assert object_exists(tool_root, content_hash)
    assert read_object(tool_root, content_hash) == "hello world"


def test_object_dedup_same_hash(tool_root: Path) -> None:
    h1 = write_object(tool_root, "same content")
    h2 = write_object(tool_root, "same content")
    assert h1 == h2


def test_different_content_different_hash(tool_root: Path) -> None:
    assert write_object(tool_root, "a") != write_object(tool_root, "b")


def test_legacy_plaintext_object_is_readable(tool_root: Path) -> None:
    content_hash = hash_text("legacy content")
    (tool_root / OBJECTS_DIR / f"{content_hash}.txt").write_text(
        "legacy content", encoding="utf-8"
    )
    assert object_exists(tool_root, content_hash)
    assert read_object(tool_root, content_hash) == "legacy content"


def test_snapshot_ids_unique_within_same_second() -> None:
    ids = {build_snapshot_id() for _ in range(100)}
    assert len(ids) == 100

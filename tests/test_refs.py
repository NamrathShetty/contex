"""Tests for the SQLite-backed refs layer (branches, tags, handoffs, resolution)."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ctxvc.refs import (
    create_branch,
    create_tag,
    delete_tag,
    list_branches,
    list_handoffs,
    list_tags,
    read_refs,
    record_handoff,
    resolve_revision,
    switch_branch,
)


def test_initial_refs_have_main(tool_root: Path) -> None:
    refs = read_refs(tool_root)
    assert refs["current_branch"] == "main"


def test_create_and_switch_branch(tool_root: Path, make_snapshot: Callable[..., str]) -> None:
    sid = make_snapshot({"a.md": "x"})
    create_branch(tool_root, "feature", sid)
    branches, _ = list_branches(tool_root)
    assert "feature" in branches and "main" in branches

    switch_branch(tool_root, "feature")
    _, current = list_branches(tool_root)
    assert current == "feature"


def test_tags_add_and_remove(tool_root: Path, make_snapshot: Callable[..., str]) -> None:
    sid = make_snapshot({"a.md": "x"})
    create_tag(tool_root, "v1", sid)
    assert list_tags(tool_root)["v1"] == sid

    delete_tag(tool_root, "v1")
    assert "v1" not in list_tags(tool_root)


def test_resolve_revision_by_prefix(tool_root: Path, make_snapshot: Callable[..., str]) -> None:
    sid = make_snapshot({"a.md": "x"})
    refs = read_refs(tool_root)
    assert resolve_revision(tool_root, refs, sid[:8]) == sid


def test_handoffs_recorded_and_listed(tool_root: Path, make_snapshot: Callable[..., str]) -> None:
    sid = make_snapshot({"a.md": "x"})
    record_handoff(tool_root, "planner", "coder", sid, "implement feature")
    handoffs = list_handoffs(tool_root, 10)
    assert handoffs[0]["source_agent"] == "planner"
    assert handoffs[0]["target_agent"] == "coder"
    assert handoffs[0]["revision"] == sid

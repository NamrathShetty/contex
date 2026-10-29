"""Shared pytest fixtures and helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pytest

# Defensive: ensure the src/ layout is importable even outside an editable install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ctxvc.const import CONFIG_PATH, OBJECTS_DIR, SNAPSHOTS_DIR  # noqa: E402
from ctxvc.refs import init_refs, record_snapshot, set_head  # noqa: E402
from ctxvc.store import build_snapshot_id, utc_now, write_json, write_object  # noqa: E402


def init_repo(root: Path) -> Path:
    """Create a fresh ``.ctxvc`` repository under ``root`` and return its tool dir."""
    tool_root = root / ".ctxvc"
    (tool_root / SNAPSHOTS_DIR).mkdir(parents=True)
    (tool_root / OBJECTS_DIR).mkdir(parents=True)
    write_json(tool_root / CONFIG_PATH, {"version": 1, "created_at": utc_now(), "agents": {}})
    init_refs(tool_root)
    return tool_root


def make_snapshot_in(tool_root: Path, files: dict[str, str], parent: str | None = None) -> str:
    """Write objects + a snapshot for ``files`` and advance HEAD; return the id."""
    entries = []
    for path, text in files.items():
        content_hash = write_object(tool_root, text)
        entries.append({"path": path, "content_hash": content_hash, "size": len(text)})
    snapshot_id = build_snapshot_id()
    snapshot = {
        "id": snapshot_id,
        "parent": parent,
        "created_at": utc_now(),
        "message": "test",
        "source": "test",
        "files": entries,
        "total_tokens": 0,
    }
    write_json(tool_root / SNAPSHOTS_DIR / f"{snapshot_id}.json", snapshot)
    record_snapshot(tool_root, snapshot)
    set_head(tool_root, snapshot_id)
    return snapshot_id


@pytest.fixture
def tool_root(tmp_path: Path) -> Path:
    return init_repo(tmp_path)


@pytest.fixture
def make_snapshot(tool_root: Path) -> Callable[..., str]:
    def _make(files: dict[str, str], parent: str | None = None) -> str:
        return make_snapshot_in(tool_root, files, parent)

    return _make


@pytest.fixture
def repo_factory(tmp_path: Path) -> Callable[..., Path]:
    """Return a factory that creates independent repos under the test's tmp dir."""

    def _make(name: str = "repo") -> Path:
        return init_repo(tmp_path / name)

    return _make


@pytest.fixture
def snapshot() -> Callable[..., str]:
    """Return the snapshot helper for use with arbitrary repos (multi-repo tests)."""
    return make_snapshot_in

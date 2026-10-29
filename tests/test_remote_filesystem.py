"""Tests for the filesystem remote push/pull synchronization."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from ctxvc.errors import CtxvcError
from ctxvc.remote import pull, push
from ctxvc.remote.filesystem import FilesystemRemote
from ctxvc.store import load_snapshot, read_object


def test_push_pull_roundtrip(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str], tmp_path: Path
) -> None:
    repo_a = repo_factory("a")
    repo_b = repo_factory("b")
    remote = FilesystemRemote("origin", tmp_path / "remote")

    sid = snapshot(repo_a, {"f.md": "alpha content"})
    pushed = push(repo_a, remote, "main")
    assert pushed["snapshots_uploaded"] == 1
    assert pushed["objects_uploaded"] == 1

    pulled = pull(repo_b, remote, "main")
    assert pulled["snapshots_downloaded"] == 1
    snap = load_snapshot(repo_b, sid)
    assert snap["id"] == sid
    content_hash = snap["files"][0]["content_hash"]
    assert read_object(repo_b, content_hash) == "alpha content"


def test_second_push_only_uploads_new_objects(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str], tmp_path: Path
) -> None:
    repo_a = repo_factory("a")
    remote = FilesystemRemote("origin", tmp_path / "remote")

    sid1 = snapshot(repo_a, {"f.md": "v1"})
    push(repo_a, remote, "main")
    snapshot(repo_a, {"f.md": "v1", "g.md": "v2"}, parent=sid1)

    second = push(repo_a, remote, "main")
    # only g.md is new (f.md object already present remotely)
    assert second["objects_uploaded"] == 1


def test_divergence_is_rejected_without_force(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str], tmp_path: Path
) -> None:
    repo_a = repo_factory("a")
    repo_b = repo_factory("b")
    remote = FilesystemRemote("origin", tmp_path / "remote")

    sid1 = snapshot(repo_a, {"f.md": "base"})
    push(repo_a, remote, "main")
    pull(repo_b, remote, "main")

    # A advances the remote
    snapshot(repo_a, {"f.md": "base", "a.md": "from-a"}, parent=sid1)
    push(repo_a, remote, "main")

    # B diverges from the same base
    snapshot(repo_b, {"f.md": "base", "b.md": "from-b"}, parent=sid1)
    with pytest.raises(CtxvcError):
        push(repo_b, remote, "main")


def test_force_push_overrides_divergence(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str], tmp_path: Path
) -> None:
    repo_a = repo_factory("a")
    repo_b = repo_factory("b")
    remote = FilesystemRemote("origin", tmp_path / "remote")

    sid1 = snapshot(repo_a, {"f.md": "base"})
    push(repo_a, remote, "main")
    pull(repo_b, remote, "main")

    snapshot(repo_a, {"f.md": "base", "a.md": "from-a"}, parent=sid1)
    push(repo_a, remote, "main")

    sid_b = snapshot(repo_b, {"f.md": "base", "b.md": "from-b"}, parent=sid1)
    forced = push(repo_b, remote, "main", force=True)
    assert forced["target"] == sid_b
    assert remote.get_ref("main") == sid_b

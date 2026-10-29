"""Push/pull negotiation with fast-forward safety, shared by all remote backends.

Objects and snapshots are immutable and content/id-addressed, so syncing them is
just "upload/download what's missing". Refs are mutable, so updates use the
remote's compare-and-swap plus a fast-forward check: a push is rejected if the
remote ref is not an ancestor of what you're pushing (and vice versa for pull),
unless ``force`` is given.
"""
from __future__ import annotations

from pathlib import Path

from ctxvc.const import SNAPSHOTS_DIR
from ctxvc.errors import CtxvcError
from ctxvc.refs import read_refs, record_snapshot, set_branch, set_head
from ctxvc.remote.base import Remote
from ctxvc.store import (
    load_snapshot,
    object_exists,
    read_object,
    write_json,
    write_object,
)


def _local_chain(tool_root: Path, head: str | None) -> list[dict[str, object]]:
    """Walk the local parent chain from ``head``, returning snapshots child-first."""
    chain: list[dict[str, object]] = []
    seen: set[str] = set()
    sid = head
    while sid is not None and sid not in seen:
        seen.add(sid)
        snap = load_snapshot(tool_root, sid)
        chain.append(snap)
        parent = snap.get("parent")
        sid = str(parent) if parent else None
    return chain


def _local_ancestors(tool_root: Path, head: str | None) -> set[str]:
    return {str(snap["id"]) for snap in _local_chain(tool_root, head)}


def push(
    tool_root: Path, remote: Remote, branch: str, force: bool = False
) -> dict[str, object]:
    """Upload a branch's missing snapshots/objects then fast-forward the remote ref."""
    refs = read_refs(tool_root)
    branches = refs.get("branches", {})
    if not isinstance(branches, dict) or branch not in branches:
        raise CtxvcError(f"unknown local branch: {branch}")
    local_target = branches[branch]
    if local_target is None:
        raise CtxvcError(f"branch '{branch}' has no snapshot to push")
    local_target = str(local_target)

    chain = _local_chain(tool_root, local_target)  # child-first
    ancestors = {str(snap["id"]) for snap in chain}

    objects_uploaded = 0
    snapshots_uploaded = 0
    for snap in reversed(chain):  # oldest-first: parents before children
        snap_id = str(snap["id"])
        if remote.has_snapshot(snap_id):
            continue
        for entry in snap.get("files", []):
            content_hash = str(entry["content_hash"])
            if not remote.has_object(content_hash):
                remote.put_object(content_hash, read_object(tool_root, content_hash))
                objects_uploaded += 1
        remote.put_snapshot(snap_id, snap)
        snapshots_uploaded += 1

    remote_old = remote.get_ref(branch)
    if not force and remote_old is not None and remote_old not in ancestors:
        raise CtxvcError(
            f"non-fast-forward: remote '{branch}' is at {remote_old}, which is not "
            f"an ancestor of {local_target}; pull first or use --force"
        )
    if not remote.update_ref(branch, remote_old, local_target):
        raise CtxvcError(
            f"remote '{branch}' changed during push; pull and retry"
        )

    return {
        "branch": branch,
        "target": local_target,
        "remote_old": remote_old,
        "snapshots_uploaded": snapshots_uploaded,
        "objects_uploaded": objects_uploaded,
    }


def pull(
    tool_root: Path, remote: Remote, branch: str, force: bool = False
) -> dict[str, object]:
    """Download a branch's missing snapshots/objects then fast-forward the local ref."""
    remote_target = remote.get_ref(branch)
    if remote_target is None:
        raise CtxvcError(f"remote has no branch '{branch}'")
    remote_target = str(remote_target)

    # Walk the remote chain, pruning where we already have the snapshot locally.
    chain: list[dict[str, object]] = []
    seen: set[str] = set()
    sid: str | None = remote_target
    while sid is not None and sid not in seen:
        seen.add(sid)
        if (tool_root / SNAPSHOTS_DIR / f"{sid}.json").exists():
            break
        snap = remote.get_snapshot(sid)
        chain.append(snap)
        parent = snap.get("parent")
        sid = str(parent) if parent else None

    objects_downloaded = 0
    snapshots_downloaded = 0
    for snap in reversed(chain):  # oldest-first
        for entry in snap.get("files", []):
            content_hash = str(entry["content_hash"])
            if not object_exists(tool_root, content_hash):
                content = remote.get_object(content_hash)
                got = write_object(tool_root, content)
                if got != content_hash:
                    raise CtxvcError(
                        f"integrity error: object {content_hash} hashed to {got}"
                    )
                objects_downloaded += 1
        snap_id = str(snap["id"])
        write_json(tool_root / SNAPSHOTS_DIR / f"{snap_id}.json", snap)
        record_snapshot(tool_root, snap)
        snapshots_downloaded += 1

    refs = read_refs(tool_root)
    branches = refs.get("branches", {})
    local_old = branches.get(branch) if isinstance(branches, dict) else None
    remote_ancestors = _local_ancestors(tool_root, remote_target)
    if not force and local_old is not None and str(local_old) not in remote_ancestors:
        raise CtxvcError(
            f"non-fast-forward: local '{branch}' at {local_old} is not an ancestor "
            f"of {remote_target}; use --force to overwrite"
        )

    if refs.get("current_branch") == branch:
        set_head(tool_root, remote_target)
    else:
        set_branch(tool_root, branch, remote_target)

    return {
        "branch": branch,
        "target": remote_target,
        "local_old": local_old,
        "snapshots_downloaded": snapshots_downloaded,
        "objects_downloaded": objects_downloaded,
    }

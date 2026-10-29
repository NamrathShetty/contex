"""Reference and snapshot-index management, backed by SQLite for safe concurrency.

Public API kept compatible where practical:
- ``read_refs(tool_root)`` still returns ``{HEAD, current_branch, branches, tags}``.
- ``resolve_revision(tool_root, refs, revision)`` unchanged signature.

Mutations now go through atomic, transaction-scoped helpers (``set_head``,
``create_branch``, ``switch_branch``, ``create_tag``, ``delete_tag``,
``record_snapshot``) instead of read-modify-write on a JSON blob, so concurrent
writers cannot lose each other's updates.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ctxvc.const import REFS_PATH, SNAPSHOTS_DIR
from ctxvc.db import init_db, reader, writer
from ctxvc.errors import CtxvcError
from ctxvc.store import read_json, utc_now

# Branch-per-agent convention: each agent works on its own ``agent/<name>``
# branch, and context is moved between agents via handoffs (see ``record_handoff``).
AGENT_BRANCH_PREFIX = "agent/"


def agent_branch_name(agent: str) -> str:
    """Return the conventional branch name for an agent."""
    return f"{AGENT_BRANCH_PREFIX}{agent}"


def agent_from_branch(branch: str | None) -> str | None:
    """Return the agent name encoded in a branch, or None if not an agent branch."""
    if isinstance(branch, str) and branch.startswith(AGENT_BRANCH_PREFIX):
        return branch[len(AGENT_BRANCH_PREFIX):]
    return None


def default_refs() -> dict[str, object]:
    return {
        "HEAD": None,
        "current_branch": "main",
        "branches": {"main": None},
        "tags": {},
    }


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _seed_defaults(conn: sqlite3.Connection) -> None:
    _set_meta(conn, "current_branch", "main")
    _set_meta(conn, "HEAD", None)
    conn.execute(
        "INSERT OR IGNORE INTO branches(name, target) VALUES('main', NULL)"
    )


def _import_legacy_refs(conn: sqlite3.Connection, legacy: dict[str, object]) -> None:
    """Import a pre-existing refs.json into the database (one-time migration)."""
    current = str(legacy.get("current_branch") or "main")
    head = legacy.get("HEAD")
    _set_meta(conn, "current_branch", current)
    _set_meta(conn, "HEAD", head if head is None else str(head))
    branches = legacy.get("branches") or {"main": head}
    if isinstance(branches, dict):
        for name, target in branches.items():
            conn.execute(
                "INSERT OR REPLACE INTO branches(name, target) VALUES(?, ?)",
                (str(name), None if target is None else str(target)),
            )
    tags = legacy.get("tags") or {}
    if isinstance(tags, dict):
        for name, target in tags.items():
            conn.execute(
                "INSERT OR REPLACE INTO tags(name, target) VALUES(?, ?)",
                (str(name), None if target is None else str(target)),
            )


def _backfill_snapshots(conn: sqlite3.Connection, tool_root: Path) -> None:
    """Backfill the snapshot index from existing snapshot JSON files (one-time)."""
    snapshots_dir = tool_root / SNAPSHOTS_DIR
    if not snapshots_dir.exists():
        return
    for path in snapshots_dir.glob("*.json"):
        try:
            data = read_json(path)
        except Exception:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO snapshots(id, parent, created_at, message, source, total_tokens) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                str(data.get("id") or path.stem),
                data.get("parent"),
                data.get("created_at"),
                data.get("message"),
                data.get("source"),
                data.get("total_tokens"),
            ),
        )


def _ensure_initialized(tool_root: Path) -> None:
    """Create schema, seed defaults, and migrate legacy data once (idempotent)."""
    init_db(tool_root)
    with reader(tool_root) as conn:
        if conn.execute("SELECT 1 FROM meta WHERE key='current_branch'").fetchone():
            return
    with writer(tool_root) as conn:
        # Re-check inside the write lock to avoid a race with a concurrent init.
        if conn.execute("SELECT 1 FROM meta WHERE key='current_branch'").fetchone():
            return
        _seed_defaults(conn)
        legacy_path = tool_root / REFS_PATH
        if legacy_path.exists():
            try:
                _import_legacy_refs(conn, read_json(legacy_path))
            except Exception:
                pass
        _backfill_snapshots(conn, tool_root)


def init_refs(tool_root: Path) -> None:
    """Initialize the refs/index store for a fresh repository."""
    _ensure_initialized(tool_root)


def read_refs(tool_root: Path) -> dict[str, object]:
    """Return a snapshot of refs as ``{HEAD, current_branch, branches, tags}``."""
    _ensure_initialized(tool_root)
    with reader(tool_root) as conn:
        current = _get_meta(conn, "current_branch") or "main"
        head = _get_meta(conn, "HEAD")
        branches = {
            row["name"]: row["target"]
            for row in conn.execute("SELECT name, target FROM branches")
        }
        tags = {
            row["name"]: row["target"]
            for row in conn.execute("SELECT name, target FROM tags")
        }
    if current not in branches:
        branches[current] = head
    # Keep HEAD consistent with the current branch's target.
    if head != branches.get(current):
        head = branches.get(current)
    return {
        "HEAD": head,
        "current_branch": current,
        "branches": branches,
        "tags": tags,
    }


def set_head(tool_root: Path, revision: str | None) -> None:
    """Atomically set HEAD and advance the current branch to the same revision."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        current = _get_meta(conn, "current_branch") or "main"
        _set_meta(conn, "HEAD", revision)
        conn.execute(
            "INSERT INTO branches(name, target) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET target=excluded.target",
            (current, revision),
        )


def create_branch(tool_root: Path, name: str, target: str | None) -> None:
    """Create a new branch pointing at target; error if it already exists."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        if conn.execute("SELECT 1 FROM branches WHERE name=?", (name,)).fetchone():
            raise CtxvcError(f"branch already exists: {name}")
        conn.execute(
            "INSERT INTO branches(name, target) VALUES(?, ?)", (name, target)
        )


def set_branch(tool_root: Path, name: str, target: str | None) -> None:
    """Create or update an arbitrary branch's target (does not change current)."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        conn.execute(
            "INSERT INTO branches(name, target) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET target=excluded.target",
            (name, target),
        )


def list_branches(tool_root: Path) -> tuple[dict[str, str | None], str | None]:
    """Return (branches, current_branch_name)."""
    _ensure_initialized(tool_root)
    with reader(tool_root) as conn:
        branches = {
            row["name"]: row["target"]
            for row in conn.execute("SELECT name, target FROM branches")
        }
        current = _get_meta(conn, "current_branch")
    return branches, current


def switch_branch(tool_root: Path, name: str) -> str | None:
    """Switch the current branch atomically; returns the branch's target."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        row = conn.execute("SELECT target FROM branches WHERE name=?", (name,)).fetchone()
        if row is None:
            raise CtxvcError(f"unknown branch: {name}")
        target = row["target"]
        _set_meta(conn, "current_branch", name)
        _set_meta(conn, "HEAD", target)
    return target


def create_tag(tool_root: Path, name: str, target: str | None) -> None:
    """Create a tag; error if it already exists."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        if conn.execute("SELECT 1 FROM tags WHERE name=?", (name,)).fetchone():
            raise CtxvcError(f"tag already exists: {name}")
        conn.execute("INSERT INTO tags(name, target) VALUES(?, ?)", (name, target))


def list_tags(tool_root: Path) -> dict[str, str | None]:
    _ensure_initialized(tool_root)
    with reader(tool_root) as conn:
        return {
            row["name"]: row["target"]
            for row in conn.execute("SELECT name, target FROM tags")
        }


def delete_tag(tool_root: Path, name: str) -> None:
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        cursor = conn.execute("DELETE FROM tags WHERE name=?", (name,))
        if cursor.rowcount == 0:
            raise CtxvcError(f"unknown tag: {name}")


def record_snapshot(tool_root: Path, snapshot: dict[str, object]) -> None:
    """Insert/replace a snapshot's metadata in the index."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots(id, parent, created_at, message, source, total_tokens) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (
                str(snapshot.get("id")),
                snapshot.get("parent"),
                snapshot.get("created_at"),
                snapshot.get("message"),
                snapshot.get("source"),
                snapshot.get("total_tokens"),
            ),
        )


def get_snapshot_meta(tool_root: Path, snapshot_id: str) -> dict[str, object] | None:
    """Return indexed metadata for a snapshot, or None if absent."""
    _ensure_initialized(tool_root)
    with reader(tool_root) as conn:
        row = conn.execute(
            "SELECT id, parent, created_at, message, source, total_tokens FROM snapshots WHERE id=?",
            (snapshot_id,),
        ).fetchone()
    return dict(row) if row else None


def record_handoff(
    tool_root: Path,
    source_agent: str | None,
    target_agent: str,
    revision: str | None,
    message: str | None = None,
) -> None:
    """Append a handoff record linking a source agent's context to a target agent."""
    _ensure_initialized(tool_root)
    with writer(tool_root) as conn:
        conn.execute(
            "INSERT INTO handoffs(created_at, source_agent, target_agent, revision, message) "
            "VALUES(?, ?, ?, ?, ?)",
            (utc_now(), source_agent, target_agent, revision, message),
        )


def list_handoffs(tool_root: Path, limit: int | None = None) -> list[dict[str, object]]:
    """Return recorded handoffs, most recent first."""
    _ensure_initialized(tool_root)
    sql = (
        "SELECT id, created_at, source_agent, target_agent, revision, message "
        "FROM handoffs ORDER BY id DESC"
    )
    params: tuple[object, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    with reader(tool_root) as conn:
        return [dict(row) for row in conn.execute(sql, params)]


def validate_ref_name(name: str, kind: str) -> None:
    if not name:
        raise CtxvcError(f"{kind} name cannot be empty")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/")
    if any(ch not in allowed for ch in name):
        raise CtxvcError(f"{kind} name may only contain letters, numbers, '-', '_', '/' ")


def resolve_revision(
    tool_root: Path, refs: dict[str, object], revision: str | None
) -> str | None:
    if revision is None:
        return None
    branches = refs.get("branches", {})
    if revision in branches:
        return branches[revision]
    tags = refs.get("tags", {})
    if revision in tags:
        return tags[revision]

    # Exact snapshot id (index first, then filesystem for un-indexed bodies).
    if get_snapshot_meta(tool_root, revision) is not None:
        return revision
    if (tool_root / SNAPSHOTS_DIR / f"{revision}.json").exists():
        return revision

    # Unique prefix match across the index and any on-disk snapshot bodies.
    matches: set[str] = set()
    with reader(tool_root) as conn:
        for row in conn.execute(
            "SELECT id FROM snapshots WHERE id LIKE ?", (revision + "%",)
        ):
            matches.add(row["id"])
    for path in (tool_root / SNAPSHOTS_DIR).glob(f"{revision}*.json"):
        matches.add(path.stem)

    ordered = sorted(matches)
    if len(ordered) == 1:
        return ordered[0]
    if len(ordered) > 1:
        raise CtxvcError(f"ambiguous revision prefix: {revision}")
    raise CtxvcError(f"unknown revision: {revision}")

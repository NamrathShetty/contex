"""SQLite-backed metadata store for refs and the snapshot index.

Why SQLite: refs (HEAD / branches / tags) are the only *mutable, contended*
state in a repository. Storing them in JSON and doing read-modify-write loses
updates under concurrent writers. SQLite gives us ACID transactions so
concurrent agents can update refs safely.

Concurrency model:
- WAL journal mode → readers never block writers and vice versa.
- ``busy_timeout`` → writers wait (instead of failing) when another write holds
  the lock.
- ``writer()`` issues ``BEGIN IMMEDIATE`` so concurrent writers serialize and
  read-modify-write sequences are atomic (no lost updates).

Snapshot *bodies* (files, graph deltas) remain immutable JSON files keyed by a
globally-unique id; only their metadata is indexed here for fast, concurrent
querying and revision resolution.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DB_FILENAME = "ctxvc.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS branches (
    name TEXT PRIMARY KEY,
    target TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    name TEXT PRIMARY KEY,
    target TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    parent TEXT,
    created_at TEXT,
    message TEXT,
    source TEXT,
    total_tokens INTEGER
);
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    source_agent TEXT,
    target_agent TEXT,
    revision TEXT,
    message TEXT
);
"""


def get_db_path(tool_root: Path) -> Path:
    return tool_root / DB_FILENAME


def _open(tool_root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_db_path(tool_root)), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(tool_root: Path) -> None:
    """Create the schema if absent (idempotent)."""
    conn = _open(tool_root)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def reader(tool_root: Path) -> Iterator[sqlite3.Connection]:
    """Open a read-only connection (no explicit transaction)."""
    conn = _open(tool_root)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def writer(tool_root: Path) -> Iterator[sqlite3.Connection]:
    """Open an exclusive write transaction (BEGIN IMMEDIATE); commit on success."""
    conn = _open(tool_root)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

from ctxvc.const import OBJECTS_DIR, SNAPSHOTS_DIR, TOOL_DIR
from ctxvc.errors import CtxvcError


def find_repo_root(start: Path, allow_missing: bool = False) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / TOOL_DIR).exists():
            return candidate
    if allow_missing:
        return current
    raise CtxvcError("no .ctxvc repository found; run 'ctxvc init' first")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes atomically: write to a temp file in the same dir, then os.replace.

    os.replace is atomic on both Windows and POSIX, so a crash mid-write leaves the
    existing file intact instead of a half-written, corrupt one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json(path: Path, payload: dict[str, object]) -> None:
    data = (json.dumps(payload, indent=2) + os.linesep).encode("utf-8")
    _atomic_write_bytes(path, data)


def read_json(path: Path) -> dict[str, object]:
    # utf-8-sig transparently strips a BOM if present (e.g. legacy files written
    # by tools that prepend one) and reads plain UTF-8 otherwise.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()


def build_snapshot_id() -> str:
    # Timestamp prefix keeps IDs chronologically sortable; the random suffix
    # prevents collisions when two snapshots are created within the same second.
    return dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)


def object_exists(tool_root: Path, content_hash: str) -> bool:
    gz_path, legacy_path = _object_paths(tool_root, content_hash)
    return gz_path.exists() or legacy_path.exists()


def _object_paths(tool_root: Path, content_hash: str) -> tuple[Path, Path]:
    """Return (gzip_path, legacy_plaintext_path) for a content hash."""
    objects_dir = tool_root / OBJECTS_DIR
    return objects_dir / f"{content_hash}.txt.gz", objects_dir / f"{content_hash}.txt"


def write_object(tool_root: Path, content: str) -> str:
    """Store content as a gzip-compressed, content-addressed object; return its hash.

    No-op if an object with the same hash already exists (in either the new gzip
    form or the legacy plaintext form).
    """
    content_hash = hash_text(content)
    gz_path, legacy_path = _object_paths(tool_root, content_hash)
    if gz_path.exists() or legacy_path.exists():
        return content_hash
    _atomic_write_bytes(gz_path, gzip.compress(content.encode("utf-8")))
    return content_hash


def read_object(tool_root: Path, content_hash: str) -> str:
    gz_path, legacy_path = _object_paths(tool_root, content_hash)
    if gz_path.exists():
        return gzip.decompress(gz_path.read_bytes()).decode("utf-8")
    if legacy_path.exists():
        return legacy_path.read_text(encoding="utf-8")
    raise CtxvcError(f"missing object for hash {content_hash}")


def resolve_entry_text(tool_root: Path, entry: dict[str, object] | None) -> str:
    if not entry:
        return ""
    content_hash = str(entry["content_hash"])
    if object_exists(tool_root, content_hash):
        return read_object(tool_root, content_hash)
    source_path = entry.get("source_path")
    if source_path:
        return Path(str(source_path)).read_text(encoding="utf-8")
    raise CtxvcError(f"unable to read content for {entry['path']}")


def load_snapshot(tool_root: Path, revision: str) -> dict[str, object]:
    snapshot_path = tool_root / SNAPSHOTS_DIR / f"{revision}.json"
    if not snapshot_path.exists():
        raise CtxvcError(f"unknown revision: {revision}")
    return read_json(snapshot_path)


def load_snapshot_index(tool_root: Path, revision: str) -> dict[str, dict[str, object]]:
    snapshot = load_snapshot(tool_root, revision)
    return {item["path"]: item for item in snapshot["files"]}

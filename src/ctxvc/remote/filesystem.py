"""Filesystem-backed remote: a shared directory (local path or network mount).

Layout mirrors a repository's storage so it is easy to inspect:

    <root>/
      objects/{hash}.txt.gz   gzip content-addressed blobs
      snapshots/{id}.json     immutable snapshot bodies
      refs.json               {branch_name: snapshot_id}
      refs.lock               transient mutex for ref compare-and-swap

Ref updates take an exclusive lock (O_CREAT|O_EXCL) so concurrent pushers on the
same machine / shared filesystem serialize their compare-and-swap safely.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ctxvc.errors import CtxvcError
from ctxvc.remote.base import Remote
from ctxvc.store import _atomic_write_bytes, write_json


class FilesystemRemote(Remote):
    def __init__(self, name: str, root: Path) -> None:
        self.name = name
        self.root = Path(root)
        self._objects = self.root / "objects"
        self._snapshots = self.root / "snapshots"
        self._refs_path = self.root / "refs.json"
        self._lock_path = self.root / "refs.lock"
        self._objects.mkdir(parents=True, exist_ok=True)
        self._snapshots.mkdir(parents=True, exist_ok=True)

    # --- objects -------------------------------------------------------------
    def _object_path(self, content_hash: str) -> Path:
        return self._objects / f"{content_hash}.txt.gz"

    def has_object(self, content_hash: str) -> bool:
        return self._object_path(content_hash).exists()

    def get_object(self, content_hash: str) -> str:
        path = self._object_path(content_hash)
        if not path.exists():
            raise CtxvcError(f"remote '{self.name}' missing object {content_hash}")
        return gzip.decompress(path.read_bytes()).decode("utf-8")

    def put_object(self, content_hash: str, content: str) -> None:
        path = self._object_path(content_hash)
        if path.exists():
            return
        _atomic_write_bytes(path, gzip.compress(content.encode("utf-8")))

    # --- snapshots -----------------------------------------------------------
    def _snapshot_path(self, snapshot_id: str) -> Path:
        return self._snapshots / f"{snapshot_id}.json"

    def has_snapshot(self, snapshot_id: str) -> bool:
        return self._snapshot_path(snapshot_id).exists()

    def get_snapshot(self, snapshot_id: str) -> dict[str, object]:
        path = self._snapshot_path(snapshot_id)
        if not path.exists():
            raise CtxvcError(f"remote '{self.name}' missing snapshot {snapshot_id}")
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def put_snapshot(self, snapshot_id: str, payload: dict[str, object]) -> None:
        path = self._snapshot_path(snapshot_id)
        if path.exists():
            return
        write_json(path, payload)

    # --- refs (with compare-and-swap) ---------------------------------------
    def _read_refs(self) -> dict[str, str | None]:
        if not self._refs_path.exists():
            return {}
        data = json.loads(self._refs_path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}

    def get_ref(self, name: str) -> str | None:
        return self._read_refs().get(name)

    def list_refs(self) -> dict[str, str | None]:
        return self._read_refs()

    def update_ref(self, name: str, expected: str | None, new: str | None) -> bool:
        with self._lock():
            refs = self._read_refs()
            if refs.get(name) != expected:
                return False
            if new is None:
                refs.pop(name, None)
            else:
                refs[name] = new
            write_json(self._refs_path, refs)
            return True

    @contextmanager
    def _lock(self, timeout: float = 10.0) -> Iterator[None]:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                break
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise CtxvcError(
                        f"timed out acquiring ref lock on remote '{self.name}'"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                os.unlink(self._lock_path)
            except OSError:
                pass

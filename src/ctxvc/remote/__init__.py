"""Pluggable remotes for ctxvc push/pull.

Remote configurations live in ``config.json`` under ``remotes``::

    "remotes": {
      "origin": {"type": "filesystem", "path": "../shared-context-remote"}
    }

Use :func:`open_remote` to instantiate a configured remote by name.
"""
from __future__ import annotations

from pathlib import Path

from ctxvc.config import read_config
from ctxvc.errors import CtxvcError
from ctxvc.remote.base import Remote
from ctxvc.remote.filesystem import FilesystemRemote
from ctxvc.remote.s3 import S3Remote
from ctxvc.remote.sync import pull, push

REMOTE_TYPES = ("filesystem", "s3")


def open_remote(repo_root: Path, tool_root: Path, name: str) -> Remote:
    """Instantiate a configured remote backend by name."""
    config = read_config(tool_root)
    remotes = config.get("remotes", {})
    if not isinstance(remotes, dict) or name not in remotes:
        raise CtxvcError(f"unknown remote: {name}")
    spec = remotes[name]
    if not isinstance(spec, dict):
        raise CtxvcError(f"invalid remote config for '{name}'")
    rtype = spec.get("type")
    if rtype == "filesystem":
        raw = str(spec.get("path") or "")
        if not raw:
            raise CtxvcError(f"remote '{name}' is missing a path")
        path = Path(raw)
        root = path if path.is_absolute() else (repo_root / path)
        return FilesystemRemote(name, root)
    if rtype == "s3":
        bucket = spec.get("bucket")
        if not bucket:
            raise CtxvcError(f"remote '{name}' is missing a bucket")
        return S3Remote(
            name,
            bucket=str(bucket),
            prefix=str(spec.get("prefix") or ""),
            endpoint_url=spec.get("endpoint_url"),  # type: ignore[arg-type]
            region=spec.get("region"),  # type: ignore[arg-type]
            profile=spec.get("profile"),  # type: ignore[arg-type]
        )
    raise CtxvcError(f"unsupported remote type: {rtype}")


__all__ = [
    "Remote",
    "FilesystemRemote",
    "S3Remote",
    "open_remote",
    "push",
    "pull",
    "REMOTE_TYPES",
]

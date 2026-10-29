"""Tests for the S3 remote using an in-memory fake client (no boto3 / network).

The fake mirrors AWS/MinIO conditional-write semantics: ``IfNoneMatch="*"``
fails with 412 if the key exists, and ``IfMatch=<etag>`` fails with 412 if the
key changed. ETags are content md5s, exactly as S3 reports them.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Callable

import pytest

from ctxvc.errors import CtxvcError
from ctxvc.remote import pull, push
from ctxvc.remote.s3 import S3Remote
from ctxvc.store import load_snapshot, read_object


class FakeClientError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakeS3:
    """Minimal in-memory stand-in for a boto3 S3 client."""

    def __init__(self) -> None:
        self.store: dict[str, tuple[bytes, str]] = {}

    @staticmethod
    def _etag(body: bytes) -> str:
        return '"' + hashlib.md5(body).hexdigest() + '"'

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.store:
            raise FakeClientError(404, "NotFound")
        return {}

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.store:
            raise FakeClientError(404, "NoSuchKey")
        body, etag = self.store[Key]
        return {"Body": io.BytesIO(body), "ETag": etag}

    def put_object(  # noqa: N803
        self,
        Bucket: str,
        Key: str,
        Body: bytes,
        IfMatch: str | None = None,
        IfNoneMatch: str | None = None,
    ) -> dict[str, Any]:
        exists = Key in self.store
        if IfNoneMatch == "*" and exists:
            raise FakeClientError(412, "PreconditionFailed")
        if IfMatch is not None and (not exists or self.store[Key][1] != IfMatch):
            raise FakeClientError(412, "PreconditionFailed")
        etag = self._etag(Body)
        self.store[Key] = (Body, etag)
        return {"ETag": etag}

    def delete_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        self.store.pop(Key, None)
        return {}

    def list_objects_v2(  # noqa: N803
        self, Bucket: str, Prefix: str = "", ContinuationToken: str | None = None
    ) -> dict[str, Any]:
        keys = [k for k in self.store if k.startswith(Prefix)]
        return {"Contents": [{"Key": k} for k in keys], "IsTruncated": False}


def _remote(client: FakeS3, name: str = "origin") -> S3Remote:
    return S3Remote(name, bucket="b", prefix="ctx/", client=client)


def test_s3_push_pull_roundtrip(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str]
) -> None:
    client = FakeS3()
    repo_a = repo_factory("a")
    repo_b = repo_factory("b")

    sid = snapshot(repo_a, {"f.md": "alpha"})
    push(repo_a, _remote(client), "main")
    pull(repo_b, _remote(client), "main")

    snap = load_snapshot(repo_b, sid)
    assert snap["id"] == sid
    assert read_object(repo_b, snap["files"][0]["content_hash"]) == "alpha"


def test_s3_cas_rejects_wrong_expected(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str]
) -> None:
    client = FakeS3()
    repo_a = repo_factory("a")
    snapshot(repo_a, {"f.md": "alpha"})
    remote = _remote(client)
    push(repo_a, remote, "main")

    assert remote.update_ref("main", "WRONG", "x") is False


def test_s3_divergence_rejected(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str]
) -> None:
    client = FakeS3()
    repo_a = repo_factory("a")
    repo_b = repo_factory("b")

    sid1 = snapshot(repo_a, {"f.md": "base"})
    push(repo_a, _remote(client), "main")
    pull(repo_b, _remote(client), "main")

    snapshot(repo_a, {"f.md": "base", "a.md": "x"}, parent=sid1)
    push(repo_a, _remote(client), "main")

    snapshot(repo_b, {"f.md": "base", "b.md": "y"}, parent=sid1)
    with pytest.raises(CtxvcError):
        push(repo_b, _remote(client), "main")


def test_s3_force_push_overrides(
    repo_factory: Callable[..., Path], snapshot: Callable[..., str]
) -> None:
    client = FakeS3()
    repo_a = repo_factory("a")
    repo_b = repo_factory("b")

    sid1 = snapshot(repo_a, {"f.md": "base"})
    push(repo_a, _remote(client), "main")
    pull(repo_b, _remote(client), "main")

    snapshot(repo_a, {"f.md": "base", "a.md": "x"}, parent=sid1)
    push(repo_a, _remote(client), "main")

    sid_b = snapshot(repo_b, {"f.md": "base", "b.md": "y"}, parent=sid1)
    forced = push(repo_b, _remote(client), "main", force=True)
    assert forced["target"] == sid_b

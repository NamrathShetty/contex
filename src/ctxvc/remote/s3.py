"""S3-compatible remote (AWS S3, MinIO, Cloudflare R2).

Objects and snapshots are plain keys under an optional prefix. Refs are stored
one key per branch and updated with **conditional writes** for true
compare-and-swap:

- creating a ref uses ``IfNoneMatch="*"`` (put only if the key is absent),
- updating a ref uses ``IfMatch=<etag>`` (put only if unchanged since we read it).

A ``412 PreconditionFailed`` therefore means we lost a race and ``update_ref``
returns False, exactly like the filesystem remote's lock-based CAS.

Credentials are never stored in the repo config; they come from the standard AWS
credential chain (env vars, shared config, IAM role) or an optional named
``profile``. Requires ``boto3`` (``pip install boto3``) and a backend that
supports conditional PutObject (AWS S3, MinIO, R2 all do).
"""
from __future__ import annotations

import gzip
import io
import json
from typing import Any

from ctxvc.errors import CtxvcError
from ctxvc.remote.base import Remote


def _build_client(endpoint_url: str | None, region: str | None, profile: str | None) -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - exercised only without boto3
        raise CtxvcError(
            "s3 remotes require boto3; install it with 'pip install boto3'"
        ) from exc
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    return session.client("s3", endpoint_url=endpoint_url, region_name=region)


def _http_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        meta = response.get("ResponseMetadata")
        if isinstance(meta, dict):
            code = meta.get("HTTPStatusCode")
            if isinstance(code, int):
                return code
        error = response.get("Error")
        if isinstance(error, dict):
            mapping = {"NoSuchKey": 404, "NotFound": 404, "404": 404,
                       "PreconditionFailed": 412, "412": 412}
            return mapping.get(str(error.get("Code")))
    return None


class S3Remote(Remote):
    def __init__(
        self,
        name: str,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
        profile: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.name = name
        self.bucket = bucket
        self.prefix = prefix if not prefix or prefix.endswith("/") else prefix + "/"
        self.client = client if client is not None else _build_client(endpoint_url, region, profile)

    def _key(self, suffix: str) -> str:
        return f"{self.prefix}{suffix}"

    def _get_bytes(self, key: str) -> bytes | None:
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001 - normalize backend 404
            if _http_status(exc) == 404:
                return None
            raise
        return resp["Body"].read()

    # --- objects -------------------------------------------------------------
    def has_object(self, content_hash: str) -> bool:
        key = self._key(f"objects/{content_hash}.txt.gz")
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:  # noqa: BLE001
            if _http_status(exc) == 404:
                return False
            raise

    def get_object(self, content_hash: str) -> str:
        data = self._get_bytes(self._key(f"objects/{content_hash}.txt.gz"))
        if data is None:
            raise CtxvcError(f"remote '{self.name}' missing object {content_hash}")
        return gzip.decompress(data).decode("utf-8")

    def put_object(self, content_hash: str, content: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(f"objects/{content_hash}.txt.gz"),
            Body=gzip.compress(content.encode("utf-8")),
        )

    # --- snapshots -----------------------------------------------------------
    def has_snapshot(self, snapshot_id: str) -> bool:
        key = self._key(f"snapshots/{snapshot_id}.json")
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as exc:  # noqa: BLE001
            if _http_status(exc) == 404:
                return False
            raise

    def get_snapshot(self, snapshot_id: str) -> dict[str, object]:
        data = self._get_bytes(self._key(f"snapshots/{snapshot_id}.json"))
        if data is None:
            raise CtxvcError(f"remote '{self.name}' missing snapshot {snapshot_id}")
        return json.loads(data.decode("utf-8-sig"))

    def put_snapshot(self, snapshot_id: str, payload: dict[str, object]) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(f"snapshots/{snapshot_id}.json"),
            Body=(json.dumps(payload, indent=2) + "\n").encode("utf-8"),
        )

    # --- refs (ETag-based compare-and-swap) ----------------------------------
    def _ref_key(self, name: str) -> str:
        return self._key(f"refs/{name}")

    def get_ref(self, name: str) -> str | None:
        data = self._get_bytes(self._ref_key(name))
        return data.decode("utf-8").strip() if data is not None else None

    def list_refs(self) -> dict[str, str | None]:
        refs_prefix = self._key("refs/")
        result: dict[str, str | None] = {}
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": refs_prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kwargs)
            for item in resp.get("Contents", []):
                key = item["Key"]
                name = key[len(refs_prefix):]
                if name:
                    result[name] = self.get_ref(name)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return result

    def update_ref(self, name: str, expected: str | None, new: str | None) -> bool:
        key = self._ref_key(name)
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=key)
            current: str | None = resp["Body"].read().decode("utf-8").strip()
            etag: str | None = resp.get("ETag")
        except Exception as exc:  # noqa: BLE001
            if _http_status(exc) != 404:
                raise
            current, etag = None, None

        if current != expected:
            return False

        if new is None:
            if current is not None:
                self.client.delete_object(Bucket=self.bucket, Key=key)
            return True

        body = new.encode("utf-8")
        try:
            if etag is None:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=body, IfNoneMatch="*")
            else:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=body, IfMatch=etag)
        except Exception as exc:  # noqa: BLE001
            if _http_status(exc) == 412:
                return False
            raise
        return True

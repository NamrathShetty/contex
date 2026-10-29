"""Qdrant-backed remote vector index for cross-agent semantic search.

The vector index is a DERIVED, rebuildable cache built from the canonical
content store — never a source of truth. Object identity stays content-hash
based; this layer only mirrors embeddings of already-stored content into a
shared Qdrant collection so multiple agents query one semantic surface instead
of each re-embedding history locally.

Embeddings are model-dependent, so every point records the embedder that
produced it. Syncing or searching a collection that was built with a different
embedder than the active one is refused (a sync can override with ``rebuild``),
to avoid silently comparing incompatible vector spaces.

Idempotency: a content hash always maps to the same point id (``uuid5`` over a
fixed namespace), so re-syncing updates points in place rather than duplicating.

Requires ``qdrant-client`` (``pip install qdrant-client``). Credentials are
never stored in the repo config; the API key is read from an environment
variable named by ``api_key_env``.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from ctxvc.errors import CtxvcError
from ctxvc.semantic.embeddings import EMBEDDER_LABEL, embed_text
from ctxvc.semantic.search import _embed_unique_objects, _load_snapshots, _preview
from ctxvc.store import read_object

INDEX_TYPES = ("qdrant",)

# Fixed namespace so a content hash always maps to the same Qdrant point id.
_POINT_NAMESPACE = uuid.UUID("a3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d")

_QDRANT_HINT = "vector indexes require qdrant-client; install it with 'pip install qdrant-client'"


def _point_id(content_hash: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, content_hash))


class QdrantIndex:
    """A handle to one Qdrant collection used as a ctxvc semantic index."""

    def __init__(
        self,
        name: str,
        collection: str,
        url: str | None = None,
        path: str | None = None,
        api_key: str | None = None,
        prefer_grpc: bool = False,
        client: Any | None = None,
    ) -> None:
        self.name = name
        self.collection = collection
        self._url = url
        self._path = path
        self._api_key = api_key
        self._prefer_grpc = prefer_grpc
        self._client = client

    def _models(self) -> Any:
        try:
            from qdrant_client import models
        except ImportError as exc:  # pragma: no cover - exercised only without qdrant-client
            raise CtxvcError(_QDRANT_HINT) from exc
        return models

    def client(self) -> Any:
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError as exc:  # pragma: no cover - exercised only without qdrant-client
                raise CtxvcError(_QDRANT_HINT) from exc
            if self._path:
                self._client = QdrantClient(path=self._path)
            elif self._url:
                self._client = QdrantClient(
                    url=self._url, api_key=self._api_key, prefer_grpc=self._prefer_grpc
                )
            else:
                raise CtxvcError(f"vector index '{self.name}' needs a url or path")
        return self._client

    def exists(self) -> bool:
        return bool(self.client().collection_exists(self.collection))

    def _create(self, dim: int) -> None:
        models = self._models()
        self.client().create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )

    def delete(self) -> None:
        client = self.client()
        if client.collection_exists(self.collection):
            client.delete_collection(self.collection)

    def collection_embedder(self) -> str | None:
        """Embedder label recorded on existing points, or None if empty/absent."""
        client = self.client()
        if not client.collection_exists(self.collection):
            return None
        points, _ = client.scroll(self.collection, limit=1, with_payload=True)
        if points:
            payload = getattr(points[0], "payload", None) or {}
            return payload.get("embedder")
        return None

    def count(self) -> int:
        client = self.client()
        if not client.collection_exists(self.collection):
            return 0
        return int(client.count(self.collection, exact=True).count)


def _records_by_hash(snapshots: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map each content hash to its path and the snapshots that reference it."""
    records: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        sid = snap.get("id")
        for entry in snap.get("files", []):
            content_hash = entry.get("content_hash")
            if not content_hash:
                continue
            record = records.setdefault(
                content_hash, {"path": entry.get("path"), "snapshots": []}
            )
            if sid not in record["snapshots"]:
                record["snapshots"].append(sid)
    return records


def sync_index(
    tool_root: Path,
    index: QdrantIndex,
    revision: str | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Embed unique content objects and upsert them into the Qdrant collection.

    Returns ``{index, collection, objects_indexed, embedder, dim}``.
    """
    snapshots = _load_snapshots(tool_root, revision)
    if not snapshots:
        raise CtxvcError("no snapshots to index")
    vectors = _embed_unique_objects(tool_root, snapshots)
    if not vectors:
        raise CtxvcError("no content objects to index")
    dim = len(next(iter(vectors.values())))

    models = index._models()
    client = index.client()

    if rebuild:
        index.delete()
    existing_embedder = index.collection_embedder()
    if existing_embedder is not None and existing_embedder != EMBEDDER_LABEL:
        raise CtxvcError(
            f"index '{index.name}' was built with embedder '{existing_embedder}' but the "
            f"active embedder is '{EMBEDDER_LABEL}'; re-run with --rebuild to replace it"
        )
    if not client.collection_exists(index.collection):
        index._create(dim)

    records = _records_by_hash(snapshots)
    points = []
    for content_hash, vector in vectors.items():
        record = records.get(content_hash, {"path": None, "snapshots": []})
        try:
            preview = _preview(read_object(tool_root, content_hash))
        except Exception:  # noqa: BLE001 - preview is best-effort metadata
            preview = ""
        points.append(
            models.PointStruct(
                id=_point_id(content_hash),
                vector=vector,
                payload={
                    "content_hash": content_hash,
                    "path": record["path"],
                    "snapshots": record["snapshots"],
                    "preview": preview,
                    "embedder": EMBEDDER_LABEL,
                },
            )
        )

    client.upsert(index.collection, points=points)
    return {
        "index": index.name,
        "collection": index.collection,
        "objects_indexed": len(vectors),
        "embedder": EMBEDDER_LABEL,
        "dim": dim,
    }


def search_index(index: QdrantIndex, query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """Rank indexed file versions by similarity to ``query``.

    Returns a list of ``{similarity, path, content_hash, snapshots, preview,
    embedder}`` sorted by descending similarity.
    """
    client = index.client()
    if not client.collection_exists(index.collection):
        raise CtxvcError(
            f"index '{index.name}' has no collection '{index.collection}'; "
            "run 'ctxvc vindex sync' first"
        )
    coll_embedder = index.collection_embedder()
    if coll_embedder is not None and coll_embedder != EMBEDDER_LABEL:
        raise CtxvcError(
            f"index '{index.name}' was built with embedder '{coll_embedder}' but the active "
            f"embedder is '{EMBEDDER_LABEL}'; results would be meaningless — rebuild the index"
        )

    query_vec = embed_text(query)
    response = client.query_points(
        index.collection, query=query_vec, limit=top_k, with_payload=True
    )

    hits: list[dict[str, Any]] = []
    for point in response.points:
        payload = getattr(point, "payload", None) or {}
        hits.append(
            {
                "similarity": float(point.score),
                "path": payload.get("path"),
                "content_hash": payload.get("content_hash"),
                "snapshots": payload.get("snapshots") or [],
                "preview": payload.get("preview") or "",
                "embedder": payload.get("embedder"),
            }
        )
    return hits


def open_index(repo_root: Path, tool_root: Path, name: str) -> QdrantIndex:
    """Instantiate a configured vector index by name from ``config.json``."""
    from ctxvc.config import read_config

    config = read_config(tool_root)
    indexes = config.get("vector_indexes", {})
    if not isinstance(indexes, dict) or name not in indexes:
        raise CtxvcError(f"unknown vector index: {name}")
    spec = indexes[name]
    if not isinstance(spec, dict):
        raise CtxvcError(f"invalid vector index config for '{name}'")
    if spec.get("type") != "qdrant":
        raise CtxvcError(f"unsupported vector index type: {spec.get('type')}")
    collection = spec.get("collection")
    if not collection:
        raise CtxvcError(f"vector index '{name}' is missing a collection")

    api_key = None
    api_key_env = spec.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(str(api_key_env))

    path = spec.get("path")
    if path:
        candidate = Path(str(path))
        path = str(candidate if candidate.is_absolute() else (repo_root / candidate))

    return QdrantIndex(
        name=name,
        collection=str(collection),
        url=spec.get("url"),  # type: ignore[arg-type]
        path=path,
        api_key=api_key,
        prefer_grpc=bool(spec.get("prefer_grpc", False)),
    )


__all__ = [
    "INDEX_TYPES",
    "QdrantIndex",
    "sync_index",
    "search_index",
    "open_index",
]

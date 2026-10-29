"""Semantic search over the snapshot/object store.

Ranks tracked file versions (or whole snapshots) by embedding similarity to a
natural-language query. Each unique content object is embedded once (keyed by
content hash) so repeated file versions across history are not re-embedded.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ctxvc.const import SNAPSHOTS_DIR
from ctxvc.semantic.embeddings import cosine_similarity, embed_text, embed_texts
from ctxvc.store import read_json, read_object

_PREVIEW_LIMIT = 120


def _preview(text: str) -> str:
    snippet = " ".join(text.split())
    return snippet[:_PREVIEW_LIMIT] + ("…" if len(snippet) > _PREVIEW_LIMIT else "")


def _load_snapshots(tool_root: Path, revision: str | None) -> list[dict[str, Any]]:
    snapshots_dir = tool_root / SNAPSHOTS_DIR
    if revision is not None:
        return [read_json(snapshots_dir / f"{revision}.json")]
    snapshots: list[dict[str, Any]] = []
    for path in sorted(snapshots_dir.glob("*.json")):
        try:
            snapshots.append(read_json(path))
        except Exception:
            continue
    return snapshots


def _embed_unique_objects(
    tool_root: Path, snapshots: list[dict[str, Any]]
) -> dict[str, list[float]]:
    """Embed each unique content hash once; returns hash -> vector."""
    texts: dict[str, str] = {}
    for snap in snapshots:
        for entry in snap.get("files", []):
            content_hash = entry.get("content_hash")
            if content_hash and content_hash not in texts:
                try:
                    texts[content_hash] = read_object(tool_root, str(content_hash))
                except Exception:
                    texts[content_hash] = ""
    hashes = list(texts)
    vectors = embed_texts([texts[h] for h in hashes])
    return dict(zip(hashes, vectors))


def search_files(
    tool_root: Path,
    query: str,
    revision: str | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Rank file versions (across history, or within one revision) by similarity.

    Returns a list of ``{similarity, path, content_hash, snapshots, preview}``
    sorted by descending similarity, deduplicated by content hash.
    """
    snapshots = _load_snapshots(tool_root, revision)
    if not snapshots:
        return []

    records: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        for entry in snap.get("files", []):
            content_hash = entry.get("content_hash")
            if not content_hash:
                continue
            record = records.get(content_hash)
            if record is None:
                records[content_hash] = {
                    "content_hash": content_hash,
                    "path": entry.get("path"),
                    "snapshots": [snap.get("id")],
                }
            else:
                record["snapshots"].append(snap.get("id"))

    if not records:
        return []

    vectors = _embed_unique_objects(tool_root, snapshots)
    query_vec = embed_text(query)

    results: list[dict[str, Any]] = []
    for content_hash, record in records.items():
        vector = vectors.get(content_hash)
        if vector is None:
            continue
        similarity = cosine_similarity(query_vec, vector)
        try:
            preview = _preview(read_object(tool_root, str(content_hash)))
        except Exception:
            preview = ""
        results.append(
            {
                "similarity": similarity,
                "path": record["path"],
                "content_hash": content_hash,
                "snapshots": record["snapshots"],
                "preview": preview,
            }
        )

    results.sort(key=lambda item: item["similarity"], reverse=True)
    return results[:top_k]


def search_snapshots(
    tool_root: Path,
    query: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Rank snapshots by the best semantic match among their files to the query.

    Returns a list of ``{similarity, id, message, best_path}`` sorted by
    descending similarity.
    """
    snapshots = _load_snapshots(tool_root, None)
    if not snapshots:
        return []

    vectors = _embed_unique_objects(tool_root, snapshots)
    query_vec = embed_text(query)

    results: list[dict[str, Any]] = []
    for snap in snapshots:
        best_similarity = 0.0
        best_path: str | None = None
        for entry in snap.get("files", []):
            vector = vectors.get(entry.get("content_hash"))
            if vector is None:
                continue
            similarity = cosine_similarity(query_vec, vector)
            if similarity > best_similarity:
                best_similarity = similarity
                best_path = entry.get("path")
        results.append(
            {
                "similarity": best_similarity,
                "id": snap.get("id"),
                "message": snap.get("message"),
                "best_path": best_path,
            }
        )

    results.sort(key=lambda item: item["similarity"], reverse=True)
    return results[:top_k]

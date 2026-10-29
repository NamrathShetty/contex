"""Graph persistence and snapshot integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx required: pip install networkx")

from ctxvc.errors import CtxvcError
from ctxvc.graph import (
    apply_graph_delta,
    compute_graph_delta,
    deserialize_graph,
    serialize_graph,
)
from ctxvc.store import load_snapshot, read_json, write_json


GRAPHS_DIR = "graphs"

# Store a full graph ("keyframe") at least this often along a snapshot chain.
# Between keyframes only deltas are stored. This bounds both storage growth and
# the cost of reconstructing a graph at any revision (at most KEYFRAME_INTERVAL-1
# deltas are replayed on top of a keyframe).
KEYFRAME_INTERVAL = 10


def get_graphs_dir(tool_root: Path) -> Path:
    """Return the graphs directory, creating if needed."""
    graphs_dir = tool_root / GRAPHS_DIR
    graphs_dir.mkdir(parents=True, exist_ok=True)
    return graphs_dir


def load_or_create_graph(tool_root: Path, graph_name: str = "default") -> nx.DiGraph:
    """Load a graph by name, or create empty one if not found."""
    graphs_dir = get_graphs_dir(tool_root)
    graph_path = graphs_dir / f"{graph_name}.json"
    if graph_path.exists():
        data = read_json(graph_path)
        return deserialize_graph(data)
    return nx.DiGraph()


def save_graph(tool_root: Path, graph: nx.DiGraph, graph_name: str = "default") -> None:
    """Save a graph to disk."""
    graphs_dir = get_graphs_dir(tool_root)
    graph_path = graphs_dir / f"{graph_name}.json"
    data = serialize_graph(graph)
    write_json(graph_path, data)


def _deltas_since_keyframe(
    tool_root: Path, revision: str, graph_name: str
) -> int | None:
    """Count delta snapshots since the last keyframe for graph_name.

    Walks the parent chain ending at `revision`. Returns the number of delta
    snapshots encountered before reaching a keyframe (a snapshot storing the
    full graph), or None if the graph does not appear anywhere in the chain.
    """
    count = 0
    cur: str | None = revision
    seen: set[str] = set()
    present = False

    while cur is not None and cur not in seen:
        seen.add(cur)
        snap = load_snapshot(tool_root, cur)
        keyframes = snap.get("graphs") or {}
        deltas = snap.get("graph_deltas") or {}
        if graph_name in keyframes:
            present = True
            break
        if graph_name in deltas:
            present = True
            count += 1
            cur = snap.get("parent")
            continue
        # Graph absent at this ancestor -> it did not exist further back.
        break

    return count if present else None


def reconstruct_graph(
    tool_root: Path, revision: str, graph_name: str = "default"
) -> nx.DiGraph:
    """Reconstruct a graph's full state at a revision from keyframe + deltas.

    Walks the parent chain from `revision` collecting deltas until a keyframe
    (full graph) is reached, then replays the deltas on top of it. Old snapshots
    that stored a full graph under "graphs" are treated as keyframes, so this is
    backward compatible with pre-delta snapshots.
    """
    deltas: list[dict[str, Any]] = []  # newest-first
    keyframe: dict[str, Any] | None = None
    cur: str | None = revision
    seen: set[str] = set()

    while cur is not None and cur not in seen:
        seen.add(cur)
        snap = load_snapshot(tool_root, cur)
        keyframes = snap.get("graphs") or {}
        graph_deltas = snap.get("graph_deltas") or {}
        if graph_name in keyframes:
            keyframe = keyframes[graph_name]
            break
        if graph_name in graph_deltas:
            deltas.append(graph_deltas[graph_name])
            cur = snap.get("parent")
            continue
        # Graph absent at this ancestor -> base is empty.
        break

    graph = deserialize_graph(keyframe) if keyframe is not None else nx.DiGraph()
    for delta in reversed(deltas):  # apply oldest-first
        apply_graph_delta(graph, delta)
    return graph


def get_graph_from_snapshot(
    tool_root: Path, revision: str, graph_name: str = "default"
) -> nx.DiGraph:
    """Load a graph from a specific snapshot, reconstructing from deltas."""
    snapshot = load_snapshot(tool_root, revision)
    keyframes = snapshot.get("graphs") or {}
    deltas = snapshot.get("graph_deltas") or {}
    if graph_name not in keyframes and graph_name not in deltas:
        raise CtxvcError(f"graph '{graph_name}' not found in snapshot {revision}")
    return reconstruct_graph(tool_root, revision, graph_name)


def embed_graphs_in_snapshot(
    snapshot: dict[str, Any], tool_root: Path, graph_names: list[str] | None = None
) -> None:
    """Embed current graphs into a snapshot using delta-based storage.

    For each graph, stores either a full keyframe (first occurrence, or every
    KEYFRAME_INTERVAL snapshots) under snapshot["graphs"], or a delta against the
    parent snapshot's reconstructed graph under snapshot["graph_deltas"].
    """
    graphs_dir = get_graphs_dir(tool_root)
    parent = snapshot.get("parent")

    keyframes: dict[str, Any] = {}
    deltas: dict[str, Any] = {}

    if graph_names:
        paths = [graphs_dir / f"{name}.json" for name in graph_names]
    else:
        paths = sorted(graphs_dir.glob("*.json"))

    for graph_path in paths:
        if not graph_path.exists():
            continue
        name = graph_path.stem
        current = deserialize_graph(read_json(graph_path))

        depth = _deltas_since_keyframe(tool_root, parent, name) if parent else None

        if depth is None:
            # First time this graph appears -> store a full keyframe.
            keyframes[name] = serialize_graph(current)
        elif depth + 1 >= KEYFRAME_INTERVAL:
            # Too many deltas since the last keyframe -> refresh with a keyframe.
            keyframes[name] = serialize_graph(current)
        else:
            parent_graph = reconstruct_graph(tool_root, parent, name)
            deltas[name] = compute_graph_delta(parent_graph, current)

    if keyframes:
        snapshot["graphs"] = keyframes
    if deltas:
        snapshot["graph_deltas"] = deltas


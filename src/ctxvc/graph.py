"""NetworkX-based knowledge graph with metadata and lineage tracking."""
from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx required: pip install networkx")

from ctxvc.errors import CtxvcError


def serialize_graph(graph: nx.DiGraph) -> dict[str, Any]:
    """Convert NetworkX graph to JSON-serializable dict."""
    return nx.node_link_data(graph)


def deserialize_graph(data: dict[str, Any]) -> nx.DiGraph:
    """Reconstruct NetworkX graph from dict."""
    return nx.node_link_graph(data, directed=True)


def add_node(
    graph: nx.DiGraph,
    node_id: str,
    label: str = "",
    origin: str | None = None,
    trust: float | None = None,
    created_by: str | None = None,
    lineage: list[str] | None = None,
    **attributes: Any,
) -> None:
    """Add or update a node with metadata and lineage tracking.
    
    Args:
        graph: NetworkX DiGraph instance
        node_id: Unique node identifier
        label: Human-readable label
        origin: Source/origin of this node (e.g., "user", "planner_agent", "document_123")
        trust: Trust/confidence score (0.0-1.0, where 1.0 is fully trusted)
        created_by: Which component/agent created this node
        lineage: List of node IDs this was derived from (data flow provenance)
        **attributes: Additional custom attributes
    """
    if not node_id.strip():
        raise CtxvcError("node_id cannot be empty")
    
    node_attrs = {"label": label, **attributes}
    
    # Add metadata fields if provided
    if origin is not None:
        node_attrs["origin"] = origin
    if trust is not None:
        if not 0.0 <= trust <= 1.0:
            raise CtxvcError("trust must be between 0.0 and 1.0")
        node_attrs["trust"] = trust
    if created_by is not None:
        node_attrs["created_by"] = created_by
    
    # Track lineage (which nodes this was derived from)
    if lineage:
        node_attrs["lineage"] = lineage
    else:
        node_attrs["lineage"] = []
    
    # Add timestamp if not present
    if "created_at" not in node_attrs:
        node_attrs["created_at"] = datetime.utcnow().isoformat()
    
    graph.add_node(node_id, **node_attrs)


def add_edge(
    graph: nx.DiGraph,
    source: str,
    target: str,
    relation: str = "related_to",
    flow_type: str | None = None,
    **attributes: Any,
) -> None:
    """Add or update an edge with flow information.
    
    Args:
        graph: NetworkX DiGraph instance
        source: Source node ID
        target: Target node ID
        relation: Relationship type
        flow_type: Type of data flow (e.g., "direct", "inferred", "aggregated")
        **attributes: Additional edge attributes
    """
    if not source.strip() or not target.strip():
        raise CtxvcError("source and target cannot be empty")
    if source not in graph:
        raise CtxvcError(f"source node not found: {source}")
    if target not in graph:
        raise CtxvcError(f"target node not found: {target}")
    
    edge_attrs = {"relation": relation, **attributes}
    if flow_type:
        edge_attrs["flow_type"] = flow_type
    
    graph.add_edge(source, target, **edge_attrs)


def remove_node(graph: nx.DiGraph, node_id: str) -> None:
    """Remove a node and all its edges."""
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    graph.remove_node(node_id)


def remove_edge(graph: nx.DiGraph, source: str, target: str) -> None:
    """Remove an edge between nodes."""
    if not graph.has_edge(source, target):
        raise CtxvcError(f"edge not found: {source} -> {target}")
    graph.remove_edge(source, target)


def list_nodes(graph: nx.DiGraph) -> list[tuple[str, dict[str, Any]]]:
    """Return list of (node_id, attributes) tuples."""
    return [(node, dict(data)) for node, data in graph.nodes(data=True)]


def list_edges(graph: nx.DiGraph) -> list[tuple[str, str, dict[str, Any]]]:
    """Return list of (source, target, attributes) tuples."""
    return [
        (source, target, dict(data))
        for source, target, data in graph.edges(data=True)
    ]


def get_node_metadata(graph: nx.DiGraph, node_id: str) -> dict[str, Any]:
    """Retrieve metadata for a node."""
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    return dict(graph.nodes[node_id])


def node_to_text(graph: nx.DiGraph, node_id: str) -> str:
    """Render a node's semantic content as text for embedding/semantic diff.

    Concatenates the node id and its human-meaningful string attributes (label,
    origin, created_by, output, and any other string-valued attributes), while
    skipping bookkeeping fields that do not carry semantic meaning.
    """
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    attrs = graph.nodes[node_id]
    skip = {"created_at", "lineage", "step_index", "execution_count", "trust"}
    parts = [str(node_id)]
    for key in ("label", "origin", "created_by", "output"):
        value = attrs.get(key)
        if value:
            parts.append(f"{key}: {value}")
    for key, value in attrs.items():
        if key in skip or key in ("label", "origin", "created_by", "output"):
            continue
        if isinstance(value, str) and value:
            parts.append(f"{key}: {value}")
    return "\n".join(parts)


def get_lineage(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Get lineage (parent nodes) for a node."""
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    return graph.nodes[node_id].get("lineage", [])


def add_to_lineage(graph: nx.DiGraph, node_id: str, parent_nodes: list[str]) -> None:
    """Add parent nodes to a node's lineage."""
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    current_lineage = graph.nodes[node_id].get("lineage", [])
    # Add new parents, avoiding duplicates
    updated_lineage = list(set(current_lineage + parent_nodes))
    graph.nodes[node_id]["lineage"] = updated_lineage


def compute_lineage_path(
    graph: nx.DiGraph, node_id: str, max_depth: int = 10
) -> dict[str, Any]:
    """Compute full lineage path (all ancestors) for a node.
    
    Returns:
        Dict with "path" (list of node IDs) and "depth" (number of levels)
    """
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    
    visited = set()
    path = []
    
    def traverse(nid: str, depth: int) -> None:
        if depth > max_depth or nid in visited:
            return
        visited.add(nid)
        path.append(nid)
        lineage = graph.nodes[nid].get("lineage", [])
        for parent in lineage:
            traverse(parent, depth + 1)
    
    traverse(node_id, 0)
    return {"path": path, "depth": len(path) - 1}


def filter_by_trust(
    graph: nx.DiGraph, min_trust: float = 0.0, max_trust: float = 1.0
) -> list[str]:
    """Filter nodes by trust level."""
    return [
        node
        for node, attrs in graph.nodes(data=True)
        if min_trust <= attrs.get("trust", 1.0) <= max_trust
    ]


def filter_by_origin(graph: nx.DiGraph, origin: str) -> list[str]:
    """Find all nodes from a specific origin."""
    return [
        node for node, attrs in graph.nodes(data=True)
        if attrs.get("origin") == origin
    ]


def get_neighbors(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Get outgoing neighbors of a node."""
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    return list(graph.successors(node_id))


def get_predecessors(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Get incoming predecessors of a node."""
    if node_id not in graph:
        raise CtxvcError(f"node not found: {node_id}")
    return list(graph.predecessors(node_id))


def graph_stats(graph: nx.DiGraph) -> dict[str, Any]:
    """Return graph statistics including metadata."""
    trust_values = [
        attrs.get("trust", 1.0)
        for _, attrs in graph.nodes(data=True)
    ]
    origins = set(
        attrs.get("origin")
        for _, attrs in graph.nodes(data=True)
        if attrs.get("origin")
    )
    
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "density": float(nx.density(graph)),
        "avg_trust": sum(trust_values) / len(trust_values) if trust_values else 1.0,
        "origins": sorted(origins),
        "nodes_with_lineage": len([
            n for n, attrs in graph.nodes(data=True)
            if attrs.get("lineage")
        ]),
    }


def compute_graph_diff(
    old_graph: nx.DiGraph, new_graph: nx.DiGraph
) -> dict[str, Any]:
    """Compute diff between two graphs including metadata changes."""
    old_nodes = set(old_graph.nodes())
    new_nodes = set(new_graph.nodes())
    old_edges = set(old_graph.edges())
    new_edges = set(new_graph.edges())

    return {
        "nodes_added": sorted(new_nodes - old_nodes),
        "nodes_removed": sorted(old_nodes - new_nodes),
        "nodes_modified": [
            n
            for n in sorted(old_nodes & new_nodes)
            if old_graph.nodes[n] != new_graph.nodes[n]
        ],
        "edges_added": sorted(new_edges - old_edges),
        "edges_removed": sorted(old_edges - new_edges),
        "edges_modified": [
            (s, t)
            for s, t in sorted(old_edges & new_edges)
            if old_graph.edges[s, t] != new_graph.edges[s, t]
        ],
    }


def compute_graph_delta(
    old_graph: nx.DiGraph, new_graph: nx.DiGraph
) -> dict[str, Any]:
    """Compute a reversible delta to transform old_graph into new_graph.

    Unlike compute_graph_diff (which is a human-readable summary), this delta
    carries the full node/edge attributes needed to reconstruct new_graph by
    applying the delta on top of old_graph. Used for delta-based snapshot storage.
    """
    old_nodes = set(old_graph.nodes())
    new_nodes = set(new_graph.nodes())
    old_edges = set(old_graph.edges())
    new_edges = set(new_graph.edges())

    return {
        "nodes_added": [
            {"id": n, "attrs": dict(new_graph.nodes[n])}
            for n in sorted(new_nodes - old_nodes)
        ],
        "nodes_modified": [
            {"id": n, "attrs": dict(new_graph.nodes[n])}
            for n in sorted(old_nodes & new_nodes)
            if old_graph.nodes[n] != new_graph.nodes[n]
        ],
        "nodes_removed": sorted(old_nodes - new_nodes),
        "edges_added": [
            {"source": s, "target": t, "attrs": dict(new_graph.edges[s, t])}
            for s, t in sorted(new_edges - old_edges)
        ],
        "edges_modified": [
            {"source": s, "target": t, "attrs": dict(new_graph.edges[s, t])}
            for s, t in sorted(old_edges & new_edges)
            if old_graph.edges[s, t] != new_graph.edges[s, t]
        ],
        "edges_removed": [list(e) for e in sorted(old_edges - new_edges)],
    }


def apply_graph_delta(graph: nx.DiGraph, delta: dict[str, Any]) -> nx.DiGraph:
    """Apply a delta (from compute_graph_delta) to a graph in place.

    Order matters: removals are applied before additions/modifications so that
    an add and a remove of the same key in one delta resolve to the add.
    Returns the same graph instance for convenience.
    """
    # Removals first (removing a node also drops its incident edges)
    for node_id in delta.get("nodes_removed", []):
        if node_id in graph:
            graph.remove_node(node_id)
    for edge in delta.get("edges_removed", []):
        source, target = edge[0], edge[1]
        if graph.has_edge(source, target):
            graph.remove_edge(source, target)

    # Additions and modifications (full attribute replacement)
    for item in delta.get("nodes_added", []) + delta.get("nodes_modified", []):
        graph.add_node(item["id"], **item["attrs"])
    for item in delta.get("edges_added", []) + delta.get("edges_modified", []):
        graph.add_edge(item["source"], item["target"], **item["attrs"])

    return graph


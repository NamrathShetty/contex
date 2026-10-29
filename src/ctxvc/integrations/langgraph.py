"""LangGraph -> ctxvc "flight recorder" integration.

ctxvc is a *descriptive* version-control layer; LangGraph is an *executable*
runtime. This module turns a LangGraph execution (or its static topology) into a
descriptive knowledge graph and records it as a delta-stored ctxvc snapshot.

Design principle: ctxvc never imports ``langgraph``. We only consume the data
structures LangGraph already produces (its ``.stream(...)`` events or the object
returned by ``.get_graph()``), so this integration has zero hard dependency and
works equally well from a saved JSON trace.

Normalized trace schema (the stable contract this module ingests)::

    {
      "version": 1,
      "name": "optional run name",
      "steps": [
        {
          "id": "planner",            # node name that executed
          "label": "Planner",         # optional display label (defaults to id)
          "inputs": ["__start__"],    # upstream node ids that fed this step
          "output": <any>,            # optional state update (summarized)
          "tokens": 123,              # optional token usage for this step
          "trust": 0.9                # optional confidence score
        },
        ...
      ]
    }

Each executed step becomes a descriptive node (``origin="langgraph"``); each
``inputs`` reference becomes both a lineage entry and a transition edge.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx required: pip install networkx")

from ctxvc.const import SNAPSHOTS_DIR
from ctxvc.errors import CtxvcError
from ctxvc.graph import add_edge, add_node
from ctxvc.graph_store import embed_graphs_in_snapshot, load_or_create_graph, save_graph
from ctxvc.refs import read_refs, record_snapshot, set_head
from ctxvc.store import build_snapshot_id, utc_now, write_json


NORMALIZED_TRACE_VERSION = 1
_OUTPUT_SUMMARY_LIMIT = 500


def _summarize_output(update: Any) -> Any:
    """Return a compact, JSON-safe summary of a step's output/state update."""
    if update is None:
        return None
    try:
        if isinstance(update, dict):
            summary = ", ".join(sorted(update.keys()))
            text = f"{{{summary}}}"
        else:
            text = repr(update)
    except Exception:
        text = "<unrepresentable>"
    if len(text) > _OUTPUT_SUMMARY_LIMIT:
        text = text[:_OUTPUT_SUMMARY_LIMIT] + "…"
    return text


def _extract_tokens(update: Any) -> int | None:
    """Best-effort extraction of token usage from a LangGraph state update."""
    if not isinstance(update, dict):
        return None
    # Common direct keys.
    for key in ("tokens", "token_count", "total_tokens"):
        value = update.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    # LangChain-style usage metadata.
    usage = update.get("usage_metadata") or update.get("usage")
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if isinstance(total, (int, float)):
            return int(total)
    # Messages carrying usage_metadata.
    messages = update.get("messages")
    if isinstance(messages, list):
        total = 0
        found = False
        for msg in messages:
            meta = getattr(msg, "usage_metadata", None)
            if isinstance(meta, dict) and isinstance(meta.get("total_tokens"), (int, float)):
                total += int(meta["total_tokens"])
                found = True
        if found:
            return total
    return None


def from_langgraph_stream(
    events: Iterable[Any], run_name: str | None = None
) -> dict[str, Any]:
    """Convert LangGraph ``.stream(..., stream_mode="updates")`` events to a trace.

    In ``updates`` mode LangGraph yields one dict per super-step mapping each node
    that ran to its state update: ``{"node_name": {<update>}}`` (multiple nodes per
    dict when they ran in parallel). Steps from the previous super-step are treated
    as the data-flow inputs of the next, which becomes lineage + transition edges.
    """
    steps: list[dict[str, Any]] = []
    prev_ids: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        current_ids: list[str] = []
        for node_name, update in event.items():
            steps.append(
                {
                    "id": node_name,
                    "label": node_name,
                    "inputs": list(prev_ids),
                    "output": _summarize_output(update),
                    "tokens": _extract_tokens(update),
                }
            )
            current_ids.append(node_name)
        if current_ids:
            prev_ids = current_ids

    return {"version": NORMALIZED_TRACE_VERSION, "name": run_name, "steps": steps}


def from_compiled_graph(app: Any, run_name: str | None = None) -> dict[str, Any]:
    """Build a trace from a compiled LangGraph's *static* topology.

    Uses duck typing on the object returned by ``app.get_graph()`` (which exposes
    ``nodes`` and ``edges``) so no LangGraph import is required. Captures the
    workflow definition even without executing it.
    """
    get_graph = getattr(app, "get_graph", None)
    if not callable(get_graph):
        raise CtxvcError("object does not expose get_graph(); not a compiled LangGraph")

    drawable = get_graph()
    raw_nodes = getattr(drawable, "nodes", {})
    raw_edges = getattr(drawable, "edges", [])

    node_ids = list(raw_nodes.keys()) if isinstance(raw_nodes, dict) else list(raw_nodes)

    inputs_by_target: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in raw_edges:
        source = getattr(edge, "source", None)
        target = getattr(edge, "target", None)
        if source is None and isinstance(edge, (tuple, list)) and len(edge) >= 2:
            source, target = edge[0], edge[1]
        if source is not None and target is not None:
            inputs_by_target.setdefault(target, []).append(source)
            inputs_by_target.setdefault(source, inputs_by_target.get(source, []))

    steps = [
        {"id": nid, "label": nid, "inputs": inputs_by_target.get(nid, [])}
        for nid in node_ids
    ]
    return {"version": NORMALIZED_TRACE_VERSION, "name": run_name, "steps": steps}


def trace_to_graph(trace: dict[str, Any], collapse: bool = True) -> nx.DiGraph:
    """Convert a normalized trace into a descriptive NetworkX graph.

    Args:
        trace: Normalized trace (see module docstring).
        collapse: When True (default), repeated executions of the same node are
            merged into a single node with an ``execution_count`` and summed
            ``tokens`` — yielding a clean workflow topology. When False, each
            execution becomes a distinct node id (``name#n``).
    """
    if not isinstance(trace, dict) or "steps" not in trace:
        raise CtxvcError("invalid trace: expected an object with a 'steps' list")

    graph = nx.DiGraph()
    steps = trace.get("steps") or []
    run_name = trace.get("name") or "langgraph_run"

    # Resolve a stable node id per step (handles loops when not collapsing).
    name_counts: dict[str, int] = {}
    step_ids: list[str] = []
    for step in steps:
        name = step.get("id")
        if not name:
            raise CtxvcError("invalid trace step: missing 'id'")
        if collapse:
            step_ids.append(name)
        else:
            count = name_counts.get(name, 0)
            step_ids.append(name if count == 0 else f"{name}#{count}")
            name_counts[name] = count + 1

    for idx, step in enumerate(steps):
        node_id = step_ids[idx]
        # Only keep lineage/edges to inputs that are real nodes in this graph.
        raw_inputs = step.get("inputs") or []
        inputs = [inp for inp in raw_inputs if inp in graph and inp != node_id]

        extra: dict[str, Any] = {
            "node_name": step.get("id"),
            "step_index": idx,
        }
        if step.get("output") is not None:
            extra["output"] = step["output"]

        tokens = step.get("tokens")
        existing = graph.nodes[node_id] if node_id in graph else None

        if existing is not None:
            # Merge a repeated execution into the collapsed node.
            extra["step_index"] = existing.get("step_index", idx)
            extra["execution_count"] = existing.get("execution_count", 1) + 1
            merged_lineage = list(dict.fromkeys(existing.get("lineage", []) + inputs))
            if tokens is not None:
                tokens = int(existing.get("tokens", 0) or 0) + int(tokens)
            else:
                tokens = existing.get("tokens")
            label = existing.get("label") or step.get("label", node_id)
        else:
            extra["execution_count"] = 1
            merged_lineage = inputs
            label = step.get("label", node_id)

        if tokens is not None:
            extra["tokens"] = int(tokens)

        add_node(
            graph,
            node_id,
            label=label,
            origin="langgraph",
            trust=step.get("trust"),
            created_by=run_name,
            lineage=merged_lineage,
            **extra,
        )

        for inp in inputs:
            add_edge(graph, inp, node_id, relation="transition", flow_type="execution")

    return graph


def _merge_into(base: nx.DiGraph, incoming: nx.DiGraph) -> nx.DiGraph:
    """Union incoming graph into base (incoming attributes win)."""
    for node_id, attrs in incoming.nodes(data=True):
        base.add_node(node_id, **attrs)
    for source, target, attrs in incoming.edges(data=True):
        base.add_edge(source, target, **attrs)
    return base


def ingest_trace(
    tool_root: Any,
    trace: dict[str, Any],
    graph_name: str = "default",
    message: str | None = None,
    merge: bool = False,
    collapse: bool = True,
) -> str:
    """Convert a trace to a descriptive graph and record it as a ctxvc snapshot.

    Returns the new snapshot id. The graph is saved to ``.ctxvc/graphs/`` and
    embedded into the snapshot using delta-based storage.
    """
    new_graph = trace_to_graph(trace, collapse=collapse)
    if merge:
        base = load_or_create_graph(tool_root, graph_name)
        graph = _merge_into(base, new_graph)
    else:
        graph = new_graph

    save_graph(tool_root, graph, graph_name)

    refs = read_refs(tool_root)
    parent = refs.get("HEAD")
    snapshot_id = build_snapshot_id()
    steps = trace.get("steps") or []
    total_tokens = sum(int(s.get("tokens") or 0) for s in steps)

    snapshot: dict[str, Any] = {
        "id": snapshot_id,
        "parent": parent,
        "created_at": utc_now(),
        "message": message or f"Ingested LangGraph run: {len(steps)} step(s)",
        "agents": [],
        "files": [],
        "total_tokens": total_tokens,
        "source": "langgraph",
        "run_name": trace.get("name"),
    }

    embed_graphs_in_snapshot(snapshot, tool_root)
    write_json(tool_root / SNAPSHOTS_DIR / f"{snapshot_id}.json", snapshot)
    record_snapshot(tool_root, snapshot)
    set_head(tool_root, snapshot_id)
    return snapshot_id

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import networkx as nx
except ImportError:
    raise ImportError("networkx required: pip install networkx")

from ctxvc.config import (
    agent_prefix_path,
    get_agent_path,
    read_config,
    resolve_within_repo,
    validate_agent_name,
)
from ctxvc.const import CONFIG_PATH, OBJECTS_DIR, SNAPSHOTS_DIR, TOOL_DIR
from ctxvc.errors import CtxvcError
from ctxvc.refs import (
    agent_branch_name,
    agent_from_branch,
    create_branch,
    create_tag,
    delete_tag,
    init_refs,
    list_branches,
    list_handoffs,
    list_tags,
    read_refs,
    record_handoff,
    record_snapshot,
    resolve_revision,
    set_branch,
    set_head,
    switch_branch,
    validate_ref_name,
)
from ctxvc.snapshot import (
    as_repo_relative,
    build_working_index,
    collect_files,
    compare_indices,
    filter_index_by_prefixes,
    print_diff,
    resolve_snapshot_targets,
    resolve_status_targets,
)
from ctxvc.store import (
    build_snapshot_id,
    find_repo_root,
    load_snapshot,
    load_snapshot_index,
    read_object,
    resolve_entry_text,
    utc_now,
    write_json,
    write_object,
)
from ctxvc.tokens import TOKENIZER_LABEL, count_tokens
from ctxvc.graph import (
    add_node,
    add_edge,
    compute_graph_diff,
    compute_lineage_path,
    deserialize_graph,
    filter_by_origin,
    filter_by_trust,
    get_lineage,
    get_node_metadata,
    graph_stats,
    list_edges,
    list_nodes,
    node_to_text,
    remove_edge,
    remove_node,
    serialize_graph,
)
from ctxvc.graph_store import embed_graphs_in_snapshot, get_graph_from_snapshot, load_or_create_graph, save_graph
from ctxvc.integrations.langgraph import ingest_trace
from ctxvc.remote import REMOTE_TYPES, open_remote
from ctxvc.remote import pull as remote_pull
from ctxvc.remote import push as remote_push
from ctxvc.semantic import (
    EMBEDDER_LABEL,
    compare_texts,
    detect_renames,
    search_files,
    search_snapshots,
)
from ctxvc.semantic.vindex import (
    INDEX_TYPES,
    open_index,
    search_index,
    sync_index,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except CtxvcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctxvc",
        description="Track versioned snapshots of LLM context files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize a .ctxvc repository.")
    init_parser.set_defaults(handler=handle_init)

    snapshot_parser = subparsers.add_parser("snapshot", help="Create a new snapshot.")
    snapshot_parser.add_argument("paths", nargs="*", help="Files or directories to capture.")
    snapshot_parser.add_argument("--agent", help="Registered agent name to snapshot.")
    snapshot_parser.add_argument("-m", "--message", required=True, help="Snapshot message.")
    snapshot_parser.set_defaults(handler=handle_snapshot)

    snapshot_all_parser = subparsers.add_parser(
        "snapshot-all",
        help="Create a single snapshot for all registered agents.",
    )
    snapshot_all_parser.add_argument("-m", "--message", required=True, help="Snapshot message.")
    snapshot_all_parser.set_defaults(handler=handle_snapshot_all)

    history_parser = subparsers.add_parser("history", help="Show snapshot history.")
    history_parser.add_argument("--limit", type=int, default=20, help="Maximum entries to show.")
    history_parser.add_argument("--tokens", action="store_true", help="Include total token count per snapshot.")
    history_parser.set_defaults(handler=handle_history)

    tokens_parser = subparsers.add_parser("tokens", help="Show token budget for a snapshot or the working tree.")
    tokens_parser.add_argument("revision", nargs="?", help="Snapshot revision, branch, or tag. Defaults to HEAD.")
    tokens_parser.add_argument("--agent", help="Limit to a registered agent.")
    tokens_parser.set_defaults(handler=handle_tokens)

    status_parser = subparsers.add_parser("status", help="Compare working files to HEAD.")
    status_parser.add_argument("paths", nargs="*", help="Optional files or directories to inspect.")
    status_parser.add_argument("--agent", help="Registered agent name to inspect.")
    status_parser.set_defaults(handler=handle_status)

    diff_parser = subparsers.add_parser("diff", help="Diff two snapshots or a snapshot against working tree.")
    diff_parser.add_argument("rev_a", nargs="?", help="Base revision. Defaults to HEAD.")
    diff_parser.add_argument("rev_b", nargs="?", help="Target revision. If omitted, compares against working tree.")
    diff_parser.add_argument("--path", dest="path_filter", help="Limit diff to a single tracked path.")
    diff_parser.add_argument("--agent", help="Limit diff to files belonging to a registered agent.")
    diff_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Report embedding-based semantic similarity and detect renames instead of a line diff.",
    )
    diff_parser.set_defaults(handler=handle_diff)

    show_parser = subparsers.add_parser("show", help="Show snapshot metadata.")
    show_parser.add_argument("revision", nargs="?", help="Revision id. Defaults to HEAD.")
    show_parser.set_defaults(handler=handle_show)

    checkout_parser = subparsers.add_parser("checkout", help="Write a snapshot to a destination directory.")
    checkout_parser.add_argument("revision", help="Revision id to materialize.")
    checkout_parser.add_argument("--dest", required=True, help="Destination directory.")
    checkout_parser.set_defaults(handler=handle_checkout)

    branch_parser = subparsers.add_parser("branch", help="Manage lightweight snapshot branches.")
    branch_subparsers = branch_parser.add_subparsers(dest="branch_command", required=True)

    branch_create_parser = branch_subparsers.add_parser("create", help="Create a branch at HEAD or revision.")
    branch_create_parser.add_argument("name", help="Branch name.")
    branch_create_parser.add_argument("revision", nargs="?", help="Optional start revision. Defaults to HEAD.")
    branch_create_parser.set_defaults(handler=handle_branch_create)

    branch_list_parser = branch_subparsers.add_parser("list", help="List branches and active branch.")
    branch_list_parser.set_defaults(handler=handle_branch_list)

    branch_switch_parser = branch_subparsers.add_parser("switch", help="Switch active branch and HEAD.")
    branch_switch_parser.add_argument("name", help="Branch name.")
    branch_switch_parser.set_defaults(handler=handle_branch_switch)

    handoff_parser = subparsers.add_parser(
        "handoff",
        help="Branch-per-agent context handoff helpers.",
    )
    handoff_subparsers = handoff_parser.add_subparsers(dest="handoff_command", required=True)

    handoff_start_parser = handoff_subparsers.add_parser(
        "start", help="Create (if needed) and switch to an agent's branch to begin working as it."
    )
    handoff_start_parser.add_argument("agent", help="Agent name to work as.")
    handoff_start_parser.add_argument(
        "revision", nargs="?", help="Start revision when creating the branch. Defaults to HEAD."
    )
    handoff_start_parser.set_defaults(handler=handle_handoff_start)

    handoff_to_parser = handoff_subparsers.add_parser(
        "to", help="Hand off a snapshot (HEAD by default) to another agent's branch."
    )
    handoff_to_parser.add_argument("agent", help="Receiving agent name.")
    handoff_to_parser.add_argument(
        "--rev",
        dest="revision",
        help="Snapshot id, branch, or tag to hand off. Defaults to HEAD.",
    )
    handoff_to_parser.add_argument("-m", "--message", help="Optional handoff note.")
    handoff_to_parser.add_argument(
        "--stay",
        action="store_true",
        help="Record the handoff without switching to the receiving agent's branch.",
    )
    handoff_to_parser.set_defaults(handler=handle_handoff_to)

    handoff_log_parser = handoff_subparsers.add_parser("log", help="Show recorded handoffs.")
    handoff_log_parser.add_argument("--limit", type=int, default=20, help="Maximum entries to show.")
    handoff_log_parser.set_defaults(handler=handle_handoff_log)

    tag_parser = subparsers.add_parser("tag", help="Manage immutable snapshot tags.")
    tag_subparsers = tag_parser.add_subparsers(dest="tag_command", required=True)

    tag_add_parser = tag_subparsers.add_parser("add", help="Create a tag at HEAD or revision.")
    tag_add_parser.add_argument("name", help="Tag name.")
    tag_add_parser.add_argument("revision", nargs="?", help="Optional target revision. Defaults to HEAD.")
    tag_add_parser.set_defaults(handler=handle_tag_add)

    tag_list_parser = tag_subparsers.add_parser("list", help="List tags.")
    tag_list_parser.set_defaults(handler=handle_tag_list)

    tag_remove_parser = tag_subparsers.add_parser("remove", help="Remove a tag.")
    tag_remove_parser.add_argument("name", help="Tag name.")
    tag_remove_parser.set_defaults(handler=handle_tag_remove)

    agent_parser = subparsers.add_parser("agent", help="Manage registered agent context folders.")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)

    agent_add_parser = agent_subparsers.add_parser("add", help="Register an agent name to a context path.")
    agent_add_parser.add_argument("name", help="Unique agent name.")
    agent_add_parser.add_argument("path", help="Path to agent context file or directory.")
    agent_add_parser.set_defaults(handler=handle_agent_add)

    agent_list_parser = agent_subparsers.add_parser("list", help="List registered agents.")
    agent_list_parser.set_defaults(handler=handle_agent_list)

    agent_remove_parser = agent_subparsers.add_parser("remove", help="Remove an agent registration.")
    agent_remove_parser.add_argument("name", help="Registered agent name.")
    agent_remove_parser.set_defaults(handler=handle_agent_remove)

    graph_parser = subparsers.add_parser("graph", help="Manage knowledge graph nodes and edges.")
    graph_subparsers = graph_parser.add_subparsers(dest="graph_command", required=True)

    graph_add_node_parser = graph_subparsers.add_parser("add-node", help="Add or update a node in the graph.")
    graph_add_node_parser.add_argument("node_id", help="Unique node identifier.")
    graph_add_node_parser.add_argument("label", help="Node label/name.")
    graph_add_node_parser.add_argument("--origin", help="Origin/source of this node (e.g., 'user', 'agent_planner', 'document_123')")
    graph_add_node_parser.add_argument("--trust", type=float, help="Trust/confidence score (0.0-1.0)")
    graph_add_node_parser.add_argument("--created-by", help="Component/agent that created this node")
    graph_add_node_parser.add_argument("--lineage", help="Comma-separated list of parent node IDs (data provenance)")
    graph_add_node_parser.add_argument("--props", help="JSON properties dict (e.g. '{\"type\": \"person\"}'")
    graph_add_node_parser.set_defaults(handler=handle_graph_add_node)

    graph_remove_node_parser = graph_subparsers.add_parser("remove-node", help="Remove a node from the graph.")
    graph_remove_node_parser.add_argument("node_id", help="Node identifier to remove.")
    graph_remove_node_parser.set_defaults(handler=handle_graph_remove_node)

    graph_add_edge_parser = graph_subparsers.add_parser("add-edge", help="Add or update an edge in the graph.")
    graph_add_edge_parser.add_argument("edge_id", help="Unique edge identifier.")
    graph_add_edge_parser.add_argument("source", help="Source node ID.")
    graph_add_edge_parser.add_argument("target", help="Target node ID.")
    graph_add_edge_parser.add_argument("label", help="Edge label/relationship type.")
    graph_add_edge_parser.add_argument("--props", help="JSON properties dict")
    graph_add_edge_parser.set_defaults(handler=handle_graph_add_edge)

    graph_remove_edge_parser = graph_subparsers.add_parser("remove-edge", help="Remove an edge from the graph.")
    graph_remove_edge_parser.add_argument("edge_id", help="Edge identifier to remove.")
    graph_remove_edge_parser.set_defaults(handler=handle_graph_remove_edge)

    graph_show_parser = graph_subparsers.add_parser("show", help="Display the current knowledge graph.")
    graph_show_parser.set_defaults(handler=handle_graph_show)

    graph_info_parser = graph_subparsers.add_parser("info", help="Show detailed metadata and lineage for a node.")
    graph_info_parser.add_argument("node_id", help="Node ID to inspect.")
    graph_info_parser.set_defaults(handler=handle_graph_info)

    graph_lineage_parser = graph_subparsers.add_parser("lineage", help="Show complete lineage path for a node.")
    graph_lineage_parser.add_argument("node_id", help="Node ID to trace.")
    graph_lineage_parser.add_argument("--max-depth", type=int, default=10, help="Maximum lineage depth to trace")
    graph_lineage_parser.set_defaults(handler=handle_graph_lineage)

    graph_filter_parser = graph_subparsers.add_parser("filter", help="Filter nodes by metadata (trust, origin).")
    graph_filter_parser.add_argument("--trust-min", type=float, help="Minimum trust level (0.0-1.0)")
    graph_filter_parser.add_argument("--trust-max", type=float, help="Maximum trust level (0.0-1.0)")
    graph_filter_parser.add_argument("--origin", help="Filter by origin/source")
    graph_filter_parser.set_defaults(handler=handle_graph_filter)

    graph_stats_parser = graph_subparsers.add_parser("stats", help="Show graph statistics including metadata.")
    graph_stats_parser.set_defaults(handler=handle_graph_stats)

    graph_diff_parser = graph_subparsers.add_parser("diff", help="Show graph changes between two revisions.")
    graph_diff_parser.add_argument("rev_a", nargs="?", help="Base revision. Defaults to HEAD.")
    graph_diff_parser.add_argument("rev_b", nargs="?", help="Target revision. Defaults to working tree.")
    graph_diff_parser.add_argument(
        "--semantic",
        action="store_true",
        help="Score node changes by embedding similarity and detect renamed nodes.",
    )
    graph_diff_parser.set_defaults(handler=handle_graph_diff)

    ingest_parser = subparsers.add_parser(
        "ingest", help="Ingest an external execution into a descriptive snapshot."
    )
    ingest_subparsers = ingest_parser.add_subparsers(dest="source", required=True)

    ingest_lg_parser = ingest_subparsers.add_parser(
        "langgraph", help="Ingest a LangGraph run trace (JSON) as a delta-stored snapshot."
    )
    ingest_lg_parser.add_argument("trace", help="Path to a normalized LangGraph trace JSON file.")
    ingest_lg_parser.add_argument("--name", help="Graph name to write to.", default="default")
    ingest_lg_parser.add_argument("--run-name", help="Optional run name (overrides trace 'name').")
    ingest_lg_parser.add_argument("-m", "--message", help="Snapshot message.")
    ingest_lg_parser.add_argument(
        "--merge", action="store_true", help="Merge into the existing graph instead of replacing it."
    )
    ingest_lg_parser.add_argument(
        "--no-collapse",
        dest="collapse",
        action="store_false",
        help="Keep each node execution as a distinct node (preserves loop iterations).",
    )
    ingest_lg_parser.set_defaults(handler=handle_ingest_langgraph, collapse=True)

    search_parser = subparsers.add_parser(
        "search", help="Semantically rank files or snapshots by a natural-language query."
    )
    search_parser.add_argument("query", help="Natural-language query.")
    search_parser.add_argument("--rev", help="Limit file search to a single revision.")
    search_parser.add_argument(
        "--snapshots",
        action="store_true",
        help="Rank whole snapshots by their best matching file instead of individual files.",
    )
    search_parser.add_argument("--top", type=int, default=10, help="Number of results to show (default 10).")
    search_parser.set_defaults(handler=handle_search)

    remote_parser = subparsers.add_parser("remote", help="Manage push/pull remotes.")
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command", required=True)

    remote_add_parser = remote_subparsers.add_parser("add", help="Register a remote.")
    remote_add_parser.add_argument("name", help="Remote name (e.g. 'origin').")
    remote_add_parser.add_argument(
        "path", nargs="?", help="Directory path (filesystem remotes)."
    )
    remote_add_parser.add_argument(
        "--type", default="filesystem", choices=REMOTE_TYPES, help="Remote backend type."
    )
    remote_add_parser.add_argument("--bucket", help="Bucket name (s3 remotes).")
    remote_add_parser.add_argument("--prefix", help="Key prefix within the bucket (s3 remotes).")
    remote_add_parser.add_argument(
        "--endpoint-url", dest="endpoint_url", help="Custom endpoint (MinIO/R2, s3 remotes)."
    )
    remote_add_parser.add_argument("--region", help="Region (s3 remotes).")
    remote_add_parser.add_argument(
        "--profile", help="AWS named profile for credentials (s3 remotes)."
    )
    remote_add_parser.set_defaults(handler=handle_remote_add)

    remote_list_parser = remote_subparsers.add_parser("list", help="List registered remotes.")
    remote_list_parser.set_defaults(handler=handle_remote_list)

    remote_remove_parser = remote_subparsers.add_parser("remove", help="Remove a remote.")
    remote_remove_parser.add_argument("name", help="Remote name.")
    remote_remove_parser.set_defaults(handler=handle_remote_remove)

    push_parser = subparsers.add_parser("push", help="Upload a branch's snapshots to a remote.")
    push_parser.add_argument("remote", help="Remote name.")
    push_parser.add_argument("branch", nargs="?", help="Branch to push. Defaults to the current branch.")
    push_parser.add_argument("--force", action="store_true", help="Allow non-fast-forward updates.")
    push_parser.set_defaults(handler=handle_push)

    pull_parser = subparsers.add_parser("pull", help="Download a branch's snapshots from a remote.")
    pull_parser.add_argument("remote", help="Remote name.")
    pull_parser.add_argument("branch", nargs="?", help="Branch to pull. Defaults to the current branch.")
    pull_parser.add_argument("--force", action="store_true", help="Allow non-fast-forward updates.")
    pull_parser.set_defaults(handler=handle_pull)

    vindex_parser = subparsers.add_parser(
        "vindex", help="Manage remote vector indexes for shared semantic search."
    )
    vindex_subparsers = vindex_parser.add_subparsers(dest="vindex_command", required=True)

    vindex_add_parser = vindex_subparsers.add_parser("add", help="Register a vector index.")
    vindex_add_parser.add_argument("name", help="Index name (e.g. 'team').")
    vindex_add_parser.add_argument("collection", help="Qdrant collection name.")
    vindex_add_parser.add_argument(
        "--type", default="qdrant", choices=INDEX_TYPES, help="Vector index backend type."
    )
    vindex_add_parser.add_argument("--url", help="Qdrant server URL (e.g. http://localhost:6333).")
    vindex_add_parser.add_argument(
        "--path", help="Local on-disk Qdrant path (alternative to --url)."
    )
    vindex_add_parser.add_argument(
        "--api-key-env",
        dest="api_key_env",
        help="Environment variable holding the Qdrant API key.",
    )
    vindex_add_parser.add_argument(
        "--prefer-grpc", dest="prefer_grpc", action="store_true", help="Use the gRPC interface."
    )
    vindex_add_parser.set_defaults(handler=handle_vindex_add)

    vindex_list_parser = vindex_subparsers.add_parser("list", help="List registered vector indexes.")
    vindex_list_parser.set_defaults(handler=handle_vindex_list)

    vindex_remove_parser = vindex_subparsers.add_parser("remove", help="Remove a vector index.")
    vindex_remove_parser.add_argument("name", help="Index name.")
    vindex_remove_parser.set_defaults(handler=handle_vindex_remove)

    vindex_sync_parser = vindex_subparsers.add_parser(
        "sync", help="Embed content objects and upsert them into the index."
    )
    vindex_sync_parser.add_argument("name", help="Index name.")
    vindex_sync_parser.add_argument("--rev", help="Index only a single revision.")
    vindex_sync_parser.add_argument(
        "--rebuild", action="store_true", help="Drop and rebuild the collection first."
    )
    vindex_sync_parser.set_defaults(handler=handle_vindex_sync)

    vindex_search_parser = vindex_subparsers.add_parser(
        "search", help="Semantically search a remote vector index."
    )
    vindex_search_parser.add_argument("name", help="Index name.")
    vindex_search_parser.add_argument("query", help="Natural-language query.")
    vindex_search_parser.add_argument(
        "--top", type=int, default=10, help="Number of results to show (default 10)."
    )
    vindex_search_parser.set_defaults(handler=handle_vindex_search)

    return parser


def handle_init(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd(), allow_missing=True)
    tool_root = repo_root / TOOL_DIR
    if tool_root.exists():
        raise CtxvcError(f"repository already initialized at {tool_root}")

    (tool_root / SNAPSHOTS_DIR).mkdir(parents=True)
    (tool_root / OBJECTS_DIR).mkdir(parents=True)
    write_json(
        tool_root / CONFIG_PATH,
        {
            "version": 1,
            "created_at": utc_now(),
            "agents": {},
        },
    )
    init_refs(tool_root)
    print(f"Initialized context repository in {tool_root}")
    return 0


def handle_snapshot(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    target_paths, included_agents = resolve_snapshot_targets(repo_root, tool_root, args.paths, args.agent)
    tracked_files = collect_files(repo_root, target_paths)
    if not tracked_files:
        raise CtxvcError("no files found to snapshot")

    refs = read_refs(tool_root)
    parent = refs.get("HEAD")
    snapshot_id = build_snapshot_id()
    snapshot = {
        "id": snapshot_id,
        "parent": parent,
        "created_at": utc_now(),
        "message": args.message,
        "agents": sorted(included_agents),
        "files": [],
    }

    for file_path in tracked_files:
        rel_path = file_path.relative_to(repo_root).as_posix()
        content = file_path.read_text(encoding="utf-8")
        content_hash = write_object(tool_root, content)
        snapshot["files"].append(
            {
                "path": rel_path,
                "content_hash": content_hash,
                "size": len(content.encode("utf-8")),
                "token_count": count_tokens(content),
            }
        )

    snapshot["files"].sort(key=lambda item: item["path"])
    snapshot["total_tokens"] = sum(int(f["token_count"]) for f in snapshot["files"])
    embed_graphs_in_snapshot(snapshot, tool_root)
    write_json(tool_root / SNAPSHOTS_DIR / f"{snapshot_id}.json", snapshot)
    record_snapshot(tool_root, snapshot)
    set_head(tool_root, snapshot_id)
    print(f"Created snapshot {snapshot_id} with {len(snapshot['files'])} files  ({snapshot['total_tokens']} tokens)")
    return 0


def handle_snapshot_all(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    agents = config.get("agents", {})
    if not agents:
        raise CtxvcError("no agents registered; use 'ctxvc agent add <name> <path>' first")

    target_paths = [Path(path) for path in agents.values()]
    tracked_files = collect_files(repo_root, target_paths)
    if not tracked_files:
        raise CtxvcError("registered agent paths did not resolve to files")

    refs = read_refs(tool_root)
    parent = refs.get("HEAD")
    snapshot_id = build_snapshot_id()
    snapshot = {
        "id": snapshot_id,
        "parent": parent,
        "created_at": utc_now(),
        "message": args.message,
        "agents": sorted(agents.keys()),
        "files": [],
    }

    for file_path in tracked_files:
        rel_path = file_path.relative_to(repo_root).as_posix()
        content = file_path.read_text(encoding="utf-8")
        content_hash = write_object(tool_root, content)
        snapshot["files"].append(
            {
                "path": rel_path,
                "content_hash": content_hash,
                "size": len(content.encode("utf-8")),
                "token_count": count_tokens(content),
            }
        )

    snapshot["files"].sort(key=lambda item: item["path"])
    snapshot["total_tokens"] = sum(int(f["token_count"]) for f in snapshot["files"])
    embed_graphs_in_snapshot(snapshot, tool_root)
    write_json(tool_root / SNAPSHOTS_DIR / f"{snapshot_id}.json", snapshot)
    record_snapshot(tool_root, snapshot)
    set_head(tool_root, snapshot_id)
    print(f"Created all-agent snapshot {snapshot_id} with {len(snapshot['files'])} files  ({snapshot['total_tokens']} tokens)")
    return 0


def handle_history(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    revision = refs.get("HEAD")
    shown = 0
    while revision and shown < args.limit:
        snapshot = load_snapshot(tool_root, revision)
        token_info = f"  {snapshot['total_tokens']} tok" if args.tokens and "total_tokens" in snapshot else ""
        print(f"{snapshot['id']}  {snapshot['created_at']}  {snapshot['message']}{token_info}")
        revision = snapshot.get("parent")
        shown += 1
    if shown == 0:
        print("No snapshots yet")
    return 0


def handle_tokens(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    revision = resolve_revision(tool_root, refs, args.revision or refs.get("HEAD"))
    if not revision:
        raise CtxvcError("no HEAD snapshot available")

    snapshot = load_snapshot(tool_root, revision)
    files = list(snapshot["files"])

    if args.agent:
        prefix = agent_prefix_path(repo_root, tool_root, args.agent)
        normalized = prefix.rstrip("/") + "/"
        files = [f for f in files if f["path"] == prefix or str(f["path"]).startswith(normalized)]

    total = sum(int(f.get("token_count", 0)) for f in files)
    print(f"Snapshot : {revision}")
    print(f"Tokenizer: {TOKENIZER_LABEL}")
    print(f"Files    : {len(files)}")
    print(f"Total    : {total:,} tokens")
    print()
    col_w = max((len(str(f['path'])) for f in files), default=4)
    print(f"{'PATH':<{col_w}}  TOKENS")
    print("-" * (col_w + 10))
    for f in sorted(files, key=lambda x: x["path"]):
        tc = int(f.get("token_count", 0))
        print(f"{str(f['path']):<{col_w}}  {tc:,}")
    return 0


def handle_status(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    head = refs.get("HEAD")
    inspect_paths = resolve_status_targets(repo_root, tool_root, args.paths, args.agent)
    current_files = collect_files(repo_root, inspect_paths)
    working = build_working_index(repo_root, current_files)
    if not head:
        for path in sorted(working):
            print(f"A  {path}")
        return 0

    snapshot = load_snapshot(tool_root, head)
    snap_index = {item['path']: item for item in snapshot['files']}
    if args.agent or args.paths:
        prefixes = [as_repo_relative(repo_root, path) for path in inspect_paths]
        snap_index = filter_index_by_prefixes(snap_index, prefixes)
    changes = compare_indices(snap_index, working)
    if not changes:
        print("Working tree matches HEAD")
        return 0
    for marker, path in changes:
        print(f"{marker}  {path}")
    return 0


def handle_diff(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    rev_a = resolve_revision(tool_root, refs, args.rev_a or refs.get("HEAD"))
    if not rev_a:
        raise CtxvcError("no HEAD snapshot available")

    base_index = load_snapshot_index(tool_root, rev_a)
    if args.rev_b:
        target_index = load_snapshot_index(tool_root, resolve_revision(tool_root, refs, args.rev_b))
    else:
        inspect_paths = resolve_status_targets(repo_root, tool_root, [], args.agent)
        current_files = collect_files(repo_root, inspect_paths)
        target_index = build_working_index(repo_root, current_files)

    effective_filter = args.path_filter
    if args.agent:
        agent_prefix = agent_prefix_path(repo_root, tool_root, args.agent)
        if effective_filter and not effective_filter.startswith(agent_prefix):
            raise CtxvcError("--path must be inside the selected --agent path")
    else:
        agent_prefix = None

    if getattr(args, "semantic", False):
        print_semantic_file_diff(tool_root, base_index, target_index, effective_filter, agent_prefix)
        return 0

    print_diff(tool_root, base_index, target_index, effective_filter, agent_prefix)
    return 0


def print_semantic_file_diff(
    tool_root: Path,
    base_index: dict[str, dict[str, object]],
    target_index: dict[str, dict[str, object]],
    path_filter: str | None,
    prefix_filter: str | None,
) -> None:
    """Print an embedding-based semantic diff: per-file similarity + rename detection."""
    paths = sorted(set(base_index) | set(target_index))
    if prefix_filter:
        normalized = prefix_filter.rstrip("/") + "/"
        paths = [p for p in paths if p == prefix_filter or p.startswith(normalized)]
    if path_filter:
        paths = [p for p in paths if p == path_filter]
    if not paths:
        print("No matching files")
        return

    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    modified: list[tuple[str, dict[str, object]]] = []
    for path in paths:
        left = base_index.get(path)
        right = target_index.get(path)
        if left and right:
            if left["content_hash"] == right["content_hash"]:
                continue
            old_text = read_object(tool_root, str(left["content_hash"]))
            new_text = resolve_entry_text(tool_root, right)
            modified.append((path, compare_texts(old_text, new_text)))
        elif left:
            removed[path] = read_object(tool_root, str(left["content_hash"]))
        elif right:
            added[path] = resolve_entry_text(tool_root, right)

    rename_result = detect_renames(removed, added)

    if not modified and not rename_result["renames"] and not rename_result["removed"] and not rename_result["added"]:
        print("No differences found")
        return

    for path, result in modified:
        print(f"M {path}  similarity={result['similarity']:.2f} ({result['change']})")
    for rename in rename_result["renames"]:
        print(f"R {rename['from']} -> {rename['to']}  similarity={rename['similarity']:.2f}")
    for path in rename_result["removed"]:
        print(f"D {path}")
    for path in rename_result["added"]:
        print(f"A {path}")


def handle_show(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    revision = resolve_revision(tool_root, refs, args.revision or refs.get("HEAD"))
    if not revision:
        raise CtxvcError("no HEAD snapshot available")
    snapshot = load_snapshot(tool_root, revision)
    print(json.dumps(snapshot, indent=2))
    return 0


def handle_checkout(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    revision = resolve_revision(tool_root, refs, args.revision)
    snapshot = load_snapshot(tool_root, revision)
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    for entry in snapshot["files"]:
        target = dest / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(read_object(tool_root, entry["content_hash"]), encoding="utf-8")
    print(f"Materialized {revision} to {dest}")
    return 0


def handle_branch_create(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    validate_ref_name(args.name, "branch")
    target = resolve_revision(tool_root, refs, args.revision or refs.get("HEAD"))
    create_branch(tool_root, args.name, target)
    print(f"Created branch '{args.name}' at {target}")
    return 0


def handle_branch_list(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    branches, current = list_branches(tool_root)
    for name in sorted(branches):
        marker = "*" if name == current else " "
        print(f"{marker} {name}\t{branches[name]}")
    return 0


def handle_branch_switch(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    switch_branch(tool_root, args.name)
    print(f"Switched to branch '{args.name}'")
    return 0


def handle_handoff_start(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    validate_agent_name(args.agent)
    branch = agent_branch_name(args.agent)
    validate_ref_name(branch, "branch")
    refs = read_refs(tool_root)
    branches = refs.get("branches", {})
    if not isinstance(branches, dict) or branch not in branches:
        target = resolve_revision(tool_root, refs, args.revision or refs.get("HEAD"))
        create_branch(tool_root, branch, target)
        print(f"Created agent branch '{branch}' at {target}")
    switch_branch(tool_root, branch)
    print(f"Working as agent '{args.agent}' on branch '{branch}'")
    return 0


def handle_handoff_to(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    validate_agent_name(args.agent)
    refs = read_refs(tool_root)
    if args.revision:
        revision = resolve_revision(tool_root, refs, args.revision)
    else:
        revision = refs.get("HEAD")
    if revision is None:
        raise CtxvcError(
            "nothing to hand off: HEAD has no snapshot yet "
            "(create one with 'ctxvc snapshot-all -m ...') or pass --rev <id>"
        )
    current = refs.get("current_branch")
    source_agent = agent_from_branch(current if isinstance(current, str) else None)
    if source_agent is None and isinstance(current, str):
        source_agent = current

    target_branch = agent_branch_name(args.agent)
    validate_ref_name(target_branch, "branch")
    set_branch(tool_root, target_branch, revision)
    record_handoff(tool_root, source_agent, args.agent, str(revision), args.message)

    if args.stay:
        print(
            f"Handed off {revision} from '{source_agent or '-'}' to "
            f"'{args.agent}' ({target_branch}); stayed on '{current}'"
        )
    else:
        switch_branch(tool_root, target_branch)
        print(
            f"Handed off {revision} from '{source_agent or '-'}' to "
            f"'{args.agent}'; switched to '{target_branch}'"
        )
    return 0


def handle_handoff_log(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    entries = list_handoffs(tool_root, args.limit)
    if not entries:
        print("No handoffs recorded")
        return 0
    for entry in entries:
        source = entry.get("source_agent") or "-"
        note = f"  {entry['message']}" if entry.get("message") else ""
        print(
            f"{entry['created_at']}  {source} -> {entry['target_agent']}"
            f"  @ {entry['revision']}{note}"
        )
    return 0


def handle_remote_add(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    remotes = config.setdefault("remotes", {})
    if not isinstance(remotes, dict):
        raise CtxvcError("invalid config: remotes must be an object")
    if args.name in remotes:
        raise CtxvcError(f"remote already exists: {args.name}")

    if args.type == "filesystem":
        if not args.path:
            raise CtxvcError("filesystem remotes require a path")
        spec: dict[str, object] = {"type": "filesystem", "path": args.path}
        summary = args.path
    elif args.type == "s3":
        if not args.bucket:
            raise CtxvcError("s3 remotes require --bucket")
        spec = {"type": "s3", "bucket": args.bucket}
        for key, value in (
            ("prefix", args.prefix),
            ("endpoint_url", args.endpoint_url),
            ("region", args.region),
            ("profile", args.profile),
        ):
            if value:
                spec[key] = value
        summary = f"s3://{args.bucket}/{args.prefix or ''}"
    else:  # pragma: no cover - guarded by argparse choices
        raise CtxvcError(f"unsupported remote type: {args.type}")

    remotes[args.name] = spec
    write_json(tool_root / CONFIG_PATH, config)
    print(f"Registered remote '{args.name}' ({args.type}) -> {summary}")
    return 0


def handle_remote_list(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    remotes = config.get("remotes", {})
    if not isinstance(remotes, dict) or not remotes:
        print("No remotes")
        return 0
    for name in sorted(remotes):
        spec = remotes[name]
        if isinstance(spec, dict):
            if spec.get("type") == "s3":
                location = f"s3://{spec.get('bucket')}/{spec.get('prefix', '')}"
                if spec.get("endpoint_url"):
                    location += f" @ {spec.get('endpoint_url')}"
            else:
                location = str(spec.get("path"))
            print(f"{name}\t{spec.get('type')}\t{location}")
        else:
            print(f"{name}\t{spec}")
    return 0


def handle_remote_remove(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    remotes = config.get("remotes", {})
    if not isinstance(remotes, dict) or args.name not in remotes:
        raise CtxvcError(f"unknown remote: {args.name}")
    del remotes[args.name]
    write_json(tool_root / CONFIG_PATH, config)
    print(f"Removed remote '{args.name}'")
    return 0


def handle_push(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    branch = args.branch or read_refs(tool_root).get("current_branch")
    if not branch:
        raise CtxvcError("no branch to push")
    remote = open_remote(repo_root, tool_root, args.remote)
    result = remote_push(tool_root, remote, str(branch), force=args.force)
    print(
        f"Pushed '{result['branch']}' -> {result['target']} to '{args.remote}' "
        f"({result['snapshots_uploaded']} snapshot(s), {result['objects_uploaded']} object(s))"
    )
    return 0


def handle_pull(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    branch = args.branch or read_refs(tool_root).get("current_branch")
    if not branch:
        raise CtxvcError("no branch to pull")
    remote = open_remote(repo_root, tool_root, args.remote)
    result = remote_pull(tool_root, remote, str(branch), force=args.force)
    print(
        f"Pulled '{result['branch']}' -> {result['target']} from '{args.remote}' "
        f"({result['snapshots_downloaded']} snapshot(s), {result['objects_downloaded']} object(s))"
    )
    return 0


def handle_vindex_add(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    indexes = config.setdefault("vector_indexes", {})
    if not isinstance(indexes, dict):
        raise CtxvcError("invalid config: vector_indexes must be an object")
    if args.name in indexes:
        raise CtxvcError(f"vector index already exists: {args.name}")

    if args.type == "qdrant":
        if not args.url and not args.path:
            raise CtxvcError("qdrant indexes require --url or --path")
        spec: dict[str, object] = {"type": "qdrant", "collection": args.collection}
        for key, value in (
            ("url", args.url),
            ("path", args.path),
            ("api_key_env", args.api_key_env),
        ):
            if value:
                spec[key] = value
        if args.prefer_grpc:
            spec["prefer_grpc"] = True
        location = args.url or args.path
    else:  # pragma: no cover - guarded by argparse choices
        raise CtxvcError(f"unsupported vector index type: {args.type}")

    indexes[args.name] = spec
    write_json(tool_root / CONFIG_PATH, config)
    print(
        f"Registered vector index '{args.name}' ({args.type}) -> {location} [{args.collection}]"
    )
    return 0


def handle_vindex_list(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    indexes = config.get("vector_indexes", {})
    if not isinstance(indexes, dict) or not indexes:
        print("No vector indexes")
        return 0
    for name in sorted(indexes):
        spec = indexes[name]
        if isinstance(spec, dict):
            location = spec.get("url") or spec.get("path")
            print(f"{name}\t{spec.get('type')}\t{location}\t[{spec.get('collection')}]")
        else:
            print(f"{name}\t{spec}")
    return 0


def handle_vindex_remove(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    indexes = config.get("vector_indexes", {})
    if not isinstance(indexes, dict) or args.name not in indexes:
        raise CtxvcError(f"unknown vector index: {args.name}")
    del indexes[args.name]
    write_json(tool_root / CONFIG_PATH, config)
    print(f"Removed vector index '{args.name}'")
    return 0


def handle_vindex_sync(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    revision = resolve_revision(tool_root, refs, args.rev) if args.rev else None
    index = open_index(repo_root, tool_root, args.name)
    result = sync_index(tool_root, index, revision=revision, rebuild=args.rebuild)
    print(
        f"Synced vector index '{result['index']}' ({result['collection']}): "
        f"{result['objects_indexed']} object(s)  [{result['embedder']}]"
    )
    return 0


def handle_vindex_search(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    index = open_index(repo_root, tool_root, args.name)
    results = search_index(index, args.query, top_k=args.top)
    if not results:
        print("No matches")
        return 0
    print(f"Top {len(results)} matches from '{args.name}' for: {args.query}  [{EMBEDDER_LABEL}]")
    for result in results:
        snapshots = result["snapshots"]
        if not snapshots:
            where = "?"
        elif len(snapshots) == 1:
            where = snapshots[0]
        else:
            where = f"{snapshots[0]} (+{len(snapshots) - 1} more)"
        print(f"  {result['similarity']:.2f}  {result['path']}  @{where}")
        if result["preview"]:
            print(f"        {result['preview']}")
    return 0


def handle_tag_add(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)
    validate_ref_name(args.name, "tag")
    target = resolve_revision(tool_root, refs, args.revision or refs.get("HEAD"))
    create_tag(tool_root, args.name, target)
    print(f"Created tag '{args.name}' at {target}")
    return 0


def handle_tag_list(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    tags = list_tags(tool_root)
    if not tags:
        print("No tags")
        return 0
    for name in sorted(tags):
        print(f"{name}\t{tags[name]}")
    return 0


def handle_tag_remove(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    delete_tag(tool_root, args.name)
    print(f"Removed tag '{args.name}'")
    return 0


def handle_agent_add(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)

    validate_agent_name(args.name)
    candidate = resolve_within_repo(repo_root, Path(args.path))
    if not candidate.exists():
        raise CtxvcError(f"agent path does not exist: {args.path}")

    rel_path = candidate.relative_to(repo_root).as_posix()
    agents = config.setdefault("agents", {})
    if not isinstance(agents, dict):
        raise CtxvcError("invalid config: agents must be an object")
    agents[args.name] = rel_path
    write_json(tool_root / CONFIG_PATH, config)
    print(f"Registered agent '{args.name}' -> {rel_path}")
    return 0


def handle_agent_list(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    agents = config.get("agents", {})
    if not agents:
        print("No registered agents")
        return 0

    for name in sorted(agents):
        print(f"{name}\t{agents[name]}")
    return 0


def handle_agent_remove(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    config = read_config(tool_root)
    agents = config.get("agents", {})
    if args.name not in agents:
        raise CtxvcError(f"unknown agent: {args.name}")
    del agents[args.name]
    write_json(tool_root / CONFIG_PATH, config)
    print(f"Removed agent '{args.name}'")
    return 0


def handle_graph_add_node(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    props = {}
    if args.props:
        try:
            props = json.loads(args.props)
        except json.JSONDecodeError:
            raise CtxvcError("--props must be valid JSON")

    # Parse lineage (comma-separated node IDs)
    lineage = []
    if args.lineage:
        lineage = [n.strip() for n in args.lineage.split(",") if n.strip()]

    add_node(
        graph,
        args.node_id,
        label=args.label,
        origin=args.origin,
        trust=args.trust,
        created_by=args.created_by,
        lineage=lineage,
        **props,
    )
    save_graph(tool_root, graph)
    
    # Build status message
    meta_parts = []
    if args.origin:
        meta_parts.append(f"origin={args.origin}")
    if args.trust is not None:
        meta_parts.append(f"trust={args.trust}")
    if args.created_by:
        meta_parts.append(f"created_by={args.created_by}")
    if lineage:
        meta_parts.append(f"lineage=[{','.join(lineage)}]")
    
    meta_str = f" [{', '.join(meta_parts)}]" if meta_parts else ""
    print(f"Added/updated node '{args.node_id}' ({args.label}){meta_str}")
    return 0


def handle_graph_remove_node(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)
    remove_node(graph, args.node_id)
    save_graph(tool_root, graph)
    print(f"Removed node '{args.node_id}'")
    return 0


def handle_graph_add_edge(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    props = {}
    if args.props:
        try:
            props = json.loads(args.props)
        except json.JSONDecodeError:
            raise CtxvcError("--props must be valid JSON")

    add_edge(graph, args.source, args.target, relation=args.label, **props)
    save_graph(tool_root, graph)
    print(f"Added/updated edge: {args.source} -[{args.label}]-> {args.target}")
    return 0


def handle_graph_remove_edge(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    edge_parts = args.edge_id.split("->")
    if len(edge_parts) != 2:
        raise CtxvcError("edge_id format: 'source->target'")
    source, target = edge_parts[0].strip(), edge_parts[1].strip()
    remove_edge(graph, source, target)
    save_graph(tool_root, graph)
    print(f"Removed edge: {source} -> {target}")
    return 0


def handle_graph_show(_: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    nodes = list_nodes(graph)
    edges = list_edges(graph)

    print(f"Nodes ({len(nodes)}):")
    for nid, data in nodes:
        label = data.get("label", nid)
        print(f"  {nid}: {label}")

    print(f"\nEdges ({len(edges)}):")
    for source, target, data in edges:
        relation = data.get("relation", "related_to")
        print(f"  {source} -[{relation}]-> {target}")

    return 0


def handle_graph_diff(args: argparse.Namespace) -> int:
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)

    rev_a = resolve_revision(tool_root, refs, args.rev_a or refs.get("HEAD"))
    if not rev_a:
        raise CtxvcError("no HEAD snapshot available")

    if args.rev_b:
        rev_b = resolve_revision(tool_root, refs, args.rev_b)
        graph_a = get_graph_from_snapshot(tool_root, rev_a)
        graph_b = get_graph_from_snapshot(tool_root, rev_b)
    else:
        graph_a = get_graph_from_snapshot(tool_root, rev_a)
        graph_b = load_or_create_graph(tool_root)

    diff = compute_graph_diff(graph_a, graph_b)

    if getattr(args, "semantic", False):
        removed_map = {n: node_to_text(graph_a, n) for n in diff["nodes_removed"]}
        added_map = {n: node_to_text(graph_b, n) for n in diff["nodes_added"]}
        rename_result = detect_renames(removed_map, added_map)

        has_changes = (
            diff["nodes_modified"]
            or rename_result["renames"]
            or rename_result["removed"]
            or rename_result["added"]
            or diff["edges_added"]
            or diff["edges_removed"]
            or diff["edges_modified"]
        )
        if not has_changes:
            print("No graph changes")
            return 0

        print(f"Semantic graph diff: {rev_a} -> {args.rev_b or 'working'}")
        for node_id in diff["nodes_modified"]:
            result = compare_texts(node_to_text(graph_a, node_id), node_to_text(graph_b, node_id))
            print(f"  ~ {node_id}  similarity={result['similarity']:.2f} ({result['change']})")
        for rename in rename_result["renames"]:
            print(f"  R {rename['from']} -> {rename['to']}  similarity={rename['similarity']:.2f}")
        for node_id in rename_result["removed"]:
            print(f"  - {node_id}")
        for node_id in rename_result["added"]:
            print(f"  + {node_id}")
        if diff["edges_added"]:
            print(f"  Edges added: {', '.join(str(e) for e in diff['edges_added'])}")
        if diff["edges_removed"]:
            print(f"  Edges removed: {', '.join(str(e) for e in diff['edges_removed'])}")
        if diff["edges_modified"]:
            print(f"  Edges modified: {', '.join(str(e) for e in diff['edges_modified'])}")
        return 0

    if any(diff.values()):
        print(f"Graph diff: {rev_a} -> {args.rev_b or 'working'}")
        if diff["nodes_added"]:
            print(f"  Nodes added: {', '.join(diff['nodes_added'])}")
        if diff["nodes_removed"]:
            print(f"  Nodes removed: {', '.join(diff['nodes_removed'])}")
        if diff["nodes_modified"]:
            print(f"  Nodes modified: {', '.join(diff['nodes_modified'])}")
        if diff["edges_added"]:
            print(f"  Edges added: {', '.join(str(e) for e in diff['edges_added'])}")
        if diff["edges_removed"]:
            print(f"  Edges removed: {', '.join(str(e) for e in diff['edges_removed'])}")
        if diff["edges_modified"]:
            print(f"  Edges modified: {', '.join(str(e) for e in diff['edges_modified'])}")
    else:
        print("No graph changes")

    return 0


def handle_graph_info(args: argparse.Namespace) -> int:
    """Show detailed metadata and lineage for a node."""
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    try:
        metadata = get_node_metadata(graph, args.node_id)
    except Exception as e:
        raise CtxvcError(str(e))

    print(f"Node: {args.node_id}")
    print(f"  Label: {metadata.get('label', 'N/A')}")
    
    if "origin" in metadata:
        print(f"  Origin: {metadata['origin']}")
    if "trust" in metadata:
        print(f"  Trust: {metadata['trust']:.2f}")
    if "created_by" in metadata:
        print(f"  Created by: {metadata['created_by']}")
    if "created_at" in metadata:
        print(f"  Created at: {metadata['created_at']}")
    
    lineage = metadata.get("lineage", [])
    if lineage:
        print(f"  Lineage (parents): {', '.join(lineage)}")
    else:
        print(f"  Lineage: (no parents)")
    
    # Show custom properties
    custom_props = {k: v for k, v in metadata.items() 
                   if k not in {"label", "origin", "trust", "created_by", "created_at", "lineage"}}
    if custom_props:
        print(f"  Custom properties: {custom_props}")
    
    return 0


def handle_graph_lineage(args: argparse.Namespace) -> int:
    """Show complete lineage path for a node."""
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    try:
        lineage = compute_lineage_path(graph, args.node_id, args.max_depth)
    except Exception as e:
        raise CtxvcError(str(e))

    path = lineage["path"]
    depth = lineage["depth"]

    if depth == 0:
        print(f"Node '{args.node_id}' has no lineage (origin node)")
    else:
        print(f"Lineage path for '{args.node_id}' (depth: {depth}):")
        for i, node_id in enumerate(path):
            indent = "  " * i
            metadata = get_node_metadata(graph, node_id)
            label = metadata.get("label", "")
            trust = metadata.get("trust", 1.0)
            origin = metadata.get("origin", "")
            origin_str = f" [origin={origin}]" if origin else ""
            trust_str = f" [trust={trust:.2f}]" if trust < 1.0 else ""
            print(f"{indent}└─ {node_id}: {label}{origin_str}{trust_str}")

    return 0


def handle_graph_filter(args: argparse.Namespace) -> int:
    """Filter nodes by metadata."""
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    results = []
    
    # Filter by trust
    if args.trust_min is not None or args.trust_max is not None:
        min_trust = args.trust_min if args.trust_min is not None else 0.0
        max_trust = args.trust_max if args.trust_max is not None else 1.0
        results = filter_by_trust(graph, min_trust, max_trust)
        print(f"Nodes with trust {min_trust}-{max_trust}:")
    
    # Filter by origin
    elif args.origin:
        results = filter_by_origin(graph, args.origin)
        print(f"Nodes with origin '{args.origin}':")
    
    else:
        raise CtxvcError("must specify --trust-min/--trust-max or --origin")

    if results:
        for node_id in sorted(results):
            metadata = get_node_metadata(graph, node_id)
            label = metadata.get("label", "")
            print(f"  {node_id}: {label}")
    else:
        print("  (no matches)")

    return 0


def handle_graph_stats(args: argparse.Namespace) -> int:
    """Show graph statistics including metadata."""
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    graph = load_or_create_graph(tool_root)

    stats = graph_stats(graph)

    print("Graph Statistics:")
    print(f"  Nodes: {stats['nodes']}")
    print(f"  Edges: {stats['edges']}")
    print(f"  Density: {stats['density']:.3f}")
    print(f"  Average Trust: {stats['avg_trust']:.2f}")
    print(f"  Nodes with Lineage: {stats['nodes_with_lineage']}")
    if stats['origins']:
        print(f"  Origins: {', '.join(sorted(stats['origins']))}")

    return 0


def handle_ingest_langgraph(args: argparse.Namespace) -> int:
    """Ingest a LangGraph run trace (JSON) as a delta-stored descriptive snapshot."""
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR

    trace_path = Path(args.trace)
    if not trace_path.is_file():
        raise CtxvcError(f"trace file not found: {trace_path}")
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CtxvcError(f"invalid trace JSON: {exc}") from exc

    if args.run_name:
        trace["name"] = args.run_name

    snapshot_id = ingest_trace(
        tool_root,
        trace,
        graph_name=args.name,
        message=args.message,
        merge=args.merge,
        collapse=args.collapse,
    )

    graph = load_or_create_graph(tool_root, args.name)
    print(
        f"Ingested LangGraph run into snapshot {snapshot_id} "
        f"(graph '{args.name}': {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges)"
    )
    return 0


def handle_search(args: argparse.Namespace) -> int:
    """Semantically rank files (default) or snapshots by a natural-language query."""
    repo_root = find_repo_root(Path.cwd())
    tool_root = repo_root / TOOL_DIR
    refs = read_refs(tool_root)

    if args.snapshots:
        results = search_snapshots(tool_root, args.query, top_k=args.top)
        if not results:
            print("No snapshots to search")
            return 0
        print(f"Top {len(results)} snapshots for: {args.query}  [{EMBEDDER_LABEL}]")
        for result in results:
            print(
                f"  {result['similarity']:.2f}  {result['id']}  {result['message']}"
                f"  (best: {result['best_path']})"
            )
        return 0

    revision = None
    if args.rev:
        revision = resolve_revision(tool_root, refs, args.rev)

    results = search_files(tool_root, args.query, revision=revision, top_k=args.top)
    if not results:
        print("No files to search")
        return 0

    scope = f" in {revision}" if revision else ""
    print(f"Top {len(results)} files{scope} for: {args.query}  [{EMBEDDER_LABEL}]")
    for result in results:
        snapshots = result["snapshots"]
        where = snapshots[0] if len(snapshots) == 1 else f"{snapshots[0]} (+{len(snapshots) - 1} more)"
        print(f"  {result['similarity']:.2f}  {result['path']}  @{where}")
        if result["preview"]:
            print(f"        {result['preview']}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
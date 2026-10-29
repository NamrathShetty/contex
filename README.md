# ctxvc

`ctxvc` is a small local version-control style tool for LLM contexts.

It treats prompt/context files as versioned artifacts, with integrated knowledge graph support for modeling orchestrations and context relationships. Features include:

- initialize a context repository with embedded knowledge graph support
- snapshot prompt files with a message, capturing both file state and graph structure
- register multiple agents that each map to a file/folder subtree
- create one centralized snapshot for all sub-agents in an orchestrator, including graph state
- inspect history with token counting and graph evolution
- compare the working context against a previous revision, including graph changes
- materialize an old snapshot into a separate folder with full graph recovery
- model LLM context as directed knowledge graphs using NetworkX
- version-control graph changes alongside file snapshots
- recover graph state from any historical snapshot

## Why this exists

Git is good at versioning source files, but prompt engineering workflows often need a narrower tool:

- snapshot only the context files that matter to a run, including graph state
- compare prompt revisions without unrelated repo noise
- model orchestration structure and context relationships as directed graphs
- export a known-good context bundle for evaluation or replay
- track how context and orchestration evolve over time

This MVP stores immutable file contents under `.ctxvc/objects/`, keeps snapshot metadata under `.ctxvc/snapshots/`, and maintains versioned knowledge graphs under `.ctxvc/graphs/`.

## Installation

```bash
pip install ctxvc
```

The core install is lightweight. Heavier capabilities are opt-in via extras:

```bash
pip install "ctxvc[tokens]"     # accurate token counts (tiktoken)
pip install "ctxvc[semantic]"   # neural embeddings (sentence-transformers)
pip install "ctxvc[s3]"         # S3 / MinIO / R2 remotes (boto3)
pip install "ctxvc[qdrant]"     # remote vector index (qdrant-client)
pip install "ctxvc[all]"        # everything
```

After installing, use the `ctxvc` command directly:

```bash
ctxvc init
ctxvc snapshot examples/customer-support -m "Baseline support context"
ctxvc history
```

> The examples below use `python ctxvc.py …` so they also work from a source
> checkout without installing. Once installed, replace `python ctxvc.py` with
> `ctxvc`.

## Quick Start

From the project root:

```powershell
python ctxvc.py init

# Single file snapshot
python ctxvc.py snapshot examples\customer-support -m "Baseline support context"
python ctxvc.py history
python ctxvc.py status examples\customer-support
python ctxvc.py diff --path examples/customer-support/system.md
python ctxvc.py checkout 20260504141448 --dest exported-context

# Knowledge graph workflow
python ctxvc.py graph add-node "task1" "Primary task"
python ctxvc.py graph add-node "task2" "Related task"
python ctxvc.py graph add-edge "e1" "task1" "task2" "depends_on"
python ctxvc.py graph show
python ctxvc.py snapshot-all -m "Context with orchestration graph"
```

## Multi-Agent Orchestrator Workflow

Register each agent once, then snapshot everything centrally with graph integration:

```powershell
python ctxvc.py agent add planner examples\multi-agent\planner
python ctxvc.py agent add critic examples\multi-agent\critic
python ctxvc.py agent list

# Model agent relationships
python ctxvc.py graph add-node "planner" "Planning agent"
python ctxvc.py graph add-node "critic" "Review agent"
python ctxvc.py graph add-edge "e1" "planner" "critic" "sends_to"

python ctxvc.py snapshot-all -m "Orchestrator baseline"
python ctxvc.py status --agent critic
python ctxvc.py diff --agent critic
python ctxvc.py snapshot --agent planner -m "Planner-only update"

# See how agent graph evolved
python ctxvc.py graph diff <snapshot_id>
```

## Commands

### `init`

Creates `.ctxvc/` in the current directory.

```powershell
python ctxvc.py init
```

### `snapshot`

Captures one or more files or directories as a revision, including current graph state.

```powershell
python ctxvc.py snapshot prompt.txt -m "Initial prompt"
python ctxvc.py snapshot examples\customer-support -m "Support prompt v2"
python ctxvc.py snapshot --agent planner -m "Planner prompt revision"
```

### `snapshot-all`

Creates one centralized revision containing all registered agents and current graph state.

```powershell
python ctxvc.py snapshot-all -m "Orchestrator checkpoint"
```

### `history`

Shows snapshots from `HEAD` backwards.

```powershell
python ctxvc.py history --limit 10
python ctxvc.py history --tokens              # Include token counts and graph sizes
```

### `tokens`

Analyze token budget breakdown across files and agents.

```powershell
python ctxvc.py tokens
python ctxvc.py tokens <REVISION>
python ctxvc.py tokens --agent planner
```

### `status`

Compares working files against `HEAD`.

```powershell
python ctxvc.py status examples\customer-support
python ctxvc.py status --agent critic
```

Markers:

- `A` added in working tree
- `M` modified in working tree
- `D` deleted from working tree

### `diff`

Diffs `HEAD` against the working tree, or two snapshots (includes graph changes).

```powershell
python ctxvc.py diff
python ctxvc.py diff --path examples/customer-support/system.md
python ctxvc.py diff --agent planner
python ctxvc.py diff 20260504141448 20260504142000
```

### `agent`

Registers and manages agent-to-path mappings used by centralized orchestration workflows.

```powershell
python ctxvc.py agent add planner examples\multi-agent\planner
python ctxvc.py agent list
python ctxvc.py agent remove planner
```

### `graph`

Manages knowledge graphs representing orchestration and context relationships, with **metadata and lineage tracking** for data provenance.

```powershell
# Add a concept/node with metadata and lineage
python ctxvc.py graph add-node "concept_id" "Concept label" \
  --origin "source" \
  --trust 0.95 \
  --created-by "agent_name" \
  --lineage "parent_node1,parent_node2"

# Show detailed metadata and lineage for a node
python ctxvc.py graph info "concept_id"

# Trace complete lineage path (all ancestors)
python ctxvc.py graph lineage "concept_id" [--max-depth 10]

# Filter nodes by metadata
python ctxvc.py graph filter --trust-min 0.8 --trust-max 1.0
python ctxvc.py graph filter --origin "knowledge_base"

# View graph statistics with metadata insights
python ctxvc.py graph stats

# Remove a node
python ctxvc.py graph remove-node "concept_id"

# Add a directed relationship/edge
python ctxvc.py graph add-edge "edge_id" "source_node" "target_node" "relation_type"

# Remove an edge
python ctxvc.py graph remove-edge "edge_id"

# Display the current graph
python ctxvc.py graph show

# Compare graph state between revisions (including metadata changes)
python ctxvc.py graph diff <SNAPSHOT_A_ID> <SNAPSHOT_B_ID>
python ctxvc.py graph diff <SNAPSHOT_ID>          # Compare snapshot to working tree
```

**Metadata Support:**
- **origin**: Source/origin of information (e.g., "user", "knowledge_base", "inference_engine")
- **trust**: Confidence/reliability score (0.0-1.0, where 1.0 is fully trusted)
- **created_by**: Component/agent that created this node
- **lineage**: List of parent node IDs (data provenance - which nodes this was derived from)

### `show`

Prints snapshot metadata as JSON, including embedded graph state.

```powershell
python ctxvc.py show
```

### `checkout`

Writes a snapshot into another directory without overwriting the working tree. Recovers both files and graph state from the snapshot.

```powershell
python ctxvc.py checkout 20260504141448 --dest exported-context
```

### `branch`

Manage branches for different experiment/production lines. Each branch maintains its own file snapshots and graph history.

```powershell
python ctxvc.py branch create "experiment-a"
python ctxvc.py branch list
python ctxvc.py branch switch "experiment-a"
python ctxvc.py branch switch "main"
```

### `tag`

Tag important snapshots for easy reference.

```powershell
python ctxvc.py tag add "validated-v1" <SNAPSHOT_ID>
python ctxvc.py tag list
python ctxvc.py tag remove "validated-v1"
```

### `handoff`

Coordinate multi-agent workflows using branch-per-agent handoffs.

```powershell
python ctxvc.py handoff start planner          # begin work as an agent
python ctxvc.py handoff to coder -m "ready for implementation"
python ctxvc.py handoff to coder --rev <SNAPSHOT_ID>   # hand off a specific revision
python ctxvc.py handoff log                     # show recent handoffs
```

### `search`

Semantically rank files or snapshots by a natural-language query. Uses neural
embeddings when `sentence-transformers` is installed, otherwise a deterministic
offline lexical fallback.

```powershell
python ctxvc.py search "how do we handle authentication"
python ctxvc.py search "retry logic" --rev <SNAPSHOT_ID>
python ctxvc.py search "planning strategy" --snapshots --top 5
```

### `remote`, `push`, `pull`

Share snapshots between repositories. Objects and snapshots are immutable and
content-addressed, so only missing data is transferred; branch refs use
compare-and-swap with fast-forward protection (like git).

```powershell
# Filesystem remote
python ctxvc.py remote add origin ../shared-context-remote
# S3 / MinIO / R2 remote (needs the [s3] extra; credentials from the AWS chain)
python ctxvc.py remote add prod --type s3 --bucket my-bucket --prefix team/ --endpoint-url https://minio.local

python ctxvc.py remote list
python ctxvc.py push origin            # push current branch
python ctxvc.py pull origin main
python ctxvc.py push origin --force    # allow non-fast-forward
```

### `vindex`

Maintain a shared remote vector index (Qdrant) so multiple agents query one
semantic surface instead of each re-embedding history. Needs the `[qdrant]`
extra. The index is a derived, rebuildable cache — never a source of truth — and
the embedder used is pinned per point.

```powershell
python ctxvc.py vindex add team ctxvc --url http://localhost:6333 --api-key-env QDRANT_API_KEY
python ctxvc.py vindex sync team           # embed + upsert content objects
python ctxvc.py vindex search team "vector database design" --top 5
python ctxvc.py vindex sync team --rebuild # rebuild after changing embedder
```

## Knowledge Graph Use Cases

### 1. Multi-Agent Orchestration
Model how agents coordinate and communicate:
```bash
ctxvc.py graph add-node "orchestrator" "Main controller"
ctxvc.py graph add-node "planner" "Planning agent"
ctxvc.py graph add-node "critic" "Review agent"
ctxvc.py graph add-edge "e1" "orchestrator" "planner" "delegates_to"
ctxvc.py graph add-edge "e2" "planner" "critic" "sends_to"
ctxvc.py snapshot-all -m "Orchestration structure"
```

### 2. RAG Context Graphs
Version control relationships between queries, documents, and synthesis:
```bash
ctxvc.py graph add-node "query" "User question"
ctxvc.py graph add-node "doc1" "Retrieved document"
ctxvc.py graph add-node "answer" "Generated response"
ctxvc.py graph add-edge "e1" "query" "doc1" "matches"
ctxvc.py graph add-edge "e2" "doc1" "answer" "supports"
```

### 3. Task Decomposition
Track how tasks decompose and aggregate:
```bash
ctxvc.py graph add-node "main_task" "Overall objective"
ctxvc.py graph add-node "subtask_1" "Part 1"
ctxvc.py graph add-node "subtask_2" "Part 2"
ctxvc.py graph add-edge "e1" "main_task" "subtask_1" "decomposes_to"
ctxvc.py graph add-edge "e2" "main_task" "subtask_2" "decomposes_to"
```

See [docs/GRAPH_EXAMPLES.md](docs/GRAPH_EXAMPLES.md) for detailed examples and advanced usage.

## Storage Model

```
.ctxvc/
  config.json           # Repository metadata, agent registry, remote/index config
  ctxvc.db              # SQLite: HEAD, branches, tags, snapshot index, handoffs
  graphs/
    default.json        # Current knowledge graph (NetworkX format)
  snapshots/
    TIMESTAMP.json      # Snapshot with file index, metadata, and embedded graph state
  objects/
    {hash}.txt.gz       # Immutable, gzip-compressed file contents
```

## Suggested Next Features

If you want to turn this into a stronger product, the next useful layers are:

1. Graph visualization (ASCII tree, Mermaid export, GraphML/GEXF)
2. Graph query language (find nodes by attribute, path traversal)
3. Semantic diffs for JSON chat transcripts and prompt templates
4. Dataset-linked snapshots so prompts and evaluation results stay connected
5. Bulk import/export of graphs (CSV, RDF, knowledge base formats)
6. Performance optimization for graphs with thousands of nodes

## Validation

Current validation path:

```powershell
python -m py_compile ctxvc.py src/ctxvc/*.py
python ctxvc.py init
python ctxvc.py snapshot prompt.txt -m "Initial prompt"
python ctxvc.py status prompt.txt
python ctxvc.py history
python ctxvc.py diff --path prompt.txt

# Graph integration
python ctxvc.py graph add-node "test" "Test concept"
python ctxvc.py graph show
python ctxvc.py snapshot-all -m "Graph snapshot"
python ctxvc.py graph diff <snapshot_id>
```
# Context Version Control - Knowledge Graph Examples

This document demonstrates the NetworkX-based knowledge graph versioning system with **metadata and lineage tracking** integrated with context snapshots.

## Quick Start: Build a Knowledge Graph with Provenance

### 1. Initialize the Repository
```bash
python ctxvc.py init
python ctxvc.py agent add orchestrator ./agents/orchestrator
python ctxvc.py agent add planner ./agents/planner
```

### 2. Create Nodes with Metadata & Lineage

Each node can track:
- **Origin**: Where the information came from (e.g., "user", "knowledge_base", "inference_engine")
- **Trust**: Confidence/reliability score (0.0-1.0, where 1.0 is fully trusted)
- **Created by**: Which component/agent created this node
- **Lineage**: List of parent nodes (data provenance - which nodes this was derived from)

```bash
# Create a trusted knowledge base concept
python ctxvc.py graph add-node "domain_fact" "Core domain knowledge" \
  --origin "knowledge_base" \
  --trust 0.95 \
  --created-by "curator"

# Create an inferred concept (derived from the domain fact)
python ctxvc.py graph add-node "inference" "Inferred insight" \
  --origin "inference_engine" \
  --trust 0.75 \
  --created-by "reasoning_agent" \
  --lineage "domain_fact"

# Create a user-provided concept (lower confidence)
python ctxvc.py graph add-node "user_input" "User query" \
  --origin "user" \
  --trust 0.5 \
  --created-by "user"

# Create a synthesized answer (combines multiple sources)
python ctxvc.py graph add-node "answer" "Synthesized response" \
  --origin "synthesis_engine" \
  --trust 0.8 \
  --created-by "answer_generator" \
  --lineage "domain_fact,inference,user_input"
```

### 3. Inspect Node Metadata
```bash
# View all metadata for a node
python ctxvc.py graph info answer

# Output:
# Node: answer
#   Label: Synthesized response
#   Origin: synthesis_engine
#   Trust: 0.80
#   Created by: answer_generator
#   Created at: 2026-06-30T10:21:56.603089
#   Lineage (parents): domain_fact, inference, user_input
```

### 4. Trace Data Lineage
```bash
# See complete lineage path (all ancestors)
python ctxvc.py graph lineage answer

# Output:
# Lineage path for 'answer' (depth: 3):
# └─ answer: Synthesized response [origin=synthesis_engine] [trust=0.80]
#   └─ domain_fact: Core domain knowledge [origin=knowledge_base] [trust=0.95]
#     └─ inference: Inferred insight [origin=inference_engine] [trust=0.75]
#       └─ user_input: User query [origin=user] [trust=0.50]
```

### 5. Filter Nodes by Metadata
```bash
# Find all high-confidence nodes
python ctxvc.py graph filter --trust-min 0.8 --trust-max 1.0

# Find all knowledge from a specific source
python ctxvc.py graph filter --origin "knowledge_base"

# Find all user-provided content
python ctxvc.py graph filter --origin "user"
```

### 6. View Graph Statistics with Metadata
```bash
python ctxvc.py graph stats

# Output:
# Graph Statistics:
#   Nodes: 4
#   Edges: 3
#   Density: 0.333
#   Average Trust: 0.75
#   Nodes with Lineage: 2
#   Origins: knowledge_base, inference_engine, synthesis_engine, user
```

### 7. Add Relationships
```bash
# Connect the nodes
python ctxvc.py graph add-edge "e1" "domain_fact" "inference" "informs"
python ctxvc.py graph add-edge "e2" "inference" "answer" "supports"
python ctxvc.py graph add-edge "e3" "user_input" "answer" "prompts"
```

### 8. Snapshot with Metadata
```bash
# Capture everything including metadata and lineage
python ctxvc.py snapshot-all -m "Knowledge graph with full provenance"

# Later, view or diff the graph
python ctxvc.py graph diff <snapshot_id>
```

## Use Cases

### 1. RAG System with Trust Tracking
Track document retrieval, inference, and synthesis with confidence:

```bash
# Document from knowledge base
ctxvc.py graph add-node "doc_1" "Retrieved document" \
  --origin "rag_retriever" --trust 0.95 --created-by "semantic_search"

# Generated answer combines multiple documents
ctxvc.py graph add-node "rag_answer" "Generated response" \
  --origin "rag_synthesis" --trust 0.85 --created-by "answer_generator" \
  --lineage "doc_1,doc_2,doc_3"
```

### 2. Multi-Agent Reasoning Chain
Track how different agents contribute to reasoning:

```bash
# Planner analyzes the problem
ctxvc.py graph add-node "analysis" "Problem analysis" \
  --origin "planning_agent" --trust 0.9 --created-by "planner"

# Reasoner infers implications
ctxvc.py graph add-node "implications" "Inferred implications" \
  --origin "reasoning_engine" --trust 0.7 --created-by "reasoner" \
  --lineage "analysis"

# Critic validates the reasoning
ctxvc.py graph add-node "validation" "Validated conclusion" \
  --origin "critic_agent" --trust 0.85 --created-by "critic" \
  --lineage "analysis,implications"
```

### 3. Data Lineage Audit
Ensure traceability of information through your system:

```bash
# Each transformation step becomes a node
ctxvc.py graph add-node "raw_input" "Raw user input" \
  --origin "user" --trust 0.5 --created-by "user"

ctxvc.py graph add-node "cleaned_input" "Cleaned and normalized" \
  --origin "preprocessor" --trust 0.95 --created-by "data_cleaner" \
  --lineage "raw_input"

ctxvc.py graph add-node "enriched" "Enriched with context" \
  --origin "context_engine" --trust 0.85 --created-by "enricher" \
  --lineage "cleaned_input"

ctxvc.py graph add-node "final_output" "Final processed result" \
  --origin "output_formatter" --trust 0.9 --created-by "formatter" \
  --lineage "enriched"
```

### 4. LLM Context Evolution
Track how context evolves through conversation turns with trust scores:

```bash
# Turn 1
ctxvc.py graph add-node "context_v1" "Initial context" \
  --origin "system" --trust 1.0 --created-by "system"
ctxvc.py snapshot-all -m "Turn 1: Initial context"

# Turn 2 - Context refined based on user feedback
ctxvc.py graph add-node "context_v2" "Refined context" \
  --origin "learning_engine" --trust 0.85 --created-by "learner" \
  --lineage "context_v1"
ctxvc.py snapshot-all -m "Turn 2: Context refined"

# Query evolution
ctxvc.py graph diff <turn1_id> <turn2_id>
```

## Metadata Fields Reference

### Node Metadata
```python
# Required
node_id: str              # Unique identifier
label: str                # Human-readable label

# Optional
origin: str               # Source of information
                         # Examples: "user", "knowledge_base", "inference_engine", "document_123"
trust: float             # Confidence score (0.0-1.0)
                         # 1.0 = fully trusted (system fact, database record)
                         # 0.9+ = very high confidence
                         # 0.7-0.9 = inference/synthesis
                         # 0.5-0.7 = user-provided or uncertain
                         # <0.5 = speculative/unvalidated

created_by: str          # Component/agent that created this
                         # Examples: "user", "curator", "planner", "critic", "inference_engine"

lineage: list[str]       # Parent node IDs (provenance)
                         # Tracks data flow: which nodes this was derived from
```

### Edge Metadata
```python
relation: str            # Relationship type
                         # Examples: "informs", "supports", "contradicts", "depends_on"

flow_type: str          # Data flow type
                         # Examples: "direct", "inferred", "aggregated", "synthesized"

# Additional custom properties
weight: float           # Edge strength/confidence
confidence: float       # Confidence in the relationship
# ... any other JSON-serializable property
```

## Snapshot Structure with Metadata

```json
{
  "id": "20260630102326",
  "created_at": "2026-06-30T10:23:26+00:00",
  "message": "Knowledge graph with full provenance",
  "graphs": {
    "default": {
      "nodes": [
        {
          "id": "domain_fact",
          "label": "Core domain knowledge",
          "origin": "knowledge_base",
          "trust": 0.95,
          "created_by": "curator",
          "created_at": "2026-06-30T10:21:56.603089",
          "lineage": []
        },
        {
          "id": "answer",
          "label": "Synthesized response",
          "origin": "synthesis_engine",
          "trust": 0.8,
          "created_by": "answer_generator",
          "created_at": "2026-06-30T10:21:58.123456",
          "lineage": ["domain_fact", "inference", "user_input"]
        }
      ],
      "links": [
        {
          "source": "domain_fact",
          "target": "inference",
          "relation": "informs"
        }
      ]
    }
  }
}
```

## Advanced Commands

### View detailed node information
```bash
ctxvc.py graph info <NODE_ID>
```

### Trace complete lineage path
```bash
ctxvc.py graph lineage <NODE_ID> [--max-depth 10]
```

### Filter by trust range
```bash
ctxvc.py graph filter --trust-min 0.8 --trust-max 1.0
```

### Filter by origin
```bash
ctxvc.py graph filter --origin "knowledge_base"
```

### Show graph statistics with metadata
```bash
ctxvc.py graph stats
```

## Storage and Serialization

### File Structure
```
.ctxvc/
  graphs/
    default.json          # Current graph with all metadata
  snapshots/
    TIMESTAMP.json        # Snapshot with embedded graphs (metadata preserved)
```

### Metadata Persistence
- All node metadata (origin, trust, created_by, lineage) is serialized in snapshots
- Metadata survives `checkout`, `snapshot-all`, and historical recovery
- Metadata is JSON-serializable (supports all JSON types: string, number, boolean, null, array, object)

## Best Practices

### 1. Trust Scoring
- **1.0**: System facts, database records, validated knowledge
- **0.9+**: High-confidence inference, trusted sources
- **0.7-0.9**: Synthesis results, moderate-confidence inference
- **0.5-0.7**: User input, speculative reasoning
- **<0.5**: Unvalidated hypotheses, placeholder data

### 2. Origin Naming
Use clear, consistent origin names for easy filtering:
- `user` - direct user input
- `knowledge_base` - trusted knowledge base
- `inference_engine` - automated inference
- `synthesis_engine` - aggregation/synthesis
- `document_<id>` - specific document
- `<agent_name>` - specific agent/service

### 3. Lineage Best Practices
- Keep lineage focused on direct parents (not full ancestry)
- Use graph lineage tracing to see full ancestors
- Mark all derived nodes with lineage for auditability
- Use empty lineage only for "origin" nodes (primary sources)

### 4. Metadata Evolution
```bash
# Add metadata to existing nodes
ctxvc.py graph add-node "existing" "label" --origin "new_origin"
# This updates the node if it exists, preserving other metadata

# Track metadata changes across snapshots
ctxvc.py graph diff <snapshot1> <snapshot2>
```

## Integration with Existing Features

### Token Budgeting
Graph metadata is included in token count statistics:
```bash
ctxvc.py history --tokens
```

### Branching for Experiments
```bash
ctxvc.py branch create "experiment-with-high-trust"
# Create nodes with high trust scores
ctxvc.py graph add-node "exp_node" "Experimental" --origin "experiment" --trust 0.95
ctxvc.py snapshot-all -m "Experiment setup"

# Compare with main branch
ctxvc.py branch switch "main"
ctxvc.py graph diff <exp_snapshot_id>
```

### Tagging Important States
```bash
ctxvc.py snapshot-all -m "Stable knowledge graph"
# Get snapshot ID from history, then:
ctxvc.py tag add "validated-knowledge-v1" <SNAPSHOT_ID>

# Later reference it
ctxvc.py graph diff "validated-knowledge-v1"
```

## Querying Examples

### Find all unreliable information
```bash
ctxvc.py graph filter --trust-min 0 --trust-max 0.5
```

### Find all user-provided context
```bash
ctxvc.py graph filter --origin "user"
```

### Audit data lineage
```bash
ctxvc.py graph lineage <FINAL_NODE_ID>
```

### Export for analysis
```python
# In Python code:
from ctxvc.graph_store import get_graph_from_snapshot
import networkx as nx

graph = get_graph_from_snapshot(tool_root, "snapshot_id")

# Analyze metadata
for node, attrs in graph.nodes(data=True):
    if attrs.get('trust', 1.0) < 0.7:
        print(f"Low-confidence node: {node} (trust={attrs['trust']})")
    lineage = attrs.get('lineage', [])
    if lineage:
        print(f"Node {node} derived from: {lineage}")

# Export to file
nx.write_graphml(graph, "graph_with_metadata.graphml")
```

## Performance

- Metadata adds ~100 bytes per node (JSON-serialized)
- Lineage tracking adds ~20 bytes per parent reference
- Trust scores: negligible overhead (<1 byte per node)
- 1000 nodes with full metadata ≈ 100-150 KB in snapshots

## Future Enhancements

- [ ] Lineage visualization (ASCII tree, Mermaid DAG)
- [ ] Trust propagation (computed trust from ancestors)
- [ ] Metadata search/query language
- [ ] Confidence anomaly detection
- [ ] Lineage compression for large graphs
- [ ] GraphML/RDF export with metadata

## Quick Start: Build a Multi-Agent Orchestration Graph

### 1. Initialize the Repository
```bash
python ctxvc.py init
python ctxvc.py agent add orchestrator ./agents/orchestrator
python ctxvc.py agent add planner ./agents/planner
python ctxvc.py agent add critic ./agents/critic
```

### 2. Model Your Orchestration Structure
```bash
# Define the orchestration nodes
python ctxvc.py graph add-node "orchestrator" "Main orchestration controller" --props '{"type":"system"}'
python ctxvc.py graph add-node "planner" "Planning & decomposition" --props '{"type":"agent"}'
python ctxvc.py graph add-node "critic" "Review & validation" --props '{"type":"agent"}'
python ctxvc.py graph add-node "executor" "Execution engine" --props '{"type":"system"}'

# Define relationships
python ctxvc.py graph add-edge "e1" "orchestrator" "planner" "delegates_to" --props '{"priority":1}'
python ctxvc.py graph add-edge "e2" "planner" "critic" "sends_to"
python ctxvc.py graph add-edge "e3" "critic" "executor" "approves"
python ctxvc.py graph add-edge "e4" "executor" "orchestrator" "reports_to"
```

### 3. View the Current Graph
```bash
python ctxvc.py graph show
```

**Output:**
```
Nodes (4):
  orchestrator: Main orchestration controller
  planner: Planning & decomposition
  critic: Review & validation
  executor: Execution engine

Edges (4):
  orchestrator -[delegates_to]-> planner
  planner -[sends_to]-> critic
  critic -[approves]-> executor
  executor -[reports_to]-> orchestrator
```

### 4. Snapshot the Graph with Agent Context
```bash
python ctxvc.py snapshot-all -m "Initial orchestration setup with all agents"
```

This creates a snapshot that includes:
- All agent context files
- Current graph state (stored in `snapshot["graphs"]["default"]`)
- Token counts for budget tracking
- Timestamp and message

### 5. Track Changes Over Time
```bash
# Modify the graph (add a new decision node)
python ctxvc.py graph add-node "decision_engine" "Decision logic" --props '{"type":"service"}'
python ctxvc.py graph add-edge "e5" "planner" "decision_engine" "uses"

# Show what changed since the snapshot
python ctxvc.py graph diff <snapshot_id>
```

**Output:**
```
Graph diff: <snapshot_id> -> working
  Nodes added: decision_engine
  Edges added: e5
```

## Advanced: Querying Graph History

### Compare Two Snapshots
```bash
python ctxvc.py graph diff <snapshot_a_id> <snapshot_b_id>
```

### Recover Graph State from Snapshot
```python
# In Python code:
from ctxvc.graph_store import get_graph_from_snapshot
from ctxvc.store import find_repo_root
from pathlib import Path

repo_root = find_repo_root(Path.cwd())
tool_root = repo_root / '.ctxvc'

# Load the graph as it existed at a specific revision
graph_at_v1 = get_graph_from_snapshot(tool_root, 'snapshot_id_123')
print(f"Graph had {len(graph_at_v1.nodes())} nodes at v1")
```

### Export Graph to NetworkX Format
```python
import networkx as nx
from ctxvc.graph_store import load_or_create_graph

# Get current graph
graph = load_or_create_graph(tool_root)

# Analyze with NetworkX
print(f"Density: {nx.density(graph)}")
print(f"Shortest path planner->executor: {nx.shortest_path(graph, 'planner', 'executor')}")

# Export to formats
nx.write_gexf(graph, "orchestration.gexf")    # Gephi format
nx.write_graphml(graph, "orchestration.xml")  # GraphML format
```

## Storage Model

### File Structure
```
.ctxvc/
  graphs/
    default.json          # Current graph (node_link_data format)
  snapshots/
    TIMESTAMP.json        # Snapshot with embedded graph state
```

### Snapshot Structure
```json
{
  "id": "20260630094241",
  "parent": "20260630093709",
  "created_at": "2026-06-30T09:42:41+00:00",
  "message": "Multi-agent orchestration graph",
  "agents": ["planner", "critic"],
  "files": [...],
  "total_tokens": 1250,
  "graphs": {
    "default": {
      "directed": true,
      "multigraph": false,
      "graph": {},
      "nodes": [
        {"id": "orchestrator", "label": "Main orchestration controller", "type": "system"},
        ...
      ],
      "links": [
        {"source": "orchestrator", "target": "planner", "relation": "delegates_to", "priority": 1},
        ...
      ]
    }
  }
}
```

### Node Properties
Nodes support arbitrary JSON properties:
```bash
python ctxvc.py graph add-node "task1" "Analysis" --props '{"priority":1,"timeout":300,"retry_count":3}'
```

### Edge Properties
Edges store relationship metadata:
```bash
python ctxvc.py graph add-edge "e1" "source" "target" "flow_type" --props '{"async":true,"priority":2}'
```

## Use Cases

### 1. LLM Context Evolution
Track how LLM context (knowledge graphs) evolves through a multi-turn conversation:
```bash
# Turn 1
ctxvc graph add-node "user_intent" "User's original request"
ctxvc snapshot-all -m "Turn 1: Intent captured"

# Turn 2
ctxvc graph add-node "refined_intent" "Refined understanding"
ctxvc graph add-edge "e1" "user_intent" "refined_intent" "evolves_to"
ctxvc snapshot-all -m "Turn 2: Intent refined"

# Query history
ctxvc graph diff <turn1_snapshot> <turn2_snapshot>
```

### 2. Multi-Agent Orchestration
Model how agents coordinate:
```bash
ctxvc graph add-node "task_decomposer" "Breaks down tasks"
ctxvc graph add-node "worker_1" "Executes subtask 1"
ctxvc graph add-node "worker_2" "Executes subtask 2"
ctxvc graph add-node "aggregator" "Combines results"

ctxvc graph add-edge "d1" "task_decomposer" "worker_1" "assigns"
ctxvc graph add-edge "d2" "task_decomposer" "worker_2" "assigns"
ctxvc graph add-edge "a1" "worker_1" "aggregator" "reports"
ctxvc graph add-edge "a2" "worker_2" "aggregator" "reports"
```

### 3. RAG System Knowledge Graphs
Version control the relationship between documents and queries:
```bash
ctxvc graph add-node "query" "User question"
ctxvc graph add-node "doc1" "Retrieved document 1"
ctxvc graph add-node "doc2" "Retrieved document 2"
ctxvc graph add-node "synthesis" "Generated answer"

ctxvc graph add-edge "r1" "query" "doc1" "matches"
ctxvc graph add-edge "r2" "query" "doc2" "matches"
ctxvc graph add-edge "s1" "doc1" "synthesis" "contributes_to"
ctxvc graph add-edge "s2" "doc2" "synthesis" "contributes_to"
```

## Command Reference

### Graph Operations
```bash
# Add a node with optional properties
ctxvc.py graph add-node <NODE_ID> <LABEL> [--props '{"key":"value"}']

# Remove a node
ctxvc.py graph remove-node <NODE_ID>

# Add an edge (directed relationship)
ctxvc.py graph add-edge <EDGE_ID> <SOURCE> <TARGET> <RELATION> [--props '{}']

# Remove an edge
ctxvc.py graph remove-edge <EDGE_ID>

# Show current graph
ctxvc.py graph show

# Compare graph states between revisions
ctxvc.py graph diff [REV_A] [REV_B]
```

### Snapshots with Graphs
```bash
# Snapshot all agents with current graph state
ctxvc.py snapshot-all -m "Message describing snapshot"

# Snapshot specific agents with graph state
ctxvc.py snapshot -m "Message" --agent planner --agent critic

# View snapshot metadata (includes embedded graph)
ctxvc.py show <SNAPSHOT_ID>

# Show snapshot history with token counts
ctxvc.py history --tokens --limit 10
```

## Integration with Existing Features

### Token Budgeting
Snapshots now include graph complexity metrics:
```bash
ctxvc.py history --tokens
```

Output includes:
- File token counts
- Total tokens across all files
- Graph nodes/edges (for monitoring context size)

### Branching with Graph State
Each branch maintains its own graph history:
```bash
ctxvc.py branch create "experiment-a"
ctxvc.py branch switch "experiment-a"
ctxvc.py graph add-node "experimental_feature" "Feature being tested"
ctxvc.py snapshot-all -m "Experimental setup"

# Switch back to main
ctxvc.py branch switch "main"
ctxvc.py graph show  # Shows original graph
```

### Tagging Graph Versions
Mark important graph states:
```bash
ctxvc.py snapshot-all -m "Orchestration validated"
# After getting snapshot ID from history
ctxvc.py tag add "validated-v1" <SNAPSHOT_ID>
ctxvc.py tag list
# Later reference it
ctxvc.py graph diff "validated-v1"
```

## Performance Notes

- **Graph Serialization**: Uses NetworkX's optimized `node_link_data()` format (~50 bytes per node/edge)
- **Snapshot Size**: 100-node graph ≈ 5-10 KB in snapshot JSON
- **Memory**: NetworkX DiGraph stays in memory; minimal for graphs <10K nodes
- **Scaling**: Tested with thousands of nodes; linear complexity for most operations

## Future Enhancements

- [ ] Graph visualization (ASCII tree, Mermaid export)
- [ ] Graph query language (find nodes by attribute, path traversal)
- [ ] Bulk import/export (CSV, GraphML, RDF formats)
- [ ] Graph compression for large histories
- [ ] Query optimization (indexing frequently accessed paths)

# Metadata & Lineage Tracking - Design Overview

## Overview

The context version control system now supports rich metadata on knowledge graph nodes, enabling:

1. **Data Provenance**: Track where information came from (origin)
2. **Confidence Tracking**: Assign trust scores to capture information reliability
3. **Lineage Tracking**: Record which nodes were used to derive new nodes
4. **Auditability**: Complete traceability through your LLM pipeline

## Core Concepts

### Origin
**What**: Where did this information come from?

Examples:
- `"user"` - Direct user input
- `"knowledge_base"` - Trusted knowledge base
- `"inference_engine"` - Automated reasoning
- `"synthesis_engine"` - Aggregation/synthesis of multiple sources
- `"document_xyz"` - Specific source document
- `"agent_planner"` - Specific agent/service

**Use Cases**:
- Filter nodes to only use high-quality sources
- Track which agents contributed information
- Audit information flow through your system

### Trust
**What**: How confident are you in this information?

**Scale** (0.0 = no confidence, 1.0 = fully trusted):
- **1.0**: System facts, database records, validated knowledge
- **0.9+**: High-confidence inference, outputs from trusted systems
- **0.7-0.9**: Synthesis results, moderate-confidence inference
- **0.5-0.7**: User input, speculative reasoning
- **<0.5**: Unvalidated hypotheses, placeholder data

**Use Cases**:
- Filter to only high-confidence nodes before making decisions
- Weight nodes in downstream processing by confidence
- Track degradation of confidence through reasoning chains
- Generate warnings when reasoning from low-confidence sources

### Lineage
**What**: Which nodes was this derived from?

Example lineage chain:
```
Raw Input (trust=0.5)
    ↓ (processed by data_cleaner)
Cleaned Input (trust=0.95)
    ↓ (enriched by context_engine)
Enriched Input (trust=0.85)
    ↓ (synthesized by answer_generator)
Final Answer (trust=0.8)
```

**Use Cases**:
- Trace how information flowed through your pipeline
- Identify weak links in reasoning chains
- Audit data quality path
- Understand dependencies between concepts
- Regenerate only affected downstream nodes if source changes

## Workflow Examples

### Example 1: RAG with Trust Tracking

```bash
# Document retrieved from knowledge base (high trust)
ctxvc.py graph add-node "doc_search_001" "Retrieved document on Topic X" \
  --origin "rag_retriever" \
  --trust 0.95 \
  --created-by "semantic_search_engine"

# Another document (less directly relevant)
ctxvc.py graph add-node "doc_search_002" "Potentially relevant document" \
  --origin "rag_retriever" \
  --trust 0.65 \
  --created-by "semantic_search_engine"

# Synthesis combines both (moderate confidence)
ctxvc.py graph add-node "rag_answer" "Generated answer" \
  --origin "synthesis_engine" \
  --trust 0.8 \
  --created-by "llm_synthesizer" \
  --lineage "doc_search_001,doc_search_002"

# Later: Query all high-confidence information
ctxvc.py graph filter --trust-min 0.8 --trust-max 1.0

# Trace where the answer came from
ctxvc.py graph lineage rag_answer
```

Output shows:
- Final answer originated from two documents
- One document is highly trusted (0.95), one less so (0.65)
- Synthesis process reduced confidence from 0.95 to 0.8 (combining sources)

### Example 2: Multi-Agent Reasoning

```bash
# Planning phase: Planner analyzes the problem
ctxvc.py graph add-node "problem_analysis" "Problem analyzed into components" \
  --origin "planning_agent" \
  --trust 0.9 \
  --created-by "planner"

# Reasoning phase: Reasoner infers implications
ctxvc.py graph add-node "reasoned_implications" "Inferred implications and relationships" \
  --origin "reasoning_engine" \
  --trust 0.7 \
  --created-by "reasoner" \
  --lineage "problem_analysis"

# Critic phase: Critic validates reasoning
ctxvc.py graph add-node "validated_conclusion" "Validated and approved conclusion" \
  --origin "critic_agent" \
  --trust 0.85 \
  --created-by "critic" \
  --lineage "problem_analysis,reasoned_implications"

# Synthesis: Combine into final response
ctxvc.py graph add-node "final_response" "Final response to user" \
  --origin "synthesis_engine" \
  --trust 0.82 \
  --created-by "response_generator" \
  --lineage "validated_conclusion"

# Track the flow
ctxvc.py graph lineage final_response

# Output shows: final_response ← validated_conclusion ← reasoned_implications ← problem_analysis
#              with trust degradation: 0.82 ← 0.85 ← 0.7 ← 0.9
```

### Example 3: Data Quality Auditing

```bash
# User provides raw input
ctxvc.py graph add-node "user_requirement" "User requirements" \
  --origin "user" \
  --trust 0.5 \
  --created-by "user"

# Data pipeline: Clean and normalize
ctxvc.py graph add-node "normalized" "Normalized requirements" \
  --origin "data_cleaner" \
  --trust 0.95 \
  --created-by "data_pipeline" \
  --lineage "user_requirement"

# Enrich with context
ctxvc.py graph add-node "enriched" "Requirements with domain context" \
  --origin "context_engine" \
  --trust 0.85 \
  --created-by "context_enricher" \
  --lineage "normalized"

# Validate against patterns
ctxvc.py graph add-node "validated" "Validated requirements" \
  --origin "validation_engine" \
  --trust 0.9 \
  --created-by "validator" \
  --lineage "enriched"

# Generate plan
ctxvc.py graph add-node "plan" "Generated execution plan" \
  --origin "planner" \
  --trust 0.8 \
  --created-by "planner" \
  --lineage "validated"

# Later: Show complete data lineage
ctxvc.py graph lineage plan

# Shows: plan ← validated ← enriched ← normalized ← user_requirement
# Trust progression: 0.8 ← 0.9 ← 0.85 ← 0.95 ← 0.5
```

## Storage & Persistence

### Node Metadata Structure
```python
{
    "id": "node_id",
    "label": "Human-readable label",
    "origin": "source",                    # Optional
    "trust": 0.85,                         # Optional, 0.0-1.0
    "created_by": "agent_name",            # Optional
    "created_at": "ISO8601 timestamp",     # Auto-added
    "lineage": ["parent1", "parent2"],     # Optional, empty if origin node
    # ... any other custom JSON properties
}
```

### Snapshot Embedding
Metadata is fully preserved in snapshots:

```json
{
  "id": "20260630102326",
  "graphs": {
    "default": {
      "nodes": [
        {
          "id": "kb_concept",
          "label": "Domain Knowledge",
          "origin": "knowledge_base",
          "trust": 0.95,
          "created_by": "curator",
          "created_at": "2026-06-30T10:21:56.603089",
          "lineage": []
        },
        {
          "id": "synthesis",
          "label": "Synthesized Answer",
          "origin": "synthesis_engine",
          "trust": 0.8,
          "created_by": "answer_gen",
          "created_at": "2026-06-30T10:21:58.123456",
          "lineage": ["kb_concept", "inference", "user_concept"]
        }
      ]
    }
  }
}
```

**Key Property**: Metadata survives:
- Snapshots and checkouts
- Branch switching
- Historical recovery
- Export/import operations

## Querying & Analysis

### View Node Metadata
```bash
ctxvc.py graph info <NODE_ID>
```

Output:
```
Node: synthesis
  Label: Synthesized Answer
  Origin: synthesis_engine
  Trust: 0.80
  Created by: answer_gen
  Created at: 2026-06-30T10:21:56.603089
  Lineage (parents): kb_concept, inference, user_concept
```

### Trace Lineage
```bash
ctxvc.py graph lineage <NODE_ID>
```

Shows complete ancestor tree with trust scores and origins.

### Filter by Metadata
```bash
# High-confidence nodes
ctxvc.py graph filter --trust-min 0.8 --trust-max 1.0

# User-provided content
ctxvc.py graph filter --origin "user"

# Knowledge base content
ctxvc.py graph filter --origin "knowledge_base"
```

### Statistics with Metadata
```bash
ctxvc.py graph stats
```

Output includes:
- Average trust score across graph
- Number of nodes with lineage
- Origins present in graph

## Best Practices

### 1. Trust Score Consistency
- Use same scale across your system
- Document trust levels for each component
- Validate actual vs expected trust periodically
- Lower trust scores through reasoning chains (confidence decreases)

### 2. Lineage Completeness
- Mark ALL derived nodes with their parents
- Include all direct parents (don't need full ancestry - graph traversal handles that)
- Update lineage when combining sources
- Use empty lineage only for primary sources

### 3. Origin Naming
- Use consistent, queryable origin names
- Consider namespacing: `{source_type}/{source_name}`
- Examples: `db/users`, `api/openweather`, `user/input`
- Document your organization's origin taxonomy

### 4. Metadata Updates
```bash
# Update metadata on existing node
ctxvc.py graph add-node "existing" "label" --trust 0.9 --origin "new_source"

# Preserves other metadata, updates specified fields
```

### 5. Snapshots for Checkpoints
```bash
# Create snapshots at important milestones
ctxvc.py snapshot-all -m "High-confidence knowledge graph built"

# Reference by snapshot ID for later analysis
ctxvc.py graph diff <old_snapshot> <new_snapshot>
```

## Integration Patterns

### Pattern 1: Trust-Aware Processing
```python
from ctxvc.graph_store import load_or_create_graph
from ctxvc.graph import filter_by_trust

graph = load_or_create_graph(tool_root)

# Only use high-confidence nodes
high_confidence = filter_by_trust(graph, min_trust=0.8)

for node_id in high_confidence:
    process_node(node_id)
```

### Pattern 2: Lineage-Based Invalidation
```python
def node_changed(graph, node_id):
    """Invalidate node and all nodes that depend on it"""
    # Find all nodes that have this node in their lineage
    affected = []
    for nid, attrs in graph.nodes(data=True):
        if node_id in attrs.get("lineage", []):
            affected.append(nid)
    return affected
```

### Pattern 3: Origin-Based Filtering
```python
from ctxvc.graph import filter_by_origin

# Exclude all user-provided nodes
user_nodes = filter_by_origin(graph, "user")
verified_nodes = [n for n in graph.nodes() if n not in user_nodes]
```

## Performance Characteristics

- **Storage**: Metadata adds ~100 bytes/node per snapshot
- **Computation**: Trust filtering is O(N), lineage tracing is O(N+E)
- **Scalability**: Tested with 1000+ nodes with full metadata

## Future Enhancements

1. **Trust Propagation**: Automatically compute trust from ancestors
2. **Lineage Visualization**: ASCII DAG or Mermaid export
3. **Metadata Search**: Query language for complex metadata filters
4. **Anomaly Detection**: Flag unusual trust/lineage patterns
5. **RDF Export**: Export with semantic annotations for knowledge bases

---

**See Also**: [GRAPH_EXAMPLES.md](GRAPH_EXAMPLES.md) for detailed usage examples.

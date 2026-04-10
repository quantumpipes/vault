# Knowledge Graph

Track entities, relationships, mentions, and backlinks across your vault. Every mutation creates an auditable VaultEvent.

## Quick Start

```python
from qp_vault import AsyncVault

vault = AsyncVault("./my-knowledge")
await vault._ensure_initialized()

# Create entities
alice = await vault.graph.create_node(
    name="Alice Chen",
    entity_type="person",
    properties={"role": "CTO", "department": "Engineering"},
    tags=["leadership", "founder"],
)

acme = await vault.graph.create_node(
    name="Acme Corp",
    entity_type="company",
    properties={"industry": "AI", "founded": "2020"},
)

# Connect them
edge = await vault.graph.create_edge(
    source_id=alice.id,
    target_id=acme.id,
    relation_type="works_at",
    weight=0.9,
)

# Search by name
results = await vault.graph.search_nodes("Alice")

# Traverse relationships
neighbors = await vault.graph.neighbors(alice.id, depth=2)

# Track where entities appear in documents
resource = await vault.add("Alice Chen leads engineering at Acme Corp.", name="team.md")
await vault.graph.track_mention(
    alice.id, resource.id,
    context_snippet="Alice Chen leads engineering",
)

# Find all documents mentioning an entity
backlinks = await vault.graph.get_backlinks(alice.id)

# Build context for LLM prompts
context = await vault.graph.context_for([alice.id, acme.id])
```

Sync interface works identically through `Vault` (wraps async calls automatically).

<!-- VERIFIED: graph/service.py:53-63, vault.py:253-257 -->

---

## Installation

```bash
pip install qp-vault              # Graph included (no extra deps)
pip install qp-vault[postgres]    # PostgreSQL backend (pg_trgm + recursive CTEs)
```

The graph subpackage uses only `pydantic` (already a base dependency). Both PostgreSQL and SQLite backends support graph operations out of the box.

---

## Availability

`vault.graph` returns a `GraphEngine` when the storage backend supports graphs. Both built-in backends (PostgreSQL and SQLite) do. Custom backends that don't implement `GraphStorageBackend` get `vault.graph = None`.

```python
if vault.graph is not None:
    node = await vault.graph.create_node(name="X", entity_type="thing")
```

<!-- VERIFIED: vault.py:253-257, protocols.py:200-247 -->

---

## Node CRUD

### create_node

```python
node = await vault.graph.create_node(
    name="Jane Doe",               # Required. Max 500 chars.
    entity_type="person",           # Required. Max 50 chars. Emergent, not prescribed.
    properties={"role": "engineer"},# Optional. Arbitrary JSON.
    tags=["vip"],                   # Optional. String array.
    primary_space_id=space_id,      # Optional. Home space for profile files.
    tenant_id=tenant_id,            # Optional. Auto-resolved from vault if locked.
)
```

Returns `GraphNode`. Slug auto-generated from name (`jane-doe`). Collisions append `-2`, `-3`, etc.

<!-- VERIFIED: graph/service.py:144-196 -->

### get_node / list_nodes / search_nodes

```python
node = await vault.graph.get_node(node_id)                      # By UUID, or None
nodes, total = await vault.graph.list_nodes(                     # Filtered list
    space_id=space_id, entity_type="person", limit=20, offset=0,
)
results = await vault.graph.search_nodes("quantum", limit=10)   # Trigram (PG) / FTS5 (SQLite)
```

<!-- VERIFIED: graph/service.py:198-268 -->

### update_node

```python
updated = await vault.graph.update_node(
    node.id,
    name="Jane Smith",             # Triggers slug regeneration
    properties={"role": "VP"},
    tags=["vip", "exec"],
)
```

Accepts: `name`, `entity_type`, `properties`, `tags`, `primary_space_id`. Other kwargs are silently ignored.

<!-- VERIFIED: graph/service.py:270-299 -->

### delete_node

```python
await vault.graph.delete_node(node.id)
```

Cascades: removes all edges, mentions, and space memberships for this node.

<!-- VERIFIED: graph/service.py:301-316 -->

---

## Edge CRUD

### create_edge

```python
edge = await vault.graph.create_edge(
    source_id=alice.id,
    target_id=acme.id,
    relation_type="works_at",       # Required.
    properties={"since": "2022"},   # Optional.
    weight=0.9,                     # 0.0-1.0. Default: 0.5.
    bidirectional=False,            # Default: False.
    source_resource_id=doc.id,      # Optional. Document that established this.
)
```

Self-edges (source == target) raise `ValueError`. Duplicate (source, target, relation_type) tuples are upserted on PostgreSQL and replaced on SQLite.

<!-- VERIFIED: graph/service.py:321-384 -->

### get_edges / update_edge / delete_edge

```python
edges = await vault.graph.get_edges(node.id, direction="outgoing")  # or "incoming", "both"
updated = await vault.graph.update_edge(edge.id, weight=0.8)
await vault.graph.delete_edge(edge.id)
```

<!-- VERIFIED: graph/service.py:386-432 -->

---

## Traversal

```python
neighbors = await vault.graph.neighbors(
    node.id,
    depth=2,                          # Max 3 (silently capped).
    relation_types=["works_at"],      # Optional filter.
    space_id=space_id,                # Optional filter.
)
for n in neighbors:
    print(f"{n.node_name} ({n.entity_type}) at depth {n.depth} via {n.relation_type}")
```

PostgreSQL uses a recursive CTE function. SQLite uses Python-side BFS. Both avoid cycles.

<!-- VERIFIED: graph/service.py:437-471 -->

---

## Mentions and Backlinks

```python
# Record a mention (upserts on node_id + resource_id)
await vault.graph.track_mention(
    node.id, resource.id,
    space_id=space_id,
    context_snippet="Alice presented the Q3 results",  # Max 500 chars.
)

# All resources mentioning an entity
backlinks = await vault.graph.get_backlinks(node.id, limit=50, offset=0)

# All entities in a resource
entities = await vault.graph.get_entities_in_resource(resource.id)
```

First mention increments `mention_count`. Re-mentioning the same entity in the same resource updates the snippet without double-counting.

<!-- VERIFIED: graph/service.py:525-583 -->

---

## Cross-Space Membership

Nodes have a primary space but can appear in additional spaces:

```python
await vault.graph.add_to_space(node.id, other_space_id)
await vault.graph.remove_from_space(node.id, other_space_id)
```

`list_nodes(space_id=...)` returns nodes from both the primary space and cross-space memberships.

<!-- VERIFIED: graph/service.py:587-603 -->

---

## Merge

Combine two nodes that represent the same entity:

```python
merged = await vault.graph.merge_nodes(keep_id=alice.id, merge_id=duplicate.id)
```

The merge operation:
1. Re-points all edges from `merge_id` to `keep_id` (skips duplicates)
2. Re-points all mentions (skips duplicates)
3. Transfers space memberships
4. Unions tags (deduplicated)
5. Merges properties (keep-node wins on conflicts)
6. Sums mention counts
7. Deletes the merged node

<!-- VERIFIED: graph/service.py:608-627 -->

---

## LLM Context

Build structured markdown context for injection into LLM system prompts:

```python
context = await vault.graph.context_for([alice.id, acme.id])
# Returns markdown with entity names, types, properties, tags, and relationships
```

<!-- VERIFIED: graph/service.py:474-520 -->

---

## Entity Detection

Detect known entities in text without LLM calls:

```python
from qp_vault.graph.detection import EntityDetector

detector = EntityDetector(vault.graph)
detected = await detector.detect("Alice presented at Acme's annual meeting")
for d in detected:
    print(f"{d.name} ({d.entity_type}) confidence={d.confidence}")
```

Loads up to 10,000 entity names into memory. Case-insensitive regex matching, longest match first. Optional fuzzy matching via `EntityResolver`:

```python
from qp_vault.graph.resolution import EntityResolver

resolver = EntityResolver(vault.graph)
detector = EntityDetector(vault.graph, entity_resolver=resolver)
detected = await detector.detect("Alice presented at ACME", fuzzy=True)
```

Caps: 50,000 char text input, 100 fuzzy candidates, 10,000 index size.

<!-- VERIFIED: graph/detection.py:29-45, 64-137 -->

---

## Knowledge Extraction

Extract entities and relationships from documents via LLM:

```python
from qp_vault.graph.extraction import KnowledgeExtractor
from qp_vault.graph.resolution import EntityResolver

async def chat_fn(messages, temperature):
    # Your LLM provider here
    return await llm.complete(messages, temperature=temperature)

extractor = KnowledgeExtractor(chat_fn=chat_fn)
graph = await extractor.extract(
    "Alice Chen is CTO of Acme Corp, which builds AI tools.",
    query="team overview",
)
print(f"Found {len(graph.entities)} entities, {len(graph.relationships)} relationships")

# Persist to the graph (resolves duplicates automatically)
resolver = EntityResolver(vault.graph)
extractor.set_graph_services(vault.graph, resolver)
resource = await vault.add("team-overview.md")
node_ids, edge_ids = await extractor.persist_to_graph(graph, resource_id=resource.id)
```

Input text is sanitized (NFKC normalization, HTML escaping, XML wrapping) before reaching the LLM. Output is validated: 200 entity cap, 500 relationship cap, type/length enforcement.

<!-- VERIFIED: graph/extraction.py:106-171, 292-330 -->

---

## Entity Resolution

Deduplicate entities using a three-stage cascade:

```python
from qp_vault.graph.resolution import EntityResolver

resolver = EntityResolver(vault.graph, similarity_threshold=0.6)

# Find existing or create new
node = await resolver.resolve_or_create("OpenAI", "company")

# Find by name across all types (for wikilinks)
node = await resolver.resolve_by_name("Alice Chen")
```

Stages: exact match (case-insensitive) -> FTS/trigram search -> create.

<!-- VERIFIED: graph/resolution.py:41-106 -->

---

## Wikilinks

Parse and resolve `[[Entity Name]]` syntax:

```python
from qp_vault.graph.wikilinks import parse_wikilinks, resolve_wikilinks

refs = parse_wikilinks("See [[Alice Chen]] and [[Acme Corp|Acme]] for details")
resolved = await resolve_wikilinks(refs, resolver)
for r in resolved:
    print(f"{r.name}: {'resolved' if r.resolved else 'unresolved'}")
```

Supports `[[Name]]` and `[[Name|Display Text]]`. Skips wikilinks inside code fences and inline code. Deduplicates by name (case-insensitive).

<!-- VERIFIED: graph/wikilinks.py:46-93, 96-134 -->

---

## Entity Materialization

Generate `profile.md` and `manifest.json` resources for entities:

```python
from qp_vault.graph.materialization import EntityMaterializer

materializer = EntityMaterializer(vault.graph, vault)
result = await materializer.materialize(alice.id)
print(result["profile_resource_id"], result["manifest_resource_id"])
```

Profile includes: properties table, tags, wikilinked relationships, mention context snippets, and metadata footer. Manifest is structured JSON with schema version, relationships, and timestamps.

<!-- VERIFIED: graph/materialization.py:35-78 -->

---

## Graph-Augmented Search

Boost search results for documents mentioning detected entities:

```python
results = await vault.search("quantum computing research", graph_boost=True)
```

When `graph_boost=True`: detects entities in the query, fetches their backlinks, and applies a 15% relevance boost to matching documents. Off by default. Best-effort: falls back to standard search on any failure.

<!-- VERIFIED: vault.py:1172-1188 -->

---

## Scan Orchestration

Batch-extract entities from all resources in a space:

```python
job = await vault.graph.scan(space_id, tenant_id=tenant_id)
print(f"Scan {job.id} status: {job.status}")

# Check progress
status = await vault.graph.get_scan(job.id)
```

Jobs track: status (`running`/`completed`/`failed`/`cancelled`), timestamps, summary counters, and error text.

<!-- VERIFIED: graph/service.py:656-711 -->

---

## Audit Events

Every mutation fires a `VaultEvent`. When a `CapsuleAuditor` is configured, these are sealed into the immutable audit chain.

| Operation | EventType |
|-----------|-----------|
| `create_node` | `ENTITY_CREATE` |
| `update_node` | `ENTITY_UPDATE` |
| `delete_node` | `ENTITY_DELETE` |
| `create_edge` | `EDGE_CREATE` |
| `delete_edge` | `EDGE_DELETE` |
| `merge_nodes` | `ENTITY_MERGE` |
| `track_mention` | `MENTION_TRACK` |
| `scan` | `SCAN_START` |

Subscribe to graph events:

```python
def on_graph_event(event):
    if event.event_type.value.startswith("entity_"):
        print(f"Graph: {event.event_type} {event.resource_name}")

vault.subscribe(on_graph_event)
```

<!-- VERIFIED: graph/service.py:90-112, enums.py:210-220 -->

---

## Backend Differences

| Capability | PostgreSQL | SQLite |
|-----------|-----------|--------|
| Node search | `similarity()` via pg_trgm (threshold 0.3) | FTS5 `MATCH` with rank scoring |
| Traversal | Recursive CTE function (`graph_neighbors`) | Python iterative BFS |
| Edge upsert | `ON CONFLICT ... DO UPDATE` | `INSERT OR REPLACE` |
| Mention upsert | `ON CONFLICT (node_id, resource_id) DO UPDATE` | `INSERT OR REPLACE` with manual check |
| Schema | `qp_vault.graph_*` (configurable via `graph_schema`) | Unqualified `graph_*` tables |
| Best for | Production (100k+ nodes) | Development and small deployments (<10k nodes) |

---

## Models

| Model | Key Fields |
|-------|------------|
| `GraphNode` | `id`, `name`, `slug`, `entity_type`, `properties`, `tags`, `mention_count` |
| `GraphEdge` | `source_node_id`, `target_node_id`, `relation_type`, `weight` (0.0-1.0) |
| `GraphMention` | `node_id`, `resource_id`, `context_snippet` (max 500 chars) |
| `NeighborResult` | `node_id`, `node_name`, `depth`, `relation_type`, `edge_weight` |
| `GraphScanJob` | `space_id`, `status`, `summary`, `error` |
| `DetectedEntity` | `name`, `entity_type`, `node_id`, `confidence` (0.0-1.0), `start`, `end` |

Import from `qp_vault.graph.models` or directly from `qp_vault.graph`:

```python
from qp_vault.graph import GraphNode, GraphEdge, GraphEngine
```

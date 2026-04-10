# Getting Started

Install qp-vault and have a governed knowledge store running in under 5 minutes.

## Install

```bash
pip install qp-vault
```

Zero config. SQLite backend, trust-weighted search, content-addressed storage, Merkle verification, Membrane screening, and RBAC built in.

For additional features:

```bash
pip install qp-vault[sqlite]         # Async SQLite (aiosqlite)
pip install qp-vault[postgres]       # PostgreSQL + pgvector hybrid search
pip install qp-vault[encryption]     # AES-256-GCM encryption at rest
pip install qp-vault[pq]             # ML-KEM-768 + ML-DSA-65 post-quantum crypto
pip install qp-vault[capsule]        # Cryptographic audit trail via qp-capsule
pip install qp-vault[docling]        # 25+ document formats (PDF, DOCX, PPTX, etc.)
pip install qp-vault[local]          # Local embeddings (sentence-transformers, air-gap)
pip install qp-vault[openai]         # OpenAI embeddings (cloud)
pip install qp-vault[integrity]      # Near-duplicate + contradiction detection (numpy)
pip install qp-vault[fastapi]        # 22+ REST API endpoints
pip install qp-vault[cli]            # vault command-line tool (15 commands)
pip install qp-vault[all]            # Everything
```

Combine extras with commas to install exactly what you need:

```bash
# Production API server with PostgreSQL and encryption
pip install qp-vault[postgres,encryption,pq,capsule,fastapi]

# Air-gapped deployment with local embeddings and CLI
pip install qp-vault[local,encryption,cli]

# Development with document processing and integrity checks
pip install qp-vault[docling,integrity,cli]
```

## Create a Vault

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")
```

Creates `./my-knowledge/` with SQLite database and audit log. No configuration required.

## Add Resources

```python
# From text
vault.add("Incident response: acknowledge within 15 minutes...",
          name="sop-incident.md", trust_tier="canonical")

# From a file
vault.add("path/to/report.pdf", trust_tier="working")

# With tenant isolation
vault.add("Tenant-specific content", tenant_id="site-123")

# Batch add
vault.add_batch(["doc1.md", "doc2.md", "doc3.md"], trust_tier="working")
```

Resources are automatically: chunked, hashed (SHA3-256), screened by Membrane, indexed, and audited.

## Search

```python
results = vault.search("incident response procedure")

for r in results:
    print(f"[{r.trust_tier.value}] {r.resource_name} (relevance={r.relevance:.3f})")
```

Results are deduplicated (one per resource), ranked by: `(vector + text) * trust * freshness * layer_boost`.

## Multi-Keyword Grep

```python
# Find documents where multiple concepts converge
results = vault.grep(["incident", "response", "P0", "escalation"])

for r in results:
    meta = r.explain_metadata
    print(f"{r.resource_name} — {len(meta['matched_keywords'])}/{4} keywords matched")
    print(f"  snippet: {meta['snippet']}")
```

Single-pass FTS5 query. Scored by keyword coverage (coord factor), text relevance, and term proximity. No embedder required.

<!-- VERIFIED: vault.py:1172-1285 — grep method -->

## Retrieve Content

```python
text = vault.get_content(resource.id)
print(text)
```

## Replace Content

```python
old, new = vault.replace(resource.id, "Updated policy v2 content")
# old.lifecycle = "superseded", new = active version
```

## Verify Integrity

```python
result = vault.verify()           # Full vault Merkle tree
result = vault.verify(resource.id) # Single resource
proof = vault.export_proof(resource.id)  # For auditors
```

## Health Score

```python
score = vault.health()
print(f"Overall: {score.overall}/100")

# Per-resource health
score = vault.health(resource.id)
```

## RBAC

```python
# Reader: search and verify only
vault = Vault("./knowledge", role="reader")

# Writer: add and modify
vault = Vault("./knowledge", role="writer")

# Admin: full access
vault = Vault("./knowledge", role="admin")
```

## Multi-Tenancy

```python
# Per-call tenant isolation
vault.add("content", tenant_id="site-123")
vault.search("query", tenant_id="site-123")

# Or lock the vault to a single tenant
vault = Vault("./knowledge", tenant_id="site-123")
```

## Knowledge Graph

Track entities, relationships, and mentions across your vault:

```python
# Create entities
alice = vault.graph.create_node(name="Alice", entity_type="person")
acme = vault.graph.create_node(name="Acme Corp", entity_type="company")

# Connect them
vault.graph.create_edge(source_id=alice.id, target_id=acme.id, relation_type="works_at")

# Track mentions in documents
resource = vault.add("Alice leads engineering at Acme Corp.", name="team.md")
vault.graph.track_mention(alice.id, resource.id, context_snippet="Alice leads engineering")

# Search and traverse
results = vault.graph.search_nodes("Alice")
neighbors = vault.graph.neighbors(alice.id, depth=2)
backlinks = vault.graph.get_backlinks(alice.id)
```

Works on both PostgreSQL and SQLite. See [Knowledge Graph](knowledge-graph.md) for extraction, detection, and wikilinks.

## CLI

```bash
pip install qp-vault[cli]

vault init ./knowledge
vault add report.pdf --trust canonical
vault search "revenue" --top-k 5
vault list --trust canonical
vault verify
vault health
vault status
```

15 commands. See [CLI Reference](cli.md).

## Next Steps

- [Knowledge Graph](knowledge-graph.md): Entities, relationships, extraction, detection
- [Trust Tiers](trust-tiers.md): How trust affects search ranking
- [Encryption](encryption.md): AES-256-GCM, ML-KEM-768, ML-DSA-65
- [RBAC](rbac.md): Reader/Writer/Admin roles
- [Membrane](membrane.md): Content screening
- [Multi-Tenancy](multi-tenancy.md): Tenant isolation
- [API Reference](api-reference.md): Complete SDK

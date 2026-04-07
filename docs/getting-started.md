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
          name="sop-incident.md", trust="canonical")

# From a file
vault.add("path/to/report.pdf", trust="working")

# With tenant isolation
vault.add("Tenant-specific content", tenant_id="site-123")

# Batch add
vault.add_batch(["doc1.md", "doc2.md", "doc3.md"], trust="working")
```

Resources are automatically: chunked, hashed (SHA3-256), screened by Membrane, indexed, and audited.

## Search

```python
results = vault.search("incident response procedure")

for r in results:
    print(f"[{r.trust_tier.value}] {r.resource_name} (relevance={r.relevance:.3f})")
```

Results are deduplicated (one per resource), ranked by: `(vector + text) * trust * freshness * layer_boost`.

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

- [Trust Tiers](trust-tiers.md): How trust affects search ranking
- [Encryption](encryption.md): AES-256-GCM, ML-KEM-768, ML-DSA-65
- [RBAC](rbac.md): Reader/Writer/Admin roles
- [Membrane](membrane.md): Content screening
- [Multi-Tenancy](multi-tenancy.md): Tenant isolation
- [API Reference](api-reference.md): Complete SDK

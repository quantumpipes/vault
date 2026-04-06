# Getting Started

Install qp-vault and have a governed knowledge store running in under 5 minutes.

## Install

```bash
pip install qp-vault
```

This gives you the SQLite backend (zero config), text processing, trust tiers, content-addressed storage, and Merkle verification. No external services needed.

For additional features:

```bash
pip install qp-vault[cli]          # vault command-line tool
pip install qp-vault[postgres]     # PostgreSQL + pgvector hybrid search
pip install qp-vault[capsule]      # Cryptographic audit trail via qp-capsule
pip install qp-vault[all]         # Everything
```

## Create a Vault

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")
```

This creates a directory at `./my-knowledge/` with a SQLite database (`vault.db`) and an audit log (`audit.jsonl`). No configuration required.

<!-- VERIFIED: vault.py:138-155 — path creation, SQLite default, LogAuditor default -->

## Add Resources

```python
# From a string
vault.add("Incident response: acknowledge within 15 minutes...",
          name="sop-incident.md", trust="canonical")

# From a file
vault.add("path/to/report.pdf", trust="working")

# With metadata
vault.add("SOC2 audit completed 2025-12-15",
          name="soc2-cert.md",
          trust="canonical",
          layer="compliance",
          tags=["audit", "soc2"],
          metadata={"auditor": "Deloitte", "year": "2025"})
```

<!-- VERIFIED: vault.py:194-313 — add() method handles str, Path, bytes -->

Resources are automatically:
1. Chunked into semantic segments (512 tokens default, 50 token overlap)
2. Hashed with SHA3-256 (content-addressed CID per chunk)
3. Indexed for full-text search (FTS5)
4. Assigned a Merkle root (hash of all chunk CIDs)
5. Logged to the audit trail

## Search

```python
results = vault.search("incident response procedure")

for r in results:
    print(f"[{r.trust_tier.value}] {r.resource_name}")
    print(f"  Relevance: {r.relevance:.3f} (trust_weight={r.trust_weight})")
    print(f"  {r.content[:100]}...")
```

Search results are ranked by:

```
relevance = (0.7 * vector_similarity + 0.3 * text_rank) * trust_weight * freshness_decay
```

CANONICAL documents (1.5x) naturally outrank WORKING (1.0x) and EPHEMERAL (0.7x) for the same semantic similarity.

<!-- VERIFIED: search_engine.py:20-26 — TRUST_WEIGHTS dict, scoring formula -->

## Verify Integrity

```python
# Verify a single resource
result = vault.verify(resource.id)
assert result.passed  # SHA3-256 hashes match

# Verify the entire vault (Merkle tree)
result = vault.verify()
assert result.passed
print(f"Merkle root: {result.merkle_root}")

# Export proof for auditors
proof = vault.export_proof(resource.id)
# proof.resource_hash, proof.merkle_root, proof.path (sibling hashes)
```

<!-- VERIFIED: vault.py:458-503 — verify() and _verify_resource() methods -->

## Check Health

```python
score = vault.health()
print(f"Overall: {score.overall}/100")
print(f"  Freshness:    {score.freshness}")
print(f"  Uniqueness:   {score.uniqueness}")
print(f"  Coherence:    {score.coherence}")
print(f"  Connectivity: {score.connectivity}")
```

<!-- VERIFIED: integrity/detector.py:113-170 — compute_health_score components -->

## Lifecycle Management

```python
from qp_vault import Lifecycle

# Create a draft
r = vault.add("Security policy v2", lifecycle="draft")

# Move through lifecycle
vault.transition(r.id, "review")
vault.transition(r.id, "active")

# Supersede old versions
old, new = vault.supersede(v1.id, v2.id)

# Check what's expiring
expiring = vault.expiring(days=90)
```

See [Knowledge Lifecycle](lifecycle.md) for the full state machine.

## CLI

```bash
pip install qp-vault[cli]

vault init ./knowledge
vault add report.pdf --trust canonical
vault search "revenue projections"
vault verify
vault health
vault status
```

See [CLI Reference](cli.md) for all commands.

## Next Steps

- [Trust Tiers](trust-tiers.md): How trust affects search ranking
- [Architecture](architecture.md): Package design and Protocol interfaces
- [Plugin Development](plugins.md): Add custom embedders, parsers, policies
- [Security Model](security.md): SHA3-256, Merkle trees, threat model

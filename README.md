# qp-vault

**The knowledge store where every read is verified and every write is auditable.**

[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-375%20passing-brightgreen.svg)](tests/)
[![Security](https://img.shields.io/badge/Security-100%2F100-brightgreen.svg)](docs/security.md)

qp-vault is not a vector database. It is a **governed knowledge store** for autonomous organizations. Every document has a trust tier that affects search ranking. Every chunk has a SHA3-256 content ID. Every mutation creates an audit record. The entire vault is verifiable via Merkle tree in under a second.

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")
vault.add("quarterly-report.pdf", trust="canonical")
results = vault.search("Q3 revenue projections")
print(results[0].content, results[0].trust_tier)  # trust_weight=1.5x
```

```bash
pip install qp-vault
```

---

## Why qp-vault?

Vector databases store embeddings. RAG frameworks build pipelines. Neither answers the questions that matter in regulated, high-stakes environments:

| Question | ChromaDB | Qdrant | Weaviate | **qp-vault** |
|----------|----------|--------|----------|--------------|
| **Who vouched for this document?** | -- | -- | -- | Trust tiers |
| **Has this been tampered with?** | -- | -- | -- | SHA3-256 CIDs + Merkle |
| **What was our policy on March 15?** | -- | -- | -- | Temporal validity |
| **Can we prove compliance to auditors?** | -- | -- | -- | Capsule audit trail |
| **Is this SOP still current?** | -- | -- | -- | Knowledge lifecycle |
| **Does this work air-gapped?** | Partial | Partial | Partial | **Native** |

---

## Install

```bash
pip install qp-vault
```

That's it. SQLite backend, trust-weighted search, content-addressed storage, Merkle verification. Zero external services.

| Extra | Adds | Install |
|-------|------|---------|
| `[postgres]` | PostgreSQL + pgvector hybrid search | `pip install qp-vault[postgres]` |
| `[docling]` | 25+ format processing (PDF, DOCX, etc.) | `pip install qp-vault[docling]` |
| `[capsule]` | Cryptographic audit trail ([qp-capsule](https://github.com/quantumpipes/capsule)) | `pip install qp-vault[capsule]` |
| `[encryption]` | AES-256-GCM + ML-KEM-768 at rest | `pip install qp-vault[encryption]` |
| `[integrity]` | Staleness, duplicate, orphan detection | `pip install qp-vault[integrity]` |
| `[fastapi]` | REST API (15+ endpoints) | `pip install qp-vault[fastapi]` |
| `[cli]` | `vault` command-line tool | `pip install qp-vault[cli]` |
| `[all]` | Everything | `pip install qp-vault[all]` |

---

## Trust Tiers

Every resource has a trust tier. Trust is not metadata; it directly affects search ranking.

| Tier | Weight | Behavior |
|------|--------|----------|
| **CANONICAL** | 1.5x | Immutable. Official SOPs, approved policies. |
| **WORKING** | 1.0x | Default. Drafts, in-progress docs. |
| **EPHEMERAL** | 0.7x | Temporary. Meeting notes. Auto-archives after 90 days. |
| **ARCHIVED** | 0.25x | Historical. Superseded versions. |

A CANONICAL document with 0.6 similarity outranks a WORKING document with 0.8:

```
CANONICAL: 0.6 * 1.5 = 0.90  <-- wins
WORKING:   0.8 * 1.0 = 0.80
```

```python
vault.add("SOP: Incident Response", trust="canonical")   # Always surfaces first
vault.add("Draft: New Onboarding", trust="working")       # Baseline
vault.add("Standup Notes 03/15", trust="ephemeral")        # Auto-archives
```

---

## Knowledge Lifecycle

Documents are not static. They have lifecycles.

```
DRAFT --> REVIEW --> ACTIVE --> SUPERSEDED --> ARCHIVED
                       |
                    EXPIRED (auto)
```

```python
# Create and advance
r = vault.add("Security Policy v2", lifecycle="draft")
vault.transition(r.id, "review", reason="Ready for security team")
vault.transition(r.id, "active")

# Supersede old versions
old, new = vault.supersede(v1_id, v2_id)
chain = vault.chain(v1_id)  # [v1, v2, v3]

# Point-in-time queries
results = vault.search("incident response", as_of=date(2024, 3, 15))

# Expiration alerts
expiring = vault.expiring(days=90)
```

---

## Memory Layers

Three semantic partitions with per-layer defaults:

| Layer | Default Trust | Search Boost | Reads Audited |
|-------|--------------|-------------|---------------|
| **OPERATIONAL** | WORKING | 1.5x | No |
| **STRATEGIC** | CANONICAL | 1.0x | No |
| **COMPLIANCE** | CANONICAL | 1.0x | **Yes** |

```python
from qp_vault import MemoryLayer

ops = vault.layer(MemoryLayer.OPERATIONAL)       # SOPs, runbooks
await ops.add("deploy-runbook.md")                # trust=WORKING auto

strategic = vault.layer(MemoryLayer.STRATEGIC)    # ADRs, decisions
compliance = vault.layer(MemoryLayer.COMPLIANCE)  # Audit evidence, certs
await compliance.search("SOC2")                    # This search is logged
```

---

## Verification

Content-addressed storage. SHA3-256 CID per chunk. Merkle root per vault.

```python
# Verify a single resource
result = vault.verify(resource_id)
assert result.passed

# Verify entire vault
result = vault.verify()
print(result.merkle_root)  # Changes if any content is modified

# Export proof for auditors
proof = vault.export_proof(resource_id)
# Contains: resource_hash, merkle_root, sibling hashes along path
```

---

## Health Scoring

Composite integrity assessment. Catches problems before they matter.

```python
score = vault.health()
print(f"{score.overall}/100")
#   freshness:    92.0  (are documents current?)
#   uniqueness:   100.0 (no duplicates?)
#   coherence:    80.0  (no contradictions?)
#   connectivity: 70.0  (are docs organized?)
```

---

## Plugin System

Extend with custom embedders, parsers, and policies. Air-gap mode: drop `.py` files in a directory.

```python
from qp_vault.plugins import embedder, parser

@embedder("my-model")
class MyEmbedder:
    dimensions = 768
    async def embed(self, texts):
        return my_model.encode(texts)

@parser("dicom")
class DicomParser:
    supported_extensions = {".dcm"}
    async def parse(self, path):
        return ParseResult(text=extract_dicom(path))
```

Three discovery methods: explicit registration, entry_points (pip packages), or `--plugins-dir` (air-gap).

---

## CLI

```bash
vault init ./knowledge
vault add report.pdf --trust canonical
vault search "revenue projections" --top-k 5
vault inspect <resource-id>
vault verify
vault health
vault status
```

---

## FastAPI

One line to add 15+ REST endpoints:

```python
from qp_vault.integrations.fastapi_routes import create_vault_router

router = create_vault_router(vault)
app.include_router(router, prefix="/v1/vault")
```

---

## Security

| Layer | Implementation |
|-------|---------------|
| Content hashing | SHA3-256 (FIPS 202) |
| Audit signatures | Ed25519 + ML-DSA-65 via [qp-capsule](https://github.com/quantumpipes/capsule) |
| Encryption at rest | AES-256-GCM + ML-KEM-768 |
| SQL injection | Parameterized queries only |
| Input validation | Enum checks, name sanitization, tag/metadata limits |
| FTS injection | Query sanitizer strips operators |
| Path traversal | Name components stripped, null bytes removed |
| Deprecated crypto | MD5, SHA1, DES, RSA: **never used** |

100/100 security score. Full threat model in [docs/security.md](docs/security.md).

---

## Part of the Quantum Pipes Stack

```
qp-capsule    qp-vault      qp-conduit    qp-tunnel
Audit         Knowledge     Infra         Access
Protocol      Store         Mgmt          Control
```

Each independently useful. Together, the governed AI platform for autonomous organizations.

---

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Install to first search in 5 minutes |
| [Architecture](docs/architecture.md) | Package structure, Protocols, data flow |
| [API Reference](docs/api-reference.md) | Complete Python SDK |
| [Trust Tiers](docs/trust-tiers.md) | How trust affects search ranking |
| [Lifecycle](docs/lifecycle.md) | State machine, supersession, temporal validity |
| [Memory Layers](docs/memory-layers.md) | OPERATIONAL, STRATEGIC, COMPLIANCE |
| [Plugins](docs/plugins.md) | Custom embedders, parsers, policies |
| [Security](docs/security.md) | Threat model, crypto, input validation |
| [CLI](docs/cli.md) | All commands and options |
| [FastAPI](docs/fastapi.md) | REST endpoints and integration |

---

## Development

```bash
git clone https://github.com/quantumpipes/vault.git
cd vault
make install
make test-all   # lint + typecheck + 375 tests
```

---

## License

[Apache License 2.0](LICENSE)

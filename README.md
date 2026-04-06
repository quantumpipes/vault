# qp-vault

**Governed knowledge store for autonomous organizations.**

Every fact has provenance. Every read is verified. Every write is auditable.

Python 3.11+ | Apache 2.0 | 375+ tests | 100/100 security score

---

## Install

```bash
pip install qp-vault
```

| Extra | What it adds | Install |
|-------|-------------|---------|
| (base) | SQLite, basic search, trust tiers, Merkle verification | `pip install qp-vault` |
| `[postgres]` | PostgreSQL + pgvector hybrid search | `pip install qp-vault[postgres]` |
| `[docling]` | 25+ format document processing (PDF, DOCX, etc.) | `pip install qp-vault[docling]` |
| `[capsule]` | Cryptographic audit trail via qp-capsule | `pip install qp-vault[capsule]` |
| `[encryption]` | AES-256-GCM + ML-KEM-768 at-rest encryption | `pip install qp-vault[encryption]` |
| `[integrity]` | Staleness, duplicate, orphan detection | `pip install qp-vault[integrity]` |
| `[fastapi]` | Ready-made REST API routes | `pip install qp-vault[fastapi]` |
| `[cli]` | `vault` command-line tool | `pip install qp-vault[cli]` |
| `[all]` | Everything | `pip install qp-vault[all]` |

---

## Quick Start

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")
vault.add("quarterly-report.pdf", trust="canonical")
results = vault.search("Q3 revenue projections")
print(results[0].content, results[0].trust_tier)
```

---

## Trust Tiers

Every resource has a trust tier that affects search ranking:

| Tier | Weight | Purpose |
|------|--------|---------|
| **CANONICAL** | 1.5x | Immutable, authoritative. Official SOPs, approved policies. |
| **WORKING** | 1.0x | Editable, default. Drafts, in-progress documents. |
| **EPHEMERAL** | 0.7x | Temporary. Meeting notes. Auto-archived after 90 days. |
| **ARCHIVED** | 0.25x | Historical. Superseded versions, old policies. |

```python
vault.add("sop-incident-response.md", trust="canonical")   # 1.5x boost in search
vault.add("draft-onboarding.md", trust="working")           # Baseline
vault.add("meeting-notes-0315.md", trust="ephemeral")       # 0.7x, auto-archives
```

Search formula: `relevance = (0.7 * vector_sim + 0.3 * text_rank) * trust_weight * freshness_decay`

---

## Knowledge Lifecycle

```
DRAFT --> REVIEW --> ACTIVE --> SUPERSEDED --> ARCHIVED
                       |
                    EXPIRED (auto when valid_until passes)
```

```python
# Lifecycle transitions
vault.transition(resource_id, "review")
vault.transition(resource_id, "active")

# Supersession chains
old, new = vault.supersede(v1_id, v2_id)
chain = vault.chain(v1_id)  # [v1, v2, v3, ...]

# Point-in-time queries
results = vault.search("incident response", as_of=date(2024, 3, 15))

# Expiration alerts
expiring = vault.expiring(days=90)
```

---

## Memory Layers

Three semantic partitions with per-layer defaults:

```python
from qp_vault import MemoryLayer

# OPERATIONAL: SOPs, runbooks (trust=WORKING, boost=1.5x)
ops = vault.layer(MemoryLayer.OPERATIONAL)
await ops.add("deploy-runbook.md")

# STRATEGIC: Decisions, ADRs (trust=CANONICAL)
strategic = vault.layer(MemoryLayer.STRATEGIC)
await strategic.add("adr-001-postgres.md")

# COMPLIANCE: Audit evidence (trust=CANONICAL, reads audited, permanent retention)
compliance = vault.layer(MemoryLayer.COMPLIANCE)
await compliance.add("soc2-audit-2025.pdf")
```

---

## Verification

Content-addressed storage with SHA3-256 CIDs and Merkle tree verification.

```python
# Verify a single resource
result = vault.verify(resource_id)
assert result.passed

# Verify the entire vault (Merkle root)
result = vault.verify()
assert result.passed
print(result.merkle_root)

# Export cryptographic proof for auditors
proof = vault.export_proof(resource_id)
# Contains: resource_hash, merkle_root, path (siblings), leaf_index
```

---

## Health Scoring

Composite integrity assessment (0-100):

```python
score = vault.health()
print(score.overall)        # 85.0
print(score.freshness)      # 92.0  (are documents current?)
print(score.uniqueness)     # 100.0 (no duplicates?)
print(score.coherence)      # 80.0  (no contradictions?)
print(score.connectivity)   # 70.0  (are docs organized?)
```

---

## Plugin System

Extend with custom embedders, parsers, and policies:

```python
from qp_vault.plugins import embedder, parser

@embedder("my-model")
class MyEmbedder:
    dimensions = 768
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return my_model.encode(texts)

@parser("dicom")
class DicomParser:
    supported_extensions = {".dcm"}
    async def parse(self, path):
        return ParseResult(text=extract_dicom(path))
```

Air-gap mode: drop .py plugin files in `--plugins-dir`, no `pip install` needed.

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
vault expiring --days 90
```

---

## FastAPI Integration

```python
from qp_vault import AsyncVault
from qp_vault.integrations.fastapi_routes import create_vault_router

vault = AsyncVault("./knowledge")
router = create_vault_router(vault)
app.include_router(router, prefix="/v1/vault")
```

Provides 15+ endpoints: resources CRUD, search, verify, health, lifecycle, proof export.

---

## What Makes It Different

qp-vault is not a vector database. It is a **governed knowledge store**.

| Capability | ChromaDB | Qdrant | Weaviate | **qp-vault** |
|------------|----------|--------|----------|--------------|
| Document-level trust tiers | No | No | No | **Yes** |
| Cryptographic audit trail | No | No | No | **Yes** |
| Content-addressed storage | No | No | No | **Yes** |
| Knowledge lifecycle management | No | No | No | **Yes** |
| Temporal validity (point-in-time) | No | No | No | **Yes** |
| Post-quantum encryption | No | No | No | **Yes** |
| Air-gap first | Partial | Partial | Partial | **Yes** |
| Integrity verification on read | No | No | No | **Yes** |
| Memory layers | No | No | No | **Yes** |
| Plugin system (air-gap) | No | No | No | **Yes** |

---

## Part of the Quantum Pipes Stack

```
qp-capsule  |  qp-vault   |  qp-conduit  |  qp-tunnel
Audit       |  Knowledge  |  Infra       |  Access
Protocol    |  Store      |  Mgmt        |  Control
```

Each independently useful. Together, they form the governed AI platform for autonomous organizations.

---

## Development

```bash
git clone https://github.com/quantumpipes/vault.git
cd vault
make install    # pip install -e ".[sqlite,cli,fastapi,integrity,dev]"
make test       # pytest with coverage
make lint       # ruff
make typecheck  # mypy
make test-all   # lint + typecheck + test
```

---

## License

Apache 2.0. See [LICENSE](LICENSE).

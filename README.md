<div align="center">

# qp-vault

**The governed knowledge store for autonomous organizations.**

Every document has a trust tier that weights search results. Every chunk has a SHA3-256 content ID. Every mutation is auditable. The entire vault is verifiable via Merkle tree. Air-gap native.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/Tests-448_passing-brightgreen.svg)](tests/)
[![Crypto](https://img.shields.io/badge/Crypto-SHA3--256%20%C2%B7%20Ed25519-purple.svg)](#security)

</div>

---

## The Architecture

A Vault is a governed store of knowledge resources. Each resource is chunked, hashed, trust-classified, and indexed for hybrid search. The trust tier directly affects which results surface first.

```
┌─────────────────────────────────────────────────────────────┐
│                          VAULT                              │
├──────────────┬──────────────────────────────────────────────┤
│  INGEST      │  Parse → Chunk → SHA3-256 CID → Embed → Store│
│  GOVERN      │  Trust tiers · Lifecycle · Data classification│
│  RETRIEVE    │  Hybrid search · Trust-weighted · Time-travel │
│  VERIFY      │  Merkle tree · CID per chunk · Proof export  │
│  AUDIT       │  Every write → VaultEvent → Capsule (opt.)   │
├──────────────┴──────────────────────────────────────────────┤
│  Trust weights: CANONICAL 1.5x · WORKING 1.0x · EPHEMERAL 0.7x│
│  SHA3-256 content IDs · Merkle root · Ed25519+ML-DSA-65 audit │
└─────────────────────────────────────────────────────────────┘
```

Knowledge is not static. Resources move through a lifecycle (DRAFT, REVIEW, ACTIVE, SUPERSEDED, EXPIRED, ARCHIVED), organized into memory layers (OPERATIONAL, STRATEGIC, COMPLIANCE), and verified cryptographically on every read.

*Knowledge that can't be verified can't be trusted.*

---

## Why qp-vault

Vector databases store embeddings and return them by similarity. When something goes wrong, or when a regulator asks "was this the current policy at the time?", similarity search is not enough.

qp-vault solves three problems that vector databases do not:

**1. Trust-weighted retrieval.**
Every resource has a trust tier (CANONICAL, WORKING, EPHEMERAL, ARCHIVED) that multiplies its search relevance. A CANONICAL SOP at 0.6 similarity outranks a WORKING draft at 0.8 similarity. This is not metadata filtering; it is a scoring function that ensures authoritative knowledge surfaces first, every time, without manual curation.

**2. Cryptographic content integrity.**
Every chunk receives a SHA3-256 content ID at ingest. Every resource receives a Merkle root over its chunk CIDs. The entire vault has a root hash. Any modification to any chunk, in any resource, changes the vault's Merkle root. Auditors can verify a single resource without downloading the vault, using an exported Merkle proof. No trust in the storage layer is required.

**3. Knowledge lifecycle with temporal validity.**
Resources have lifecycles (DRAFT to ACTIVE to SUPERSEDED to ARCHIVED) with temporal validity windows. Point-in-time queries answer "what was our policy on March 15, 2024?" by returning only resources that were ACTIVE at that date. Supersession chains link v1 to v2 to v3 with cryptographic pointers. Expired resources auto-transition. None of this exists in any vector database.

---

## Content Addressing

Every chunk is hashed with SHA3-256 and assigned a content ID:

```
vault://sha3-256/4cb02d65a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef12
```

Every resource receives a Merkle root computed over its sorted chunk CIDs. The vault itself has a root hash over all resource hashes:

```
                    Vault Merkle Root
                    /               \
         Resource A Root      Resource B Root
         /          \              |
  hash(c1+c2)    hash(c3+c4)    hash(c5)
   /      \        /      \       |
CID(c1) CID(c2) CID(c3) CID(c4) CID(c5)
```

Identical content always produces the same CID. Modified content always produces a different root. Auditors verify a single resource via Merkle proof without downloading the vault.

---

## Trust Tiers

Trust is not metadata. It is a scoring function.

| Tier | Weight | Freshness Half-Life | Behavior |
|------|--------|---------------------|----------|
| **CANONICAL** | 1.5x | 365 days | Immutable. Official SOPs, approved policies. |
| **WORKING** | 1.0x | 180 days | Default. Drafts, in-progress documents. |
| **EPHEMERAL** | 0.7x | 30 days | Temporary. Meeting notes. Auto-archives after TTL. |
| **ARCHIVED** | 0.25x | 730 days | Historical. Superseded versions. |

Search ranking formula:

```
relevance = (0.7 × vector_similarity + 0.3 × text_rank) × trust_weight × freshness_decay
```

Where `freshness_decay = exp(-age_days / half_life × ln2)`. A 180-day-old WORKING document retains 50% freshness. A CANONICAL document of the same age retains 70%.

---

## Knowledge Lifecycle

```
DRAFT ──→ REVIEW ──→ ACTIVE ──→ SUPERSEDED ──→ ARCHIVED
                        │
                     EXPIRED (auto when valid_until passes)
                        │
                     ACTIVE (re-activate)
```

Supersession creates a linked chain. Point-in-time search returns historically correct results.

```python
vault.transition(r.id, "review", reason="Ready for security team")
vault.transition(r.id, "active")

old, new = vault.supersede(v1_id, v2_id)        # v1 → SUPERSEDED, linked to v2
chain = vault.chain(v1_id)                        # [v1, v2, v3, ...]
results = vault.search("policy", as_of=date(2024, 3, 15))  # Time-travel
expiring = vault.expiring(days=90)                # What's about to expire?
```

---

## Install

```bash
pip install qp-vault
```

| Command | What You Get | Dependencies |
|---|---|---|
| `pip install qp-vault` | SQLite, trust search, CAS, Merkle, lifecycle | **1** (pydantic) |
| `pip install qp-vault[postgres]` | + PostgreSQL + pgvector hybrid search | + sqlalchemy, asyncpg, pgvector |
| `pip install qp-vault[capsule]` | + Cryptographic audit trail | + [qp-capsule](https://github.com/quantumpipes/capsule) |
| `pip install qp-vault[docling]` | + 25+ format document processing (PDF, DOCX, etc.) | + docling |
| `pip install qp-vault[encryption]` | + AES-256-GCM encryption at rest | + cryptography, pynacl |
| `pip install qp-vault[local]` | + Local embeddings (sentence-transformers, air-gap safe) | + sentence-transformers |
| `pip install qp-vault[openai]` | + OpenAI embeddings (cloud) | + openai |
| `pip install qp-vault[fastapi]` | + REST API (15+ endpoints) | + fastapi |
| `pip install qp-vault[cli]` | + `vault` command-line tool | + typer, rich |
| `pip install qp-vault[all]` | Everything | All of the above |

---

## Quick Start

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")

# Add with trust tiers
vault.add("Incident response: acknowledge within 15 minutes...",
          name="sop-incident.md", trust="canonical")
vault.add("Draft proposal for new onboarding process...",
          name="draft-onboard.md", trust="working")

# Trust-weighted search
results = vault.search("incident response")
# CANONICAL surfaces first (1.5x), even at lower raw similarity

# Verify integrity
result = vault.verify()
print(result.merkle_root)  # Changes if any content is modified

# Export proof for auditors
proof = vault.export_proof(resource_id)
```

### Memory Layers

```python
from qp_vault import MemoryLayer

ops = vault.layer(MemoryLayer.OPERATIONAL)        # SOPs, runbooks (boost=1.5x)
strategic = vault.layer(MemoryLayer.STRATEGIC)     # ADRs, decisions (trust=CANONICAL)
compliance = vault.layer(MemoryLayer.COMPLIANCE)   # Audit evidence (reads audited)

await ops.add("deploy-runbook.md")                 # Layer defaults auto-applied
await compliance.search("SOC2")                     # This search is logged
```

### Health Scoring

```python
score = vault.health()
# score.overall:      85.0/100
# score.freshness:    92.0  (are documents current?)
# score.uniqueness:   100.0 (no duplicates?)
# score.coherence:    80.0  (no contradictions?)
# score.connectivity: 70.0  (are docs organized?)
```

### Plugin System

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

Three discovery methods: explicit registration, entry_points (pip packages), or `--plugins-dir` (air-gap: drop `.py` files, no install needed).

### CLI

```bash
vault init ./knowledge
vault add report.pdf --trust canonical
vault search "revenue projections" --top-k 5
vault inspect <resource-id>
vault verify
vault health
vault status
```

Exit codes: `0` = pass, `1` = fail. Designed for CI: `vault verify && deploy`.

### FastAPI

```python
from qp_vault.integrations.fastapi_routes import create_vault_router

router = create_vault_router(vault)
app.include_router(router, prefix="/v1/vault")
# 15+ endpoints: resources CRUD, search, verify, health, lifecycle, proof
```

---

## Security

| Layer | Algorithm | Standard | Purpose |
|---|---|---|---|
| Content integrity | SHA3-256 | FIPS 202 | Tamper-evident CIDs and Merkle roots |
| Audit signatures | Ed25519 + ML-DSA-65 | FIPS 186-5, FIPS 204 | Via [qp-capsule](https://github.com/quantumpipes/capsule) (optional) |
| Encryption at rest | AES-256-GCM | FIPS 197 | `pip install qp-vault[encryption]` |
| Search integrity | Parameterized SQL | -- | No string interpolation, FTS5 sanitized |
| Input validation | Pydantic + custom | -- | Enum checks, name/tag/metadata limits |

No deprecated cryptography. No runtime network dependencies. Air-gapped operation supported. 100/100 security score. Full threat model in [docs/security.md](docs/security.md).

---

## Part of the Quantum Pipes Stack

| Package | Purpose | Install |
|---|---|---|
| **[qp-capsule](https://github.com/quantumpipes/capsule)** | Cryptographic audit protocol | `pip install qp-capsule` |
| **qp-vault** | Governed knowledge store | `pip install qp-vault` |
| **qp-conduit** | Infrastructure management | Shell toolkit |
| **qp-tunnel** | Encrypted remote access | Shell toolkit |

Each independently useful. Together, the governed AI platform for autonomous organizations.

---

## Documentation

| Document | Audience |
|---|---|
| [Getting Started](docs/getting-started.md) | Developers |
| [Architecture](docs/architecture.md) | Developers, Architects |
| [API Reference](docs/api-reference.md) | Developers |
| [Trust Tiers](docs/trust-tiers.md) | Developers, Product |
| [Knowledge Lifecycle](docs/lifecycle.md) | Developers, Compliance |
| [Memory Layers](docs/memory-layers.md) | Developers, Architects |
| [Plugin Development](docs/plugins.md) | SDK Authors |
| [Security Model](docs/security.md) | CISOs, Security Teams |
| [CLI Reference](docs/cli.md) | DevOps, Developers |
| [FastAPI Integration](docs/fastapi.md) | Backend Developers |

---

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Bug fixes with tests, new plugins (embedders, parsers, policies), and documentation improvements are welcome.

## License

[Apache License 2.0](./LICENSE).

---

<div align="center">

*Knowledge that can't be verified can't be trusted.*

An open-source governed knowledge store

[Documentation](docs/) · [Security Policy](./SECURITY.md) · [Changelog](./CHANGELOG.md)

Copyright 2026 [Quantum Pipes Technologies, LLC](https://quantumpipes.com)

</div>

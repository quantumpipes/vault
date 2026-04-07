<div align="center">

# QP Vault

**The governed knowledge store for autonomous organizations.**

Every document has a trust tier that weights search results. Every chunk has a SHA3-256 content ID. Every mutation is auditable. The entire vault is verifiable via Merkle tree. Content is screened by a Membrane before indexing. Access is controlled by RBAC. Air-gap native. Post-quantum ready.

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Tests](https://img.shields.io/badge/Tests-520_passing-brightgreen.svg)](tests/)
[![Crypto](https://img.shields.io/badge/Crypto-SHA3--256%20%C2%B7%20AES--256--GCM%20%C2%B7%20ML--KEM--768%20%C2%B7%20ML--DSA--65-purple.svg)](#security)

</div>

---

## The Architecture

A Vault is a governed store of knowledge resources. Each resource is screened by the Membrane, chunked, hashed, trust-classified, and indexed for hybrid search. RBAC controls who can read, write, or administer.

```
┌─────────────────────────────────────────────────────────────────┐
│                          VAULT                                  │
├──────────────┬──────────────────────────────────────────────────┤
│  RBAC        │  READER · WRITER · ADMIN permission matrix       │
│  MEMBRANE    │  Innate scan → Release gate → Index/Quarantine   │
│  INGEST      │  Parse → Chunk → SHA3-256 CID → Embed → Store    │
│  GOVERN      │  Trust tiers · Lifecycle · Data classification   │
│  RETRIEVE    │  Hybrid search · Trust-weighted · Time-travel    │
│  VERIFY      │  Merkle tree · CID per chunk · Proof export      │
│  AUDIT       │  Every write → VaultEvent → Capsule (opt.)       │
│  ENCRYPT     │  AES-256-GCM · ML-KEM-768 · ML-DSA-65            │
├──────────────┴──────────────────────────────────────────────────┤
│  Trust weights: CANONICAL 1.5x · WORKING 1.0x · EPHEMERAL 0.7x  │
│  FIPS 202 · FIPS 197 · FIPS 203 · FIPS 204                      │
└─────────────────────────────────────────────────────────────────┘
```

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
relevance = (0.7 × vector_similarity + 0.3 × text_rank) × trust_weight × freshness_decay × layer_boost
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
| `pip install qp-vault` | SQLite, trust search, CAS, Merkle, lifecycle, Membrane, RBAC | **1** (pydantic) |
| `pip install qp-vault[postgres]` | + PostgreSQL + pgvector hybrid search | + sqlalchemy, asyncpg, pgvector |
| `pip install qp-vault[encryption]` | + AES-256-GCM encryption at rest | + cryptography, pynacl |
| `pip install qp-vault[pq]` | + ML-KEM-768 + ML-DSA-65 post-quantum crypto | + liboqs-python |
| `pip install qp-vault[capsule]` | + Cryptographic audit trail | + [qp-capsule](https://github.com/quantumpipes/capsule) |
| `pip install qp-vault[docling]` | + 25+ format document processing (PDF, DOCX, etc.) | + docling |
| `pip install qp-vault[local]` | + Local embeddings (sentence-transformers, air-gap safe) | + sentence-transformers |
| `pip install qp-vault[openai]` | + OpenAI embeddings (cloud) | + openai |
| `pip install qp-vault[integrity]` | + Near-duplicate + contradiction detection | + numpy |
| `pip install qp-vault[fastapi]` | + REST API (22+ endpoints) | + fastapi |
| `pip install qp-vault[cli]` | + `vault` command-line tool (15 commands) | + typer, rich |
| `pip install qp-vault[all]` | Everything | All of the above |

Combine extras with commas:

```bash
pip install qp-vault[postgres,encryption,pq,capsule,fastapi]   # Production API server
pip install qp-vault[local,encryption,cli]                       # Air-gapped deployment
pip install qp-vault[docling,integrity,cli]                      # Development
```

---

## Quick Start

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")

# Add with trust tiers
vault.add("Incident response: acknowledge within 15 minutes...",
          name="sop-incident.md", trust="canonical")

# Trust-weighted search (deduplicated, with freshness decay)
results = vault.search("incident response")

# Retrieve full content
text = vault.get_content(results[0].resource_id)

# Replace content (atomic: creates new version, supersedes old)
old, new = vault.replace(resource_id, "Updated policy v2 content")

# Verify integrity
result = vault.verify()
print(result.merkle_root)

# Export proof for auditors
proof = vault.export_proof(resource_id)
```

### Multi-Tenancy

```python
vault.add("content", tenant_id="site-123")
vault.search("query", tenant_id="site-123")      # Scoped to tenant

# Or lock the vault to a single tenant
vault = Vault("./knowledge", tenant_id="site-123")
```

### RBAC

```python
vault = Vault("./knowledge", role="reader")       # Search, get, verify only
vault = Vault("./knowledge", role="writer")       # + add, update, delete
vault = Vault("./knowledge", role="admin")        # + export, import, config
```

### Batch Import

```python
resources = vault.add_batch(["doc1.md", "doc2.md", "doc3.md"], trust="working")
```

### Memory Layers

```python
from qp_vault import MemoryLayer

ops = vault.layer(MemoryLayer.OPERATIONAL)        # SOPs, runbooks (boost=1.5x)
strategic = vault.layer(MemoryLayer.STRATEGIC)     # ADRs, decisions (trust=CANONICAL)
compliance = vault.layer(MemoryLayer.COMPLIANCE)   # Audit evidence (reads audited)
```

### Health Scoring

```python
score = vault.health()                # Vault-wide (0-100)
score = vault.health(resource.id)     # Per-resource
```

### Content Screening (Membrane)

Content is screened before indexing. Prompt injection, jailbreak, XSS, and code injection attempts are quarantined.

```python
vault.add("ignore all previous instructions")  # Quarantined automatically
```

### Plugin System

```python
from qp_vault.plugins import embedder, parser

@embedder("my-model")
class MyEmbedder:
    dimensions = 768
    async def embed(self, texts):
        return my_model.encode(texts)
```

Three discovery methods: explicit registration, entry_points, or `--plugins-dir` (air-gap).

### Encryption

```python
from qp_vault.encryption import AESGCMEncryptor, HybridEncryptor

# Classical
enc = AESGCMEncryptor()
ciphertext = enc.encrypt(b"secret")

# Post-quantum hybrid (ML-KEM-768 + AES-256-GCM)
enc = HybridEncryptor()
pub, sec = enc.generate_keypair()
ciphertext = enc.encrypt(b"classified", pub)
```

### Event Streaming

```python
from qp_vault.streaming import VaultEventStream

stream = VaultEventStream()
vault = AsyncVault("./knowledge", auditor=stream)

async for event in stream.subscribe():
    print(f"{event.event_type}: {event.resource_name}")
```

### Import / Export

```python
await vault.export_vault("backup.json")
await vault.import_vault("backup.json")
```

### CLI

```bash
vault init ./knowledge
vault add report.pdf --trust canonical
vault search "revenue projections" --top-k 5
vault list --trust canonical --tenant site-123
vault verify
vault health
vault delete <id>
vault transition <id> review --reason "Ready for review"
vault content <id>
vault replace <id> new-version.md
vault export backup.json
```

15 commands. Exit codes: `0` = pass, `1` = fail. Designed for CI: `vault verify && deploy`.

### FastAPI

```python
from qp_vault.integrations.fastapi_routes import create_vault_router

router = create_vault_router(vault)
app.include_router(router, prefix="/v1/vault")
# 22+ endpoints: resources, search, faceted search, verify, health,
# lifecycle, collections, provenance, batch, export, content
```

---

## Security

| Layer | Algorithm | Standard | Purpose |
|---|---|---|---|
| Content integrity | SHA3-256 | FIPS 202 | Tamper-evident CIDs and Merkle roots |
| Symmetric encryption | AES-256-GCM | FIPS 197 | Data at rest |
| Key encapsulation | ML-KEM-768 | FIPS 203 | Post-quantum key exchange |
| Digital signatures | ML-DSA-65 | FIPS 204 | Post-quantum provenance signing |
| Audit signatures | Ed25519 | FIPS 186-5 | Via [qp-capsule](https://github.com/quantumpipes/capsule) |
| Hybrid encryption | ML-KEM-768 + AES-256-GCM | FIPS 203+197 | Quantum-resistant data encryption |
| Content screening | Membrane pipeline | -- | Prompt injection, jailbreak, XSS detection |
| Access control | RBAC | -- | Reader / Writer / Admin roles |
| Input validation | Pydantic + custom | -- | Enum checks, name/tag/metadata limits |
| Plugin verification | SHA3-256 manifest | -- | Hash-verified plugin loading |
| Key management | ctypes memset | -- | Secure key zeroization |
| Self-testing | FIPS KAT | -- | SHA3-256 + AES-256-GCM known answer tests |

No deprecated cryptography. No runtime network dependencies. Air-gapped operation supported. Full threat model in [docs/security.md](docs/security.md).

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
| [Multi-Tenancy](docs/multi-tenancy.md) | Developers, SaaS |
| [Encryption](docs/encryption.md) | Developers, Security |
| [RBAC](docs/rbac.md) | Developers, Compliance |
| [Membrane](docs/membrane.md) | Developers, Security |
| [Streaming & Telemetry](docs/streaming-and-telemetry.md) | DevOps, Observability |
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

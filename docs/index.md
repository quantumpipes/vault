# qp-vault Documentation

Governed knowledge store for autonomous organizations. Every fact has provenance, every read is verified, every write is auditable.

## Guides

| Guide | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Install, first vault, add, search, verify in 5 minutes |
| [Architecture](architecture.md) | Package structure, layers, data flow, Protocol interfaces |
| [API Reference](api-reference.md) | Complete Python SDK: Vault, AsyncVault, all methods |
| [Trust Tiers](trust-tiers.md) | CANONICAL, WORKING, EPHEMERAL, ARCHIVED and search weighting |
| [Knowledge Lifecycle](lifecycle.md) | State machine, supersession chains, temporal validity |
| [Memory Layers](memory-layers.md) | OPERATIONAL, STRATEGIC, COMPLIANCE with per-layer defaults |
| [Multi-Tenancy](multi-tenancy.md) | Tenant isolation, tenant-locked vaults, per-tenant quotas |
| [Encryption](encryption.md) | AES-256-GCM, ML-KEM-768, ML-DSA-65, hybrid encryption |
| [RBAC](rbac.md) | Reader/Writer/Admin roles, permission matrix, structured error codes |
| [Membrane](membrane.md) | Content screening pipeline (innate scan, release gate) |
| [Plugin Development](plugins.md) | @embedder, @parser, @policy decorators, air-gap loading |
| [Security Model](security.md) | SHA3-256, Merkle trees, input validation, threat model |
| [Streaming & Telemetry](streaming-and-telemetry.md) | Real-time events, operation metrics |
| [CLI Reference](cli.md) | All 15 commands |
| [FastAPI Integration](fastapi.md) | 22+ REST endpoints |
| [Migration Guide](migration.md) | Breaking changes from v0.x to v1.0 |
| [Deployment Guide](deployment.md) | PostgreSQL, SSL, encryption, production checklist |
| [Troubleshooting](troubleshooting.md) | Error codes (VAULT_000-700), common issues |

## Quick Start

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")
vault.add("quarterly-report.pdf", trust_tier="canonical")
results = vault.search("Q3 revenue projections")
print(results[0].content, results[0].trust_tier)
```

## Installation

```bash
pip install qp-vault                    # SQLite, basic search, trust tiers
pip install qp-vault[encryption]        # + AES-256-GCM
pip install qp-vault[pq]               # + ML-KEM-768, ML-DSA-65
pip install qp-vault[all]              # Everything
```

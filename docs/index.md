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
| [Plugin Development](plugins.md) | @embedder, @parser, @policy decorators, air-gap loading |
| [Security Model](security.md) | SHA3-256, Merkle trees, input validation, threat model |
| [CLI Reference](cli.md) | vault init, add, search, inspect, verify, health, status |
| [FastAPI Integration](fastapi.md) | REST API routes, endpoints, request/response models |

## Quick Start

```python
from qp_vault import Vault

vault = Vault("./my-knowledge")
vault.add("quarterly-report.pdf", trust="canonical")
results = vault.search("Q3 revenue projections")
print(results[0].content, results[0].trust_tier)
```

## Installation

```bash
pip install qp-vault                # SQLite, basic search, trust tiers
pip install qp-vault[postgres]      # + PostgreSQL + pgvector
pip install qp-vault[capsule]       # + Cryptographic audit trail
pip install qp-vault[all]          # Everything
```

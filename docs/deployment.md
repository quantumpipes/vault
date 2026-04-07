# Deployment Guide

Production deployment recommendations for qp-vault.

## Choosing a Backend

| Scenario | Backend | Install |
|----------|---------|---------|
| Development, prototyping, < 10K chunks | SQLite | `pip install qp-vault` |
| Production, multi-user, > 10K chunks | PostgreSQL | `pip install qp-vault[postgres]` |
| Air-gapped / SCIF | SQLite + local embeddings | `pip install qp-vault[local,encryption]` |

SQLite uses brute-force cosine similarity (O(n*d) per search). PostgreSQL uses pgvector HNSW index (logarithmic). For vaults over 10,000 chunks, PostgreSQL is required for acceptable search latency.

## SQLite (Default)

Zero config. Database created automatically.

```python
vault = Vault("./my-knowledge")
```

File permissions: new databases are created with `0600` (owner-only read/write). WAL and SHM journal files are also restricted.

## PostgreSQL

### Prerequisites

- PostgreSQL 16+ with `pgvector` and `pg_trgm` extensions
- `pip install qp-vault[postgres]`

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### Connection

```python
vault = Vault.from_postgres("postgresql://user:pass@host:5432/vaultdb")
```

SSL is enabled by default. To disable (development only):

```python
vault = Vault.from_postgres("postgresql://user:pass@host:5432/vaultdb?sslmode=disable")
```

SSL verification can be enabled for production:

```python
from qp_vault.config import VaultConfig
config = VaultConfig(postgres_ssl=True, postgres_ssl_verify=True)
```

<!-- VERIFIED: storage/postgres.py:191-230 — SSL context, command_timeout -->

### Connection Pooling

The PostgreSQL backend uses asyncpg's built-in connection pool (min 2, max 10 connections, configurable command timeout).

<!-- VERIFIED: storage/postgres.py:224-230 — pool configuration -->

## Encryption

```bash
pip install qp-vault[encryption]      # AES-256-GCM
pip install qp-vault[encryption,pq]   # + ML-KEM-768, ML-DSA-65
```

```python
from qp_vault.encryption import AESGCMEncryptor

enc = AESGCMEncryptor()           # Random 256-bit key
enc = AESGCMEncryptor(key=my_key) # Bring your own key (32 bytes)

ciphertext = enc.encrypt(b"secret data")
plaintext = enc.decrypt(ciphertext)
```

Key management: keys are zeroized from memory via `ctypes.memset` when the encryptor is garbage collected. For production, store keys in a secrets manager or HSM, not in code.

## Embeddings

| Provider | Install | Air-Gap | Dimensions |
|----------|---------|---------|------------|
| None (text-only search) | (default) | Yes | 0 |
| SentenceTransformers | `qp-vault[local]` | Yes | Model-dependent |
| OpenAI | `qp-vault[openai]` | No | 1536 / 3072 |

```python
from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

vault = Vault("./knowledge", embedder=SentenceTransformerEmbedder())
```

## LLM Content Screening

Optional. Requires a running LLM (Ollama for air-gap, or cloud API).

```python
from qp_vault.membrane.screeners.ollama import OllamaScreener

vault = Vault("./knowledge", llm_screener=OllamaScreener(model="llama3.2"))
```

Without an LLM screener, only regex-based innate scan runs (still catches common attacks).

## Production Checklist

- [ ] PostgreSQL with pgvector extension (not SQLite)
- [ ] SSL enabled on database connection
- [ ] Encryption at rest enabled (`AESGCMEncryptor`)
- [ ] Keys stored in secrets manager (not code)
- [ ] RBAC role set (`role="writer"` for application, `role="admin"` for operators)
- [ ] Tenant ID locked if multi-tenant (`tenant_id="..."`)
- [ ] Per-tenant quotas configured (`max_resources_per_tenant`)
- [ ] Query timeout configured (`query_timeout_ms`, default 30s)
- [ ] Health endpoint monitored (`vault.health()`, cached 30s)
- [ ] Audit trail active (auto-detects qp-capsule if installed)
- [ ] Backups: regular `vault.export_vault("backup.json")`
- [ ] Plugin manifest.json present if using plugins_dir

## Scaling

| Resources | Chunks (est.) | Backend | Search Latency |
|-----------|--------------|---------|---------------|
| 100 | 500 | SQLite | < 50ms |
| 1,000 | 5,000 | SQLite | < 200ms |
| 10,000 | 50,000 | PostgreSQL | < 100ms |
| 100,000 | 500,000 | PostgreSQL + HNSW | < 200ms |

Health/status responses are cached (default 30s TTL) to avoid full vault scans on repeated calls.

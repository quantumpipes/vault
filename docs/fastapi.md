# FastAPI Integration

qp-vault provides 30+ ready-made REST API endpoints.

```bash
pip install qp-vault[fastapi]
```

## Quick Start

```python
from fastapi import FastAPI
from qp_vault import AsyncVault
from qp_vault.integrations.fastapi_routes import create_vault_router

app = FastAPI()
vault = AsyncVault("./knowledge")
router = create_vault_router(vault)
app.include_router(router, prefix="/v1/vault")
```

## Endpoints

### Resources

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/resources` | Add a resource |
| `GET` | `/resources` | List resources (filtered, paginated) |
| `GET` | `/resources/{id}` | Get resource details |
| `PUT` | `/resources/{id}` | Update resource metadata |
| `DELETE` | `/resources/{id}` | Delete resource (`?hard=true` for permanent) |
| `GET` | `/resources/{id}/content` | Get full text content |
| `GET` | `/resources/{id}/provenance` | Get provenance records |

### Lifecycle

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/resources/{id}/transition` | Change lifecycle state |
| `POST` | `/resources/{id}/supersede` | Supersede with newer resource |
| `GET` | `/resources/{id}/chain` | Get supersession chain |

### Verification

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/resources/{id}/verify` | Verify single resource integrity |
| `GET` | `/resources/{id}/proof` | Export Merkle proof |
| `GET` | `/verify` | Verify entire vault |

### Search & Retrieval

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Trust-weighted hybrid search |
| `POST` | `/search/faceted` | Search with facet counts |
| `POST` | `/grep` | Multi-keyword OR search (hit-density scoring) |
| `GET` | `/resources/by-name` | Find resource by name (case-insensitive) |

### Collections

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/collections` | List collections |
| `POST` | `/collections` | Create collection |

### Processing

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/resources/{id}/reprocess` | Re-chunk and re-embed a resource |

### Batch, Import & Export

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/batch` | Batch add (max 100 items) |
| `POST` | `/resources/multiple` | Get multiple resources by ID (max 100) |
| `GET` | `/export` | Export vault to JSON |
| `POST` | `/import` | Import resources from export file |

### Adversarial & Diff

| Method | Path | Description |
|--------|------|-------------|
| `PATCH` | `/resources/{id}/adversarial` | Set adversarial verification status |
| `GET` | `/resources/{old_id}/diff/{new_id}` | Unified diff between two resources |

### Intelligence

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Vault health score (0-100) |
| `GET` | `/status` | Resource counts and metadata |
| `GET` | `/expiring` | Resources expiring within N days |

<!-- VERIFIED: integrations/fastapi_routes.py:118-390 — all endpoints -->

## Input Validation

All endpoints validate inputs at the API boundary before reaching vault logic.

| Field | Constraint | Endpoint |
|-------|-----------|----------|
| `content` | Max 500MB | `POST /resources` |
| `query` | Max 10,000 characters | `POST /search` |
| `top_k` | 1-1,000 | `POST /search` |
| `threshold` | 0.0-1.0 | `POST /search` |
| `limit` | 1-1,000 | `GET /resources` |
| `offset` | 0-1,000,000 | `GET /resources` |
| Batch sources | Max 100 items | `POST /batch` |
| `as_of` | Valid ISO date | `POST /search` |
| `keywords` | Max 20 items | `POST /grep` |
| `name` | Max 255 characters | `GET /resources/by-name` |
| `resource_ids` | Max 100 items | `POST /resources/multiple` |

<!-- VERIFIED: integrations/fastapi_routes.py:40 — content max_length -->
<!-- VERIFIED: integrations/fastapi_routes.py:51-53 — SearchRequest validators -->
<!-- VERIFIED: integrations/fastapi_routes.py:140-141 — limit/offset Query validators -->

## Response Caching

`GET /health` and `GET /status` responses are cached with a configurable TTL (default 30 seconds). The cache is invalidated on any write operation (add, update, delete).

Configure via `VaultConfig(health_cache_ttl_seconds=60)`.

<!-- VERIFIED: vault.py:947-955 — health cache -->
<!-- VERIFIED: vault.py:1026-1031 — status cache -->

## Error Codes

| HTTP | Vault Code | Meaning |
|------|------------|---------|
| 404 | VAULT_000 | Resource not found |
| 409 | VAULT_300 | Invalid lifecycle transition |
| 400 | — | Bad request (batch too large, invalid params) |
| 500 | VAULT_100 | Storage operation failed |

Error responses never expose internal details.

<!-- VERIFIED: integrations/fastapi_routes.py:92-101 — _handle_error -->

## CORS

The router has no CORS configuration by default (secure: denies all cross-origin). Add your own:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(CORSMiddleware, allow_origins=["https://your-app.com"])
```

# FastAPI Integration

qp-vault provides 22+ ready-made REST API endpoints.

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

### Search

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Trust-weighted hybrid search |
| `POST` | `/search/faceted` | Search with facet counts |

### Collections

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/collections` | List collections |
| `POST` | `/collections` | Create collection |

### Batch & Export

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/batch` | Batch add (max 100 items) |
| `GET` | `/export` | Export vault to JSON |

### Intelligence

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Vault health score (0-100) |
| `GET` | `/status` | Resource counts and metadata |
| `GET` | `/expiring` | Resources expiring within N days |

<!-- VERIFIED: integrations/fastapi_routes.py:118-310 — all endpoints -->

## Input Validation

| Field | Constraint |
|-------|-----------|
| `query` | Max 10,000 characters |
| `top_k` | 1-1,000 |
| `threshold` | 0.0-1.0 |
| Batch sources | Max 100 items |

<!-- VERIFIED: integrations/fastapi_routes.py:50-53 — SearchRequest validators -->

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

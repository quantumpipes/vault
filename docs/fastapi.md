# FastAPI Integration

qp-vault provides ready-made FastAPI routes for building REST APIs on top of a vault.

## Install

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

<!-- VERIFIED: integrations/fastapi_routes.py:78-102 — create_vault_router factory -->

## Endpoints

### Resources

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/resources` | Add a resource |
| `GET` | `/resources` | List resources (filtered, paginated) |
| `GET` | `/resources/{id}` | Get resource details |
| `PUT` | `/resources/{id}` | Update resource metadata |
| `DELETE` | `/resources/{id}` | Delete resource (soft by default, `?hard=true` for permanent) |

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

### Intelligence

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Trust-weighted hybrid search |
| `GET` | `/health` | Vault health score (0-100) |
| `GET` | `/status` | Resource counts and metadata |
| `GET` | `/expiring` | Resources expiring within N days |

## Request/Response Examples

### Add Resource

```bash
POST /v1/vault/resources
```

```json
{
    "content": "Incident response SOP: acknowledge within 15 minutes...",
    "name": "sop-incident.md",
    "trust": "canonical",
    "layer": "operational",
    "tags": ["sop", "incident"],
    "metadata": {"author": "security-team"}
}
```

Response:
```json
{
    "data": {
        "id": "a1b2c3d4-...",
        "name": "sop-incident.md",
        "trust_tier": "canonical",
        "status": "indexed",
        "chunk_count": 3,
        "cid": "vault://sha3-256/..."
    },
    "meta": {}
}
```

### Search

```bash
POST /v1/vault/search
```

```json
{
    "query": "incident response procedure",
    "top_k": 5,
    "trust_min": "working",
    "layer": "operational"
}
```

### Lifecycle Transition

```bash
POST /v1/vault/resources/{id}/transition
```

```json
{
    "target": "review",
    "reason": "Ready for security team review"
}
```

Returns `409 Conflict` for invalid transitions.

### Export Proof

```bash
GET /v1/vault/resources/{id}/proof
```

Response:
```json
{
    "data": {
        "resource_id": "a1b2c3d4-...",
        "resource_hash": "8c822da2...",
        "merkle_root": "a92f5626...",
        "path": [{"hash": "...", "position": "right"}],
        "leaf_index": 0,
        "tree_size": 42
    }
}
```

## Error Handling

Errors return appropriate HTTP status codes:

| Code | Meaning | Vault Exception |
|------|---------|-----------------|
| `404` | Resource not found | `VaultError` |
| `409` | Invalid lifecycle transition | `LifecycleError` |
| `500` | Storage operation failed | `StorageError` |

Error responses never expose internal details (file paths, stack traces). Full errors are logged server-side.

<!-- VERIFIED: integrations/fastapi_routes.py:92-101 — _handle_error with sanitized messages -->

## Custom Middleware

The router is a standard FastAPI `APIRouter`. Add authentication, CORS, rate limiting as needed:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(CORSMiddleware, allow_origins=["*"])

# Or protect with dependency injection
from fastapi import Depends, HTTPException

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != "expected-key":
        raise HTTPException(status_code=401)

router = create_vault_router(vault)
app.include_router(router, prefix="/v1/vault", dependencies=[Depends(verify_api_key)])
```

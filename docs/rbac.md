# Role-Based Access Control (RBAC)

qp-vault enforces role-based permissions at the API boundary.

## Roles

| Role | Permissions |
|------|------------|
| **READER** | search, get, get_content, list, verify, health, status, get_provenance, chain, expiring, list_collections |
| **WRITER** | All reader ops + add, add_batch, update, delete, replace, transition, supersede, set_adversarial_status |
| **ADMIN** | All writer ops + export_vault, import_vault, create_collection, export_proof |

<!-- VERIFIED: rbac.py:36-60 — PERMISSIONS dict -->

## Usage

```python
from qp_vault import Vault

# Reader: can search and verify, cannot write
vault = Vault("./knowledge", role="reader")
results = vault.search("query")     # OK
vault.add("content")                # Raises VaultError (VAULT_700)

# Writer: can add and modify
vault = Vault("./knowledge", role="writer")
vault.add("content")                # OK
vault.export_vault("dump.json")     # Raises VaultError (VAULT_700)

# Admin: full access
vault = Vault("./knowledge", role="admin")

# No RBAC (default): all operations allowed
vault = Vault("./knowledge")
```

## Role Hierarchy

Higher roles inherit all lower permissions:

```
ADMIN (3) > WRITER (2) > READER (1)
```

<!-- VERIFIED: rbac.py:63-68 — ROLE_HIERARCHY -->

## Structured Error Codes

Permission violations raise `VaultError` with code `VAULT_700`.

| Code | Exception | Meaning |
|------|-----------|---------|
| VAULT_000 | VaultError | General vault error |
| VAULT_100 | StorageError | Database operation failed |
| VAULT_200 | VerificationError | Integrity check failed |
| VAULT_300 | LifecycleError | Invalid state transition |
| VAULT_400 | PolicyError | Policy denied operation |
| VAULT_500 | ChunkingError | Text chunking failed |
| VAULT_600 | ParsingError | File parsing failed |
| VAULT_700 | PermissionError | RBAC permission denied |

<!-- VERIFIED: exceptions.py:1-48 — all error codes -->

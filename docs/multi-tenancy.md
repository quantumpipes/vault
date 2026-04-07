# Multi-Tenancy

qp-vault supports multi-tenant isolation via `tenant_id` on all operations.

## Usage

```python
vault = Vault("./knowledge")

# Add with tenant isolation
vault.add("Tenant A document", tenant_id="site-123", trust="canonical")
vault.add("Tenant B document", tenant_id="site-456", trust="working")

# Search scoped to tenant
results = vault.search("document", tenant_id="site-123")
# Only returns site-123 resources

# List scoped to tenant
resources = vault.list(tenant_id="site-123")

# Verify scoped to tenant (Merkle tree per tenant)
result = vault.verify()  # Vault-wide
```

<!-- VERIFIED: vault.py:218-220 — tenant_id parameter on add -->

## Tenant-Locked Vault

For stricter isolation, lock the vault to a single tenant at construction:

```python
vault = Vault("./knowledge", tenant_id="site-123")

# All operations auto-inject tenant_id="site-123"
vault.add("doc")              # tenant_id="site-123" applied automatically
vault.search("query")         # scoped to site-123

# Mismatched tenant_id is rejected
vault.add("doc", tenant_id="site-456")  # Raises VaultError: tenant mismatch
```

When a vault is tenant-locked:
- Operations with no `tenant_id` auto-inject the locked tenant
- Operations with a matching `tenant_id` proceed normally
- Operations with a different `tenant_id` raise `VaultError`

<!-- VERIFIED: vault.py:257-277 — _resolve_tenant enforcement -->

## Per-Tenant Quotas

Limit the number of resources per tenant:

```python
from qp_vault.config import VaultConfig

config = VaultConfig(max_resources_per_tenant=1000)
vault = Vault("./knowledge", config=config)

vault.add("doc", tenant_id="site-123")  # OK until quota reached
# After 1000 resources: raises VaultError("Tenant site-123 has reached the resource limit")
```

Quotas are enforced with an atomic `COUNT(*)` query at the storage layer. No TOCTOU race condition window.

<!-- VERIFIED: config.py:68 — max_resources_per_tenant -->
<!-- VERIFIED: vault.py:406-416 — atomic count_resources check -->
<!-- VERIFIED: storage/sqlite.py:595-601 — count_resources implementation -->

## Storage

`tenant_id` is stored as a column in the resources table with an index for efficient filtering.

<!-- VERIFIED: storage/sqlite.py:42 — tenant_id TEXT column -->
<!-- VERIFIED: storage/sqlite.py:115 — idx_resources_tenant index -->

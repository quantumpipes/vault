# Migration Guide: v0.x to v1.0

qp-vault 1.0 locks the API. Three parameter renames are the only breaking changes.

## Breaking Changes

### 1. `trust` parameter renamed to `trust_tier`

Affects: `add()`, `list()`, `update()`, `add_batch()`, `replace()`.

```python
# Before (v0.16 and earlier)
vault.add("document.pdf", trust="canonical")
vault.list(trust="working")
vault.update(resource_id, trust="canonical")

# After (v1.0)
vault.add("document.pdf", trust_tier="canonical")
vault.list(trust_tier="working")
vault.update(resource_id, trust_tier="canonical")
```

### 2. `trust_min` parameter renamed to `min_trust_tier`

Affects: `search()`, `search_with_facets()`.

```python
# Before
results = vault.search("query", trust_min="working")

# After
results = vault.search("query", min_trust_tier="working")
```

### 3. `LayerDefaults.trust` field renamed to `LayerDefaults.trust_tier`

Affects: VaultConfig TOML files and programmatic config.

```python
# Before
from qp_vault.config import VaultConfig, LayerDefaults

config = VaultConfig(layer_defaults={
    "operational": LayerDefaults(trust="working"),
})

# After
config = VaultConfig(layer_defaults={
    "operational": LayerDefaults(trust_tier="working"),
})
```

## Quick Migration

For most codebases, a find-and-replace handles it:

```bash
# Parameter renames
sed -i 's/trust="canonical"/trust_tier="canonical"/g' your_code.py
sed -i 's/trust="working"/trust_tier="working"/g' your_code.py
sed -i 's/trust="ephemeral"/trust_tier="ephemeral"/g' your_code.py
sed -i 's/trust="archived"/trust_tier="archived"/g' your_code.py
sed -i 's/trust_min=/min_trust_tier=/g' your_code.py

# Config field
sed -i 's/LayerDefaults(trust=/LayerDefaults(trust_tier=/g' your_code.py
```

## What Didn't Change

- All model field names (`Resource.trust_tier`, `SearchResult.trust_tier`) are unchanged
- CLI flags (`--trust`) are unchanged
- Error codes (VAULT_000 through VAULT_700) are unchanged
- Storage schema is unchanged (no migration needed for databases)
- All Protocol interfaces are unchanged
- Encryption, Membrane, RBAC, and plugin APIs are unchanged

## New in v1.0

- `vault.upsert(source, name=...)`: add-or-replace atomically
- `vault.get_multiple(resource_ids)`: batch retrieval in a single query
- `LLMScreener` Protocol + Membrane ADAPTIVE_SCAN (v0.16)
- Classifier upgraded to Production/Stable

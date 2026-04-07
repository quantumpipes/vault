# Troubleshooting

## Error Code Reference

Every vault exception has a structured error code. CLI displays these as `[VAULT_XXX]`.

| Code | Exception | Meaning | Common Causes |
|------|-----------|---------|---------------|
| `VAULT_000` | `VaultError` | General vault error | Invalid parameters, tenant mismatch, quota exceeded, Membrane rejection |
| `VAULT_100` | `StorageError` | Storage backend failure | Database connection lost, disk full, schema mismatch |
| `VAULT_200` | `VerificationError` | Integrity check failed | Tampered content, corrupt database, missing chunks |
| `VAULT_300` | `LifecycleError` | Invalid state transition | Transitioning ARCHIVED to DRAFT, expired resource |
| `VAULT_400` | `PolicyError` | Policy denied operation | Custom PolicyProvider rejected the action |
| `VAULT_500` | `ChunkingError` | Text chunking failed | Empty content, encoding issues |
| `VAULT_600` | `ParsingError` | File parsing failed | Unsupported format, corrupt file |
| `VAULT_700` | `PermissionError` | RBAC denied | Reader trying to write, writer trying to export |

<!-- VERIFIED: exceptions.py:1-54 — all error codes -->

## Common Issues

### "Tenant mismatch" error

```
VaultError: Tenant mismatch: vault is locked to 'site-123' but operation specified 'site-456'
```

**Cause**: The vault was created with `tenant_id="site-123"` but you're trying to operate on a different tenant.

**Fix**: Either remove the tenant lock from the constructor, or ensure all operations use the correct tenant_id. When a vault is tenant-locked, you don't need to pass `tenant_id` on each call (it's auto-injected).

### "Resource limit" error

```
VaultError: Tenant site-123 has reached the resource limit (1000)
```

**Cause**: `max_resources_per_tenant` quota exceeded.

**Fix**: Increase the quota in VaultConfig, delete old resources, or archive them.

### "Content rejected by Membrane screening"

```
VaultError: Content rejected by Membrane screening
```

**Cause**: The Membrane pipeline's overall result was FAIL (detected dangerous content like prompt injection, XSS, or code execution).

**Fix**: Review the content. If it's a false positive, you can disable the Membrane: `MembranePipeline(enabled=False)`. For legitimate security documentation, consider adding custom innate scan patterns that whitelist specific terms.

### "Resource is quarantined"

```
VaultError: Resource abc123 is quarantined by Membrane screening
```

**Cause**: `get_content()` called on a quarantined resource. Quarantined resources are stored but their content is not accessible.

**Fix**: Review the resource metadata via `vault.get(resource_id)`. If it should be released, update its status via the storage backend (admin operation).

### "Operation timed out"

```
VaultError: Operation timed out after 30000ms
```

**Cause**: A search or storage operation exceeded `query_timeout_ms`.

**Fix**: Increase timeout in config, optimize the query (reduce `top_k`), or switch to PostgreSQL if using SQLite with large datasets.

### RBAC "permission denied"

```
PermissionError: Operation 'add' requires WRITER role, current role: READER
```

**Cause**: Vault was created with `role="reader"` but you're trying to write.

**Fix**: Create the vault with the appropriate role: `Vault(path, role="writer")` or `role="admin"`.

### FTS5 search returns no results

**Cause**: SQLite FTS5 full-text search requires exact or prefix matches. Semantic search requires an embedding provider.

**Fix**: Install an embedder: `pip install qp-vault[local]` and pass it to the constructor:

```python
from qp_vault.embeddings.sentence import SentenceTransformerEmbedder
vault = Vault("./knowledge", embedder=SentenceTransformerEmbedder())
```

### Plugin directory skipped

```
WARNING: Plugin directory /opt/plugins has no manifest.json. Skipping.
```

**Cause**: Plugin discovery requires a `manifest.json` with SHA3-256 hashes for each plugin file.

**Fix**: Generate a manifest. See [Plugin Development](plugins.md) for the generation script.

## Performance Tuning

| Symptom | Cause | Fix |
|---------|-------|-----|
| Slow search (> 1s) | SQLite brute-force cosine sim | Switch to PostgreSQL with pgvector HNSW index |
| Slow health/status | Full vault scan | Already cached (30s TTL). Increase `health_cache_ttl_seconds` |
| Memory spikes on status | Loading all resources | Hard cap at 50,000 resources. Use PostgreSQL for larger vaults |
| Slow add with LLM | Adaptive scan latency | Reduce `max_content_length` in AdaptiveScanConfig (default 4000 chars) |

## Getting Help

- [GitHub Issues](https://github.com/quantumpipes/vault/issues)
- [API Reference](api-reference.md)
- [Security Model](security.md)

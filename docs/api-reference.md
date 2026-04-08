# API Reference

Complete Python SDK for qp-vault v1.4.0.

## Constructor

```python
Vault(
    path: str | Path,
    *,
    storage: StorageBackend | None = None,      # Default: SQLite
    embedder: EmbeddingProvider | None = None,   # Default: None
    auditor: AuditProvider | None = None,        # Default: LogAuditor (auto-detects CapsuleAuditor)
    parsers: list[ParserProvider] | None = None,
    policies: list[PolicyProvider] | None = None,
    config: VaultConfig | None = None,
    plugins_dir: str | Path | None = None,       # Air-gap plugin directory
    tenant_id: str | None = None,                # Lock vault to single tenant
    role: str | None = None,                     # RBAC: "reader", "writer", "admin", or None
)
```

When `tenant_id` is set, the vault enforces tenant isolation: operations auto-inject the locked tenant, and operations with a mismatched `tenant_id` raise `VaultError`.

When `role` is set, all operations are checked against the RBAC permission matrix. Operations exceeding the role's permissions raise `VaultError` with code `VAULT_700`.

<!-- VERIFIED: vault.py:132-145, 257-277 — constructor + _resolve_tenant -->

### Factory Methods

```python
Vault.from_postgres(dsn: str, **kwargs) -> Vault
Vault.from_config(config_path: str | Path) -> Vault
```

---

## Resource Operations

### add()

```python
vault.add(
    source: str | Path | bytes,
    *,
    name: str | None = None,
    trust_tier: TrustTier | str = "working",
    classification: DataClassification | str = "internal",
    layer: MemoryLayer | str | None = None,
    collection: str | None = None,
    tags: list[str] | None = None,              # Max 50, 100 chars each
    metadata: dict[str, Any] | None = None,     # Max 100 keys, alphanumeric
    lifecycle: Lifecycle | str = "active",
    valid_from: date | None = None,
    valid_until: date | None = None,
    tenant_id: str | None = None,
) -> Resource
```

Content is screened by the Membrane pipeline before indexing. Flagged content is quarantined.

<!-- VERIFIED: vault.py:218-349 -->

### add_batch()

```python
vault.add_batch(
    sources: list[str | Path | bytes],
    *,
    trust_tier: TrustTier | str = "working",
    tenant_id: str | None = None,
    **kwargs,
) -> list[Resource]
```

<!-- VERIFIED: vault.py:466-491 -->

### get()

```python
vault.get(resource_id: str) -> Resource
```

### get_multiple()

```python
vault.get_multiple(resource_ids: list[str]) -> list[Resource]
```

Batch retrieval in a single query. Missing IDs are silently omitted.

<!-- VERIFIED: vault.py:473-485 -->

### get_content()

```python
vault.get_content(resource_id: str) -> str
```

Reassembles chunks in order to return the full text content. Quarantined resources raise `VaultError`.

<!-- VERIFIED: vault.py:406-420 -->

### reprocess()

```python
vault.reprocess(resource_id: str) -> Resource
```

Re-chunks and re-embeds an existing resource. Useful when the embedding model changes or chunking parameters are updated. The resource content is preserved; only chunks and embeddings are regenerated.

```python
# After switching embedding models
updated = vault.reprocess(resource.id)
assert updated.status == "indexed"
```

Emits an `UPDATE` subscriber event with `details={"reprocessed": True}`.

<!-- VERIFIED: vault.py:706-770 -->

### list()

```python
vault.list(
    *,
    tenant_id: str | None = None,
    trust_tier: TrustTier | str | None = None,
    classification: DataClassification | str | None = None,
    layer: MemoryLayer | str | None = None,
    collection: str | None = None,
    lifecycle: Lifecycle | str | None = None,
    status: ResourceStatus | str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Resource]
```

<!-- VERIFIED: vault.py:373-400 -->

### find_by_name()

```python
vault.find_by_name(
    name: str,
    *,
    tenant_id: str | None = None,
    collection_id: str | None = None,
) -> Resource | None
```

Case-insensitive name lookup. Returns the first matching non-deleted resource, or `None`.

```python
resource = vault.find_by_name("STRATEGY.md")
# Also matches "strategy.md", "Strategy.MD"
```

<!-- VERIFIED: vault.py:632-668 -->

### update()

```python
vault.update(
    resource_id: str,
    *,
    name: str | None = None,
    trust_tier: TrustTier | str | None = None,
    classification: DataClassification | str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Resource
```

### delete()

```python
vault.delete(resource_id: str, *, hard: bool = False) -> None
```

### replace()

```python
vault.replace(
    resource_id: str,
    new_content: str,
    *,
    reason: str | None = None,
) -> tuple[Resource, Resource]
```

Creates a new resource with the new content and supersedes the old one. Returns (old, new).

<!-- VERIFIED: vault.py:422-464 -->

### upsert()

```python
vault.upsert(
    source: str | Path | bytes,
    *,
    name: str | None = None,
    trust_tier: TrustTier | str = "working",
    tenant_id: str | None = None,
    **kwargs,
) -> Resource
```

Add-or-replace atomically. If a resource with the same name and tenant exists, supersedes it. Otherwise creates new.

<!-- VERIFIED: vault.py:562-611 -->

---

## Search

### search()

```python
vault.search(
    query: str,
    *,
    tenant_id: str | None = None,
    top_k: int = 10,
    offset: int = 0,                    # Pagination
    threshold: float = 0.0,
    min_trust_tier: TrustTier | str | None = None,
    layer: MemoryLayer | str | None = None,
    collection: str | None = None,
    as_of: date | None = None,          # Point-in-time
    deduplicate: bool = True,           # One result per resource
    explain: bool = False,              # Include scoring breakdown
) -> list[SearchResult]
```

When no embedder is configured, search automatically falls back to text-only mode (`vector_weight=0.0`, `text_weight=1.0`). This ensures search works on day one without requiring an embedding model.

<!-- VERIFIED: vault.py:1051-1063 — text-only fallback -->

### search_with_facets()

```python
vault.search_with_facets(query: str, **kwargs) -> dict[str, Any]
```

Returns `{"results": [...], "total": N, "facets": {"trust_tier": {...}, "resource_type": {...}}}`.

<!-- VERIFIED: vault.py:650-687 -->

### grep()

```python
vault.grep(
    keywords: list[str],
    *,
    tenant_id: str | None = None,
    top_k: int = 20,
    max_keywords: int = 20,
) -> list[SearchResult]
```

Multi-keyword OR search with three-signal blended scoring. Executes a single FTS5 OR query (SQLite) or ILIKE+trigram query (PostgreSQL) regardless of keyword count.

**Scoring formula:** `coverage * (0.7 * text_rank + 0.3 * proximity)` where:
- **Coverage** (Lucene coord factor): `matched_keywords / total_keywords`, applied as a multiplier. 3/3 = full score, 1/3 = 33%.
- **Text rank**: native FTS5 bm25 or pg_trgm similarity (0.0-1.0).
- **Proximity**: how close matched keywords appear to each other within the chunk.

```python
results = vault.grep(["revenue", "Q3", "forecast"])
# Results sorted by blended relevance (coverage * text_rank + proximity)
# explain_metadata includes: matched_keywords, hit_density, text_rank, proximity, snippet
print(results[0].explain_metadata["snippet"])
# "...discussed **Q3** **revenue** **forecast** projections..."
```

No embedder required. Single database query. Results deduplicated by resource and trust-weighted.

<!-- VERIFIED: vault.py:1172-1266 -->

**SearchResult fields:**

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | str | Chunk identifier |
| `resource_id` | str | Parent resource |
| `resource_name` | str | Display name |
| `content` | str | Chunk text |
| `vector_similarity` | float | Cosine similarity (0-1) |
| `text_rank` | float | Full-text match score |
| `trust_weight` | float | Trust tier x adversarial multiplier |
| `freshness` | float | Decay factor |
| `relevance` | float | Composite score |
| `updated_at` | str | Resource timestamp (for freshness) |
| `resource_type` | str | Document type |
| `data_classification` | str | Sensitivity level |
| `trust_tier` | TrustTier | Resource trust tier |
| `adversarial_status` | AdversarialStatus | Membrane verification status |
| `cid` | str | Chunk content ID (SHA3-256) |
| `lifecycle` | Lifecycle | Resource lifecycle state |

---

## Lifecycle

### transition()

```python
vault.transition(resource_id: str, target: Lifecycle | str, *, reason: str | None = None) -> Resource
```

### supersede()

```python
vault.supersede(old_id: str, new_id: str) -> tuple[Resource, Resource]
```

### expiring()

```python
vault.expiring(*, days: int = 90) -> list[Resource]
```

### chain()

```python
vault.chain(resource_id: str) -> list[Resource]
```

Max chain length: 1000 (cycle protection).

---

## Verification

### verify()

```python
vault.verify(resource_id: str | None = None) -> VerificationResult | VaultVerificationResult
```

### export_proof()

```python
vault.export_proof(resource_id: str) -> MerkleProof
```

---

## Provenance & Adversarial

### get_provenance()

```python
vault.get_provenance(resource_id: str) -> list[dict[str, Any]]
```

<!-- VERIFIED: vault.py:493-502 -->

### set_adversarial_status()

```python
vault.set_adversarial_status(resource_id: str, status: str) -> Resource
```

Status values: `"unverified"`, `"verified"`, `"suspicious"`.

<!-- VERIFIED: vault.py:504-515 -->

---

## Collections

### create_collection()

```python
vault.create_collection(name: str, *, description: str = "", tenant_id: str | None = None) -> dict
```

### list_collections()

```python
vault.list_collections(*, tenant_id: str | None = None) -> list[dict]
```

<!-- VERIFIED: vault.py:714-744 -->

---

## Memory Layers

### layer()

```python
vault.layer(name: MemoryLayer | str) -> LayerView
```

---

## Health

### health()

```python
vault.health(resource_id: str | None = None) -> HealthScore
```

Pass `resource_id` for per-resource health, or `None` for vault-wide.

<!-- VERIFIED: vault.py:826-844 -->

---

## Import / Export

### export_vault()

```python
vault.export_vault(path: str | Path) -> dict[str, Any]
```

### import_vault()

```python
vault.import_vault(path: str | Path) -> list[Resource]
```

<!-- VERIFIED: vault.py:846-889 -->

---

## Status

### status()

```python
vault.status() -> dict[str, Any]
```

---

## Event Subscription

### subscribe()

```python
vault.subscribe(callback: Callable[[VaultEvent], Any]) -> Callable[[], None]
```

Register a callback for vault mutation events. Returns an unsubscribe function. Callbacks can be sync or async; async callbacks are awaited directly. Errors in callbacks are logged and never propagated to the caller.

```python
from qp_vault import AsyncVault, VaultEvent

vault = AsyncVault("./knowledge")

# Sync callback
def on_change(event: VaultEvent) -> None:
    print(f"{event.event_type}: {event.resource_name}")

unsub = vault.subscribe(on_change)

# Add a resource (callback fires with CREATE event)
vault.add("Content", name="doc.md")

# Stop receiving events
unsub()
```

**Events emitted on:**

| Operation | EventType |
|-----------|-----------|
| `add()` | `CREATE` |
| `update()` | `UPDATE` |
| `delete()` | `DELETE` |
| `reprocess()` | `UPDATE` (with `details.reprocessed=True`) |
| `transition()` | `LIFECYCLE_TRANSITION` |

Multiple subscribers are independent. Unsubscribing one does not affect others. Calling `unsub()` twice is safe.

<!-- VERIFIED: vault.py:289-336 — subscribe + _notify_subscribers -->

---

## Plugin Registration

```python
vault.register_embedder(embedder: EmbeddingProvider) -> None
vault.register_parser(parser: ParserProvider) -> None
vault.register_policy(policy: PolicyProvider) -> None
```

---

## Enums

| Enum | Values |
|------|--------|
| `TrustTier` | `canonical`, `working`, `ephemeral`, `archived` |
| `DataClassification` | `public`, `internal`, `confidential`, `restricted` |
| `ResourceType` | `document`, `image`, `audio`, `video`, `note`, `code`, `spreadsheet`, `transcript`, `other` |
| `ResourceStatus` | `pending`, `quarantined`, `processing`, `indexed`, `error`, `deleted` |
| `Lifecycle` | `draft`, `review`, `active`, `superseded`, `expired`, `archived` |
| `MemoryLayer` | `operational`, `strategic`, `compliance` |
| `AdversarialStatus` | `unverified`, `verified`, `suspicious` |
| `MembraneStage` | `ingest`, `innate_scan`, `adaptive_scan`, `correlate`, `release`, `surveil`, `present`, `remember` |
| `MembraneResult` | `pass`, `flag`, `fail`, `skip` |
| `EventType` | `create`, `update`, `delete`, `restore`, `trust_change`, `classification_change`, `lifecycle_transition`, `supersede`, `verify`, `search`, `membrane_scan`, `membrane_release`, `membrane_flag`, `adversarial_status_change` |
| `Role` | `reader`, `writer`, `admin` |

<!-- VERIFIED: enums.py:1-210, rbac.py:21-30 -->

---

## Exceptions

| Code | Exception | When |
|------|-----------|------|
| VAULT_000 | `VaultError` | General error, resource not found |
| VAULT_100 | `StorageError` | Database operation failed |
| VAULT_200 | `VerificationError` | Integrity check failed |
| VAULT_300 | `LifecycleError` | Invalid state transition |
| VAULT_400 | `PolicyError` | Policy denied operation |
| VAULT_500 | `ChunkingError` | Text chunking failed |
| VAULT_600 | `ParsingError` | File parsing failed |
| VAULT_700 | `PermissionError` | RBAC permission denied |

<!-- VERIFIED: exceptions.py:1-48 -->

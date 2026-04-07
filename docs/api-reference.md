# API Reference

Complete Python SDK for qp-vault v0.13.0.

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

<!-- VERIFIED: vault.py:132-145 -->

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
    trust: TrustTier | str = "working",
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
    trust: TrustTier | str = "working",
    tenant_id: str | None = None,
    **kwargs,
) -> list[Resource]
```

<!-- VERIFIED: vault.py:466-491 -->

### get()

```python
vault.get(resource_id: str) -> Resource
```

### get_content()

```python
vault.get_content(resource_id: str) -> str
```

Reassembles chunks in order to return the full text content.

<!-- VERIFIED: vault.py:406-420 -->

### list()

```python
vault.list(
    *,
    tenant_id: str | None = None,
    trust: TrustTier | str | None = None,
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

### update()

```python
vault.update(
    resource_id: str,
    *,
    name: str | None = None,
    trust: TrustTier | str | None = None,
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
    trust_min: TrustTier | str | None = None,
    layer: MemoryLayer | str | None = None,
    collection: str | None = None,
    as_of: date | None = None,          # Point-in-time
    deduplicate: bool = True,           # One result per resource
    explain: bool = False,              # Include scoring breakdown
) -> list[SearchResult]
```

<!-- VERIFIED: vault.py:558-648 -->

### search_with_facets()

```python
vault.search_with_facets(query: str, **kwargs) -> dict[str, Any]
```

Returns `{"results": [...], "total": N, "facets": {"trust_tier": {...}, "resource_type": {...}}}`.

<!-- VERIFIED: vault.py:650-687 -->

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

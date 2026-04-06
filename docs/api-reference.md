# API Reference

Complete Python SDK for qp-vault. Both `Vault` (sync) and `AsyncVault` (async) share the same interface.

## Vault / AsyncVault

### Constructor

```python
Vault(
    path: str | Path,
    *,
    storage: StorageBackend | None = None,      # Default: SQLite
    embedder: EmbeddingProvider | None = None,   # Default: None (no embeddings)
    auditor: AuditProvider | None = None,        # Default: LogAuditor (JSON lines)
    parsers: list[ParserProvider] | None = None,
    policies: list[PolicyProvider] | None = None,
    config: VaultConfig | None = None,
    plugins_dir: str | Path | None = None,       # Air-gap plugin directory
)
```

<!-- VERIFIED: vault.py:126-137 — AsyncVault.__init__ signature -->

### Factory Methods

```python
Vault.from_postgres(dsn: str, **kwargs) -> Vault
Vault.from_config(config_path: str | Path) -> Vault
```

<!-- VERIFIED: vault.py:755-768 — factory methods in sync Vault -->

---

## Resource Operations

### add()

```python
vault.add(
    source: str | Path | bytes,
    *,
    name: str | None = None,                          # Auto-detected from file path
    trust: TrustTier | str = "working",
    classification: DataClassification | str = "internal",
    layer: MemoryLayer | str | None = None,
    collection: str | None = None,
    tags: list[str] | None = None,                    # Max 50 tags, 100 chars each
    metadata: dict[str, Any] | None = None,           # Max 100 keys, alphanumeric
    lifecycle: Lifecycle | str = "active",
    valid_from: date | None = None,
    valid_until: date | None = None,
) -> Resource
```

Adds a resource. `source` can be a file path (str or Path), text content (str), or bytes. The ingest pipeline: parse, chunk, hash (SHA3-256 CID), embed (if provider set), store, audit.

<!-- VERIFIED: vault.py:194-316 — add() full signature and pipeline -->

**Raises:** `VaultError` if invalid enum values, name too long, tags exceed limits, metadata keys invalid, content exceeds max_file_size_mb.

### get()

```python
vault.get(resource_id: str) -> Resource
```

**Raises:** `VaultError` if not found.

### list()

```python
vault.list(
    *,
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

Deleted resources are excluded by default. Pass `status="deleted"` to list trash.

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

Only provided fields are updated. Trust changes emit a `TRUST_CHANGE` audit event.

### delete()

```python
vault.delete(resource_id: str, *, hard: bool = False) -> None
```

Soft delete (default): sets status to `deleted`, preserves data. Hard delete: removes from storage permanently.

---

## Search

### search()

```python
vault.search(
    query: str,
    *,
    top_k: int = 10,
    threshold: float = 0.0,
    trust_min: TrustTier | str | None = None,
    layer: MemoryLayer | str | None = None,
    collection: str | None = None,
    as_of: date | None = None,            # Point-in-time search
) -> list[SearchResult]
```

Returns results ranked by: `(vector_weight * vector_sim + text_weight * text_rank) * trust_weight * freshness_decay`

<!-- VERIFIED: vault.py:339-385 — search() method -->

**SearchResult fields:**

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | str | Chunk identifier |
| `resource_id` | str | Parent resource |
| `resource_name` | str | Display name |
| `content` | str | Chunk text |
| `vector_similarity` | float | Cosine similarity (0-1) |
| `text_rank` | float | Full-text match score |
| `trust_weight` | float | From trust tier (1.5/1.0/0.7/0.25) |
| `freshness` | float | Decay factor |
| `relevance` | float | Composite score |
| `trust_tier` | TrustTier | Resource trust tier |
| `cid` | str | Chunk content ID (SHA3-256) |

---

## Lifecycle

### transition()

```python
vault.transition(
    resource_id: str,
    target: Lifecycle | str,
    *,
    reason: str | None = None,
) -> Resource
```

**Raises:** `LifecycleError` if the transition is not valid. See [Lifecycle](lifecycle.md) for the state machine.

### supersede()

```python
vault.supersede(old_id: str, new_id: str) -> tuple[Resource, Resource]
```

Marks old resource as SUPERSEDED, links to successor. Returns (old, new).

### expiring()

```python
vault.expiring(*, days: int = 90) -> list[Resource]
```

Returns ACTIVE resources with `valid_until` within the given window.

### chain()

```python
vault.chain(resource_id: str) -> list[Resource]
```

Returns the full supersession chain in chronological order (oldest first). Max chain length: 1000 (cycle protection).

<!-- VERIFIED: lifecycle_engine.py:205-248 — chain() with max_length guard -->

---

## Verification

### verify()

```python
# Single resource
vault.verify(resource_id: str) -> VerificationResult

# Entire vault
vault.verify() -> VaultVerificationResult
```

Single resource: recomputes SHA3-256 CIDs for all chunks and compares with stored hashes.

Full vault: computes Merkle root over all resource hashes.

### export_proof()

```python
vault.export_proof(resource_id: str) -> MerkleProof
```

Exports a Merkle proof that an auditor can verify independently. Contains the resource hash, Merkle root, and sibling hashes along the path.

<!-- VERIFIED: vault.py:553-584 — export_proof with compute_merkle_proof -->

---

## Memory Layers

### layer()

```python
vault.layer(name: MemoryLayer | str) -> LayerView
```

Returns a scoped view with per-layer defaults. See [Memory Layers](memory-layers.md).

```python
ops = vault.layer("operational")
await ops.add("runbook.md")      # Auto: trust=WORKING, boost=1.5x
await ops.search("deploy")       # Scoped to operational layer
```

---

## Health

### health()

```python
vault.health() -> HealthScore
```

**HealthScore fields:**

| Field | Type | Description |
|-------|------|-------------|
| `overall` | float | Composite 0-100 |
| `coherence` | float | Absence of duplicates |
| `freshness` | float | Average document freshness |
| `uniqueness` | float | Content diversity |
| `connectivity` | float | Resources in collections / with tags |
| `trust_alignment` | float | Trust tier distribution quality |
| `issue_count` | int | Total detected issues |
| `resource_count` | int | Total resources assessed |

<!-- VERIFIED: integrity/detector.py:113-170 — all HealthScore components -->

---

## Status

### status()

```python
vault.status() -> dict
```

Returns:
```python
{
    "total_resources": int,
    "by_status": {"indexed": N, "pending": N, ...},
    "by_trust_tier": {"canonical": N, "working": N, ...},
    "by_layer": {"operational": N, "strategic": N, ...},
    "layer_details": {
        "operational": {"resource_count": N, "default_trust": "working", ...},
        ...
    },
    "vault_path": str,
    "backend": "sqlite",
}
```

---

## Plugin Registration

```python
vault.register_embedder(embedder: EmbeddingProvider) -> None
vault.register_parser(parser: ParserProvider) -> None
vault.register_policy(policy: PolicyProvider) -> None
```

See [Plugin Development](plugins.md).

---

## Enums

| Enum | Values |
|------|--------|
| `TrustTier` | `canonical`, `working`, `ephemeral`, `archived` |
| `DataClassification` | `public`, `internal`, `confidential`, `restricted` |
| `ResourceType` | `document`, `image`, `audio`, `video`, `note`, `code`, `spreadsheet`, `transcript`, `other` |
| `ResourceStatus` | `pending`, `processing`, `indexed`, `error`, `deleted` |
| `Lifecycle` | `draft`, `review`, `active`, `superseded`, `expired`, `archived` |
| `MemoryLayer` | `operational`, `strategic`, `compliance` |
| `EventType` | `create`, `update`, `delete`, `restore`, `trust_change`, `classification_change`, `lifecycle_transition`, `supersede`, `verify`, `search` |

<!-- VERIFIED: enums.py:1-122 — all enum definitions -->

---

## Exceptions

| Exception | When |
|-----------|------|
| `VaultError` | Base exception. Resource not found, invalid parameters. |
| `StorageError` | Database operation failed. |
| `VerificationError` | Content integrity check failed. |
| `LifecycleError` | Invalid lifecycle transition. |
| `PolicyError` | Policy evaluation denied operation. |
| `ChunkingError` | Text chunking failed. |
| `ParsingError` | File parsing failed. |

<!-- VERIFIED: exceptions.py:1-25 — all 7 exception types -->

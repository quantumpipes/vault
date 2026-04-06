# Architecture

qp-vault follows a layered architecture with Protocol-based extensibility. Every component is replaceable without changing the core logic.

## Package Structure

```
src/qp_vault/
    vault.py              Vault (sync) + AsyncVault (async) main classes
    models.py             Pydantic domain models
    enums.py              TrustTier, Lifecycle, MemoryLayer, etc.
    protocols.py          StorageBackend, EmbeddingProvider, AuditProvider, etc.
    config.py             VaultConfig with TOML loading
    exceptions.py         VaultError hierarchy

    core/
        chunker.py        Semantic text chunking (token-aware, overlap)
        hasher.py         SHA3-256 CID computation, Merkle trees
        search_engine.py  Trust-weighted scoring + freshness decay
        resource_manager.py  Full ingest pipeline
        lifecycle_engine.py  State machine, supersession, expiration
        layer_manager.py  Memory layers: OPERATIONAL, STRATEGIC, COMPLIANCE

    storage/
        sqlite.py         SQLite + FTS5 (default, zero-config)
        postgres.py       PostgreSQL + pgvector + pg_trgm (production)

    processing/
        text_parser.py    30+ text formats (zero deps)
        transcript_parser.py  WebVTT + SRT with speaker attribution

    audit/
        log_auditor.py    JSON lines fallback (built-in)
        capsule_auditor.py  qp-capsule integration (optional)

    integrity/
        detector.py       Staleness, duplicates, orphans, health scoring

    plugins/
        registry.py       Plugin discovery (entry_points + plugins_dir)
        decorators.py     @embedder, @parser, @policy

    integrations/
        fastapi_routes.py  Ready-made REST API routes

    cli/
        main.py           Typer CLI: vault init, add, search, verify, etc.
```

<!-- VERIFIED: actual directory listing matches this structure -->

## Layers

```
+-------------------------------------------------------------------+
|  PUBLIC API         Vault (sync) / AsyncVault (async)             |
+-------------------------------------------------------------------+
|  CORE LAYER         ResourceManager, SearchEngine, LifecycleEngine|
|                     VerificationEngine, LayerManager              |
+-------------------------------------------------------------------+
|  PROTOCOL LAYER     StorageBackend, EmbeddingProvider,            |
|                     AuditProvider, ParserProvider, PolicyProvider  |
+-------------------------------------------------------------------+
|  STORAGE LAYER      SQLite + FTS5  |  PostgreSQL + pgvector       |
+-------------------------------------------------------------------+
```

## Protocol Interfaces

All extensibility uses Python Protocols (structural subtyping). You don't inherit from base classes; you implement the interface.

<!-- VERIFIED: protocols.py:73-122 — all 5 Protocols with @runtime_checkable -->

### StorageBackend

```python
class StorageBackend(Protocol):
    async def initialize(self) -> None: ...
    async def store_resource(self, resource: Resource) -> str: ...
    async def get_resource(self, resource_id: str) -> Resource | None: ...
    async def list_resources(self, filters: ResourceFilter) -> list[Resource]: ...
    async def update_resource(self, resource_id: str, updates: ResourceUpdate) -> Resource: ...
    async def delete_resource(self, resource_id: str, *, hard: bool = False) -> None: ...
    async def store_chunks(self, resource_id: str, chunks: list[Chunk]) -> None: ...
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...
    async def get_all_hashes(self) -> list[tuple[str, str]]: ...
    async def get_chunks_for_resource(self, resource_id: str) -> list[Chunk]: ...
    async def restore_resource(self, resource_id: str) -> Resource: ...
```

### EmbeddingProvider

```python
class EmbeddingProvider(Protocol):
    @property
    def dimensions(self) -> int: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

### AuditProvider

```python
class AuditProvider(Protocol):
    async def record(self, event: VaultEvent) -> str: ...
```

### ParserProvider

```python
class ParserProvider(Protocol):
    @property
    def supported_extensions(self) -> set[str]: ...
    async def parse(self, path: Path) -> ParseResult: ...
```

### PolicyProvider

```python
class PolicyProvider(Protocol):
    async def evaluate(self, resource: Resource, action: str, context: dict) -> PolicyResult: ...
```

## Data Flow

### Ingest Pipeline

```
Source (str/Path/bytes)
    |
    v
[Input Validation]  enum checks, name sanitization, null byte stripping, size limit
    |
    v
[Parser Selection]  Match by extension, or read as text
    |
    v
[Semantic Chunking]  512 tokens target, 50 token overlap, section detection
    |
    v
[CID Computation]   SHA3-256 hash per chunk
    |
    v
[Embedding]          EmbeddingProvider (if configured, else skipped)
    |
    v
[Resource Hash]      SHA3-256 over sorted chunk CIDs
    |
    v
[Storage]            StorageBackend.store_resource() + store_chunks()
    |
    v
[Audit Event]        VaultEvent(CREATE) -> AuditProvider.record()
```

<!-- VERIFIED: resource_manager.py:94-197 — add() method pipeline -->

### Search Pipeline

```
Query String
    |
    v
[Query Embedding]    EmbeddingProvider.embed([query]) if available
    |
    v
[FTS5 / Trigram]     Full-text matching in storage backend
    |
    v
[Vector Cosine]      Cosine similarity against chunk embeddings
    |
    v
[Raw Score]          0.7 * vector_sim + 0.3 * text_rank
    |
    v
[Trust Weighting]    raw_score * trust_weight (1.5/1.0/0.7/0.25)
    |
    v
[Freshness Decay]    * exp(-age_days / half_life * ln(2))
    |
    v
[Ranked Results]     Sorted by composite relevance
```

<!-- VERIFIED: search_engine.py:62-91 — apply_trust_weighting -->

## Storage Backends

### SQLite (Default)

Zero-config embedded storage. Uses WAL mode for concurrent safety, FTS5 for full-text search, and brute-force cosine similarity for vector search (suitable for vaults under 100K chunks).

Database: `{vault_path}/vault.db`

<!-- VERIFIED: sqlite.py:152-156 — WAL mode, foreign keys enabled -->

### PostgreSQL (Production)

Uses pgvector extension for HNSW-indexed vector search and pg_trgm for trigram matching. Suitable for millions of chunks.

```python
vault = Vault.from_postgres("postgresql://user:pass@localhost/mydb")
```

<!-- VERIFIED: postgres.py:17-21 — asyncpg import, class definition -->

## Configuration

All settings are in `VaultConfig` and can be set via constructor or TOML file:

```python
from qp_vault.config import VaultConfig

config = VaultConfig(
    chunk_target_tokens=256,      # Smaller chunks
    vector_weight=0.8,            # Weight vector search higher
    text_weight=0.2,
    max_file_size_mb=100,         # Limit file size
    trust_weights={
        "canonical": 2.0,         # Custom trust multiplier
        "working": 1.0,
        "ephemeral": 0.5,
        "archived": 0.1,
    },
)

vault = Vault("./knowledge", config=config)
```

<!-- VERIFIED: config.py:18-86 — VaultConfig fields and defaults -->

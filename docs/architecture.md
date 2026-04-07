# Architecture

qp-vault follows a layered architecture with Protocol-based extensibility. Every component is replaceable without changing the core logic.

## Package Structure

```
src/qp_vault/
    vault.py              Vault (sync) + AsyncVault (async) main classes
    models.py             Pydantic domain models
    enums.py              TrustTier, Lifecycle, MembraneStage, Role, etc.
    protocols.py          StorageBackend, EmbeddingProvider, AuditProvider, etc.
    config.py             VaultConfig with TOML loading
    exceptions.py         VaultError hierarchy with structured codes (VAULT_000-700)
    rbac.py               Role-Based Access Control (READER/WRITER/ADMIN)
    provenance.py         Content provenance attestation service
    adversarial.py        Adversarial content verification
    streaming.py          Real-time VaultEventStream
    telemetry.py          Operation metrics tracking

    core/
        chunker.py        Semantic text chunking (token-aware, overlap)
        hasher.py         SHA3-256 CID computation, Merkle trees
        search_engine.py  Trust-weighted scoring + freshness decay + layer boost
        resource_manager.py  Full ingest pipeline
        lifecycle_engine.py  State machine, supersession, expiration
        layer_manager.py  Memory layers: OPERATIONAL, STRATEGIC, COMPLIANCE

    storage/
        sqlite.py         SQLite + FTS5 (default, zero-config)
        postgres.py       PostgreSQL + pgvector + pg_trgm (production)

    membrane/
        pipeline.py       MembranePipeline: multi-stage content screening
        innate_scan.py    Pattern-based detection (regex blocklists)
        release_gate.py   Risk-proportionate gating decision

    encryption/
        aes_gcm.py        AES-256-GCM symmetric (FIPS 197)
        ml_kem.py         ML-KEM-768 key encapsulation (FIPS 203)
        ml_dsa.py         ML-DSA-65 digital signatures (FIPS 204)
        hybrid.py         ML-KEM-768 + AES-256-GCM combined
        fips_kat.py       FIPS Known Answer Tests
        zeroize.py        Secure key erasure (ctypes memset)

    embeddings/
        noop.py           NoopEmbedder (text-only search, explicit)
        sentence.py       SentenceTransformerEmbedder (local, air-gap)
        openai.py         OpenAIEmbedder (cloud)

    processing/
        text_parser.py    30+ text formats (zero deps)
        transcript_parser.py  WebVTT + SRT with speaker attribution
        docling_parser.py 25+ document formats via Docling

    audit/
        log_auditor.py    JSON lines fallback (built-in)
        capsule_auditor.py  qp-capsule integration (typed Section objects)

    integrity/
        detector.py       Staleness, duplicates, near-duplicates, contradictions, health

    plugins/
        registry.py       Plugin discovery (entry_points + plugins_dir + manifest hash)
        decorators.py     @embedder, @parser, @policy

    integrations/
        fastapi_routes.py  22+ REST endpoints with input validation

    cli/
        main.py           15 Typer CLI commands
```

<!-- VERIFIED: actual directory listing matches this structure -->

## Layers

```
+-------------------------------------------------------------------+
|  PUBLIC API + RBAC  Vault (sync) / AsyncVault (async) + Roles     |
+-------------------------------------------------------------------+
|  MEMBRANE           Content screening before indexing              |
+-------------------------------------------------------------------+
|  CORE LAYER         ResourceManager, SearchEngine, LifecycleEngine|
|                     VerificationEngine, LayerManager              |
+-------------------------------------------------------------------+
|  PROTOCOL LAYER     StorageBackend, EmbeddingProvider,            |
|                     AuditProvider, ParserProvider, PolicyProvider  |
+-------------------------------------------------------------------+
|  ENCRYPTION         AES-256-GCM | ML-KEM-768 | ML-DSA-65 | Hybrid|
+-------------------------------------------------------------------+
|  STORAGE            SQLite + FTS5  |  PostgreSQL + pgvector       |
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
[RBAC Check]        Permission check (WRITER or ADMIN required)
    |
    v
[Input Validation]  enum checks, name sanitization, null byte stripping, size limit
    |
    v
[Membrane Screen]   Innate scan (regex blocklist) -> Release gate (pass/quarantine)
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
[Layer Boost]        * layer_boost (1.5x for OPERATIONAL)
    |
    v
[Deduplication]      One result per resource (best chunk)
    |
    v
[Pagination]         offset + top_k
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

Additional config fields added in v0.6-v0.13:

```python
config = VaultConfig(
    max_resources_per_tenant=1000,    # Per-tenant quota (v0.11)
    query_timeout_ms=30000,           # 30s query timeout (v0.13)
    health_cache_ttl_seconds=30,      # Cache health responses (v0.13)
)
```

<!-- VERIFIED: config.py:18-86 — VaultConfig fields and defaults -->

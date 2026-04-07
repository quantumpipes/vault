# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.14.0] - 2026-04-06

### Added
- **Tenant lock enforcement**: `Vault(path, tenant_id="x")` now actively rejects operations with mismatched `tenant_id` and auto-injects the locked tenant when none is provided
- **Query timeouts**: `_with_timeout()` wraps storage search with `asyncio.wait_for` and proper task cancellation on timeout. PostgreSQL pool gets `command_timeout` parameter
- **Health/status response caching**: TTL-based cache (default 30s via `health_cache_ttl_seconds`) avoids full vault scans on repeated calls; cache invalidated on add/update/delete
- **Atomic tenant quotas**: `count_resources()` Protocol method replaces the previous list+offset approach, eliminating TOCTOU race condition

### Security
- **Plugin manifest required**: `manifest.json` is now mandatory when `verify_hashes=True` (default). Files not listed in manifest are rejected. Entire directory skipped if manifest missing
- **FastAPI validation**: `limit` (1-1000), `offset` (0-1M), `content` max_length (500MB) validated at API boundary
- **Path traversal protection**: `add()` resolves paths and rejects those containing `..`
- **ReDoS protection**: Membrane innate scan truncates content to 500KB before regex matching
- **CLI error sanitization**: `_safe_error_message()` returns structured error codes, never raw exception details
- **Unicode normalization**: `_sanitize_name()` applies NFC normalization to prevent homograph collisions
- **Timeout cancellation**: Timed-out tasks are cancelled (not left running in background)

### Fixed
- **Sync Vault missing tenant_id/role**: `Vault.__init__` now accepts and passes `tenant_id` and `role` to `AsyncVault` (was silently ignoring both)
- **mypy strict compliance**: 0 errors across 54 source files without disabling checks
- **Abstraction leak**: `create_collection()` and `list_collections()` now use Protocol methods instead of directly accessing `_get_conn()`
- **None-safety**: Added null checks before `.value` access in resource_manager and search_engine

### Changed
- All magic numbers extracted to named constants
- All 16 StorageBackend Protocol methods have docstrings
- Error message punctuation normalized

## [0.13.0] - 2026-04-07

### Added
- **RBAC framework**: Role enum (READER, WRITER, ADMIN) with permission matrix. Enforced at Vault API boundary.
- **Key zeroization**: `zeroize()` function using ctypes memset for secure key erasure
- **FIPS Known Answer Tests**: `run_all_kat()` for SHA3-256 and AES-256-GCM self-testing
- **Structured error codes**: All exceptions have machine-readable codes (VAULT_000 through VAULT_700)
- **Query timeout config**: `query_timeout_ms` in VaultConfig (default 30s)
- **Health response caching**: `health_cache_ttl_seconds` in VaultConfig (default 30s)

### Security
- RBAC permission checks on all Vault methods
- PermissionError (VAULT_700) for unauthorized operations

## [0.12.0] - 2026-04-06

### Added
- **Post-quantum cryptography (delivered)**:
  - `MLKEMKeyManager` — ML-KEM-768 key encapsulation (FIPS 203)
  - `MLDSASigner` — ML-DSA-65 digital signatures (FIPS 204)
  - `HybridEncryptor` — ML-KEM-768 + AES-256-GCM hybrid encryption
  - `[pq]` installation extra: `pip install qp-vault[pq]`
- **Input bounds**: `top_k` capped at 1000, `threshold` range 0-1, query max 10K chars
- **Batch limits**: max 100 items per `/batch` request
- **Plugin hash verification**: `manifest.json` with SHA3-256 hashes in plugins_dir
- **Tenant-locked vault**: `Vault(path, tenant_id="x")` enforces single-tenant scope

### Security
- SearchRequest Pydantic validators prevent unbounded parameter attacks
- Plugin files verified against manifest before execution

## [0.11.0] - 2026-04-06

### Added
- **Complete CLI**: 8 new commands (content, replace, supersede, collections, provenance, export, health, list, delete, transition, expiring)
- **Search faceting**: `vault.search_with_facets()` returns results + facet counts by trust tier, resource type, classification
- **FastAPI parity**: 7 new endpoints (content, provenance, collections CRUD, faceted search, batch, export)
- **Per-tenant quotas**: `config.max_resources_per_tenant` enforced in `vault.add()`
- **Missing storage indexes**: `data_classification`, `resource_type` in SQLite and PostgreSQL

### Changed
- CLI now has 15 commands (complete surface)
- FastAPI now has 22+ endpoints (complete surface)

## [0.10.0] - 2026-04-06

### Added
- **Search intelligence**: deduplication (one result per resource), pagination offset, explain mode (scoring breakdown)
- **Knowledge self-healing**: semantic near-duplicate detection, contradiction detection (trust/lifecycle conflicts)
- **Real-time event streaming**: VaultEventStream for subscribing to vault mutations
- **Telemetry**: VaultTelemetry with operation counters, latency, error rates
- **Per-resource health**: vault.health(resource_id) for individual quality assessment
- **Import/export**: vault.export_vault(path) and vault.import_vault(path) for portable vaults

### Removed
- `[atlas]` extra (no implementation; removed to avoid confusion)

## [0.9.0] - 2026-04-06

### Added
- **Content Immune System (CIS)**: Multi-stage content screening pipeline
  - Innate scan: pattern-based detection (prompt injection, jailbreak, XSS blocklists)
  - Release gate: risk-proportionate gating (pass/quarantine/reject)
  - Wired into `vault.add()`: content screened before indexing
  - Quarantined resources get `ResourceStatus.QUARANTINED`
- **New CLI commands**: `vault health`, `vault list`, `vault delete`, `vault transition`, `vault expiring`
- `vault.add_batch(sources)` for bulk import
- PostgreSQL schema parity: `adversarial_status`, `tenant_id`, `provenance` table, missing indexes

## [0.8.0] - 2026-04-06

### Added
- **Encryption at rest**: `AESGCMEncryptor` class (AES-256-GCM, FIPS 197). Install: `pip install qp-vault[encryption]`
- **Built-in embedding providers**:
  - `NoopEmbedder` for explicit text-only search
  - `SentenceTransformerEmbedder` for local/air-gap embedding (`pip install qp-vault[local]`)
  - `OpenAIEmbedder` for cloud embedding (`pip install qp-vault[openai]`)
- **Docling parser**: 25+ format document processing (PDF, DOCX, PPTX, etc.). Install: `pip install qp-vault[docling]`
- `PluginRegistry.fire_hooks()` — plugin lifecycle hooks are now invoked
- `[local]` and `[openai]` installation extras

### Changed
- README updated: encryption and docling marked as delivered (were "planned")

## [0.7.0] - 2026-04-06

### Added
- **Multi-tenancy**: `tenant_id` parameter on `add()`, `list()`, `search()`, and all public methods
- `tenant_id` column in SQLite and PostgreSQL storage schemas with index
- Tenant-scoped search: queries filter by `tenant_id` when provided
- `vault.create_collection()` and `vault.list_collections()` — Collection CRUD
- Auto-detection of qp-capsule: if installed, `CapsuleAuditor` is used automatically (no manual wiring)

## [0.6.0] - 2026-04-06

### Added
- `vault.get_content(resource_id)` — retrieve full text content (reassembles chunks)
- `vault.replace(resource_id, new_content)` — atomic content replacement with auto-supersession
- `vault.get_provenance(resource_id)` — retrieve provenance records for a resource
- `vault.set_adversarial_status(resource_id, status)` — persist adversarial verification status
- `adversarial_status` column in storage schemas (persisted, was RAM-only)
- `provenance` table in storage schemas (persisted, was RAM-only)
- `updated_at`, `resource_type`, `data_classification` fields on `SearchResult` model
- Layer `search_boost` applied in ranking (OPERATIONAL 1.5x, STRATEGIC 1.0x)

### Fixed
- **Freshness decay**: was hardcoded to 1.0, now computed from `updated_at` with per-tier half-life
- **Layer search_boost**: defined per layer but never applied in `apply_trust_weighting()`

### Changed
- README badges corrected: removed undelivered encryption/FIPS claims, fixed test count
- Encryption (`[encryption]`) and docling (`[docling]`) extras marked as "planned v0.8"

## [0.5.0] - 2026-04-06

### Added
- Plugin system with `@embedder`, `@parser`, `@policy` decorators
- Air-gap plugin loading via `--plugins-dir` (drop .py files)
- Entry point discovery for installed plugin packages
- FastAPI routes via `create_vault_router()` (`[fastapi]` extra)
- All REST endpoints: resources CRUD, search, verify, health, lifecycle, proof

## [0.4.0] - 2026-04-06

### Added
- Memory layers: OPERATIONAL, STRATEGIC, COMPLIANCE with per-layer defaults
- `vault.layer(MemoryLayer.OPERATIONAL)` returns scoped LayerView
- COMPLIANCE layer audits every read operation
- Integrity detection: staleness scoring, duplicate detection, orphan detection
- `vault.health()` composite score (0-100): coherence, freshness, uniqueness, connectivity
- `vault.status()` includes `layer_details` breakdown

## [0.3.0] - 2026-04-06

### Added
- Knowledge lifecycle state machine: DRAFT, REVIEW, ACTIVE, SUPERSEDED, EXPIRED, ARCHIVED
- `vault.transition()`, `vault.supersede()`, `vault.chain()`, `vault.expiring()`
- Temporal validity: `valid_from`, `valid_until` on resources
- `vault.export_proof()` for Merkle proof export (auditor-verifiable)
- Supersession chain cycle protection (max_length=1000)

## [0.2.0] - 2026-04-06

### Added
- `vault` CLI tool: init, add, search, inspect, status, verify
- Capsule audit integration (`[capsule]` extra)
- PostgreSQL + pgvector + pg_trgm storage backend (`[postgres]` extra)
- WebVTT and SRT transcript parsers with speaker attribution
- `Vault.from_postgres()` and `Vault.from_config()` factory methods

### Security
- FTS5 query sanitization (prevents injection via special characters)
- Parameterized SQL queries in PostgreSQL backend (no string interpolation)

## [0.1.0] - 2026-04-05

### Added
- Initial release
- `Vault` (sync) and `AsyncVault` (async) main classes
- 8 Pydantic domain models: Resource, Chunk, Collection, SearchResult, VaultEvent, VerificationResult, VaultVerificationResult, MerkleProof, HealthScore
- 10 enumerations: TrustTier, DataClassification, ResourceType, ResourceStatus, Lifecycle, MemoryLayer, EventType
- 5 Protocol interfaces: StorageBackend, EmbeddingProvider, AuditProvider, ParserProvider, PolicyProvider
- SQLite storage backend with FTS5 full-text search (zero-config default)
- Trust-weighted hybrid search: `relevance = (0.7 * vector + 0.3 * text) * trust_weight * freshness`
- SHA3-256 content-addressed storage (CID per chunk, Merkle root per resource)
- Semantic text chunker (token-aware, overlap, section detection)
- Built-in text parser (30+ file extensions, zero deps)
- JSON lines audit fallback (LogAuditor)
- VaultConfig with TOML loading

### Security
- Input validation: enum values, resource names, tags, metadata
- Path traversal protection (name sanitization, null byte stripping)
- Max file size enforcement (configurable)
- Content null byte stripping on ingest

[unreleased]: https://github.com/quantumpipes/vault/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/quantumpipes/vault/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/quantumpipes/vault/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/quantumpipes/vault/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/quantumpipes/vault/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/quantumpipes/vault/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/quantumpipes/vault/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/quantumpipes/vault/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/quantumpipes/vault/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/quantumpipes/vault/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/quantumpipes/vault/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/quantumpipes/vault/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/quantumpipes/vault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/quantumpipes/vault/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/quantumpipes/vault/releases/tag/v0.1.0

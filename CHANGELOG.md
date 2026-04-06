# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[unreleased]: https://github.com/quantumpipes/vault/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/quantumpipes/vault/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/quantumpipes/vault/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/quantumpipes/vault/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/quantumpipes/vault/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/quantumpipes/vault/releases/tag/v0.1.0

# Security Model

qp-vault's security architecture for v0.15.0.

## Cryptographic Inventory

| Algorithm | Standard | Module | Status |
|-----------|----------|--------|--------|
| SHA3-256 | FIPS 202 | `core/hasher.py` | Implemented |
| AES-256-GCM | FIPS 197 | `encryption/aes_gcm.py` | Implemented |
| ML-KEM-768 | FIPS 203 | `encryption/ml_kem.py` | Implemented |
| ML-DSA-65 | FIPS 204 | `encryption/ml_dsa.py` | Implemented |
| Ed25519 | FIPS 186-5 | Via qp-capsule | Implemented |
| Hybrid (ML-KEM + AES) | FIPS 203+197 | `encryption/hybrid.py` | Implemented |

### Never Used

MD5, SHA1, DES, 3DES, RC4, RSA, Blowfish, ECDSA P-256.

### FIPS Status

Uses FIPS-approved algorithms. Not a FIPS 140-3 validated module (requires formal CMVP evaluation). FIPS Known Answer Tests available via `encryption/fips_kat.py`.

## Access Control (RBAC)

| Role | Permissions |
|------|------------|
| READER | search, get, list, verify, health, status |
| WRITER | + add, update, delete, replace, transition |
| ADMIN | + export, import, create_collection |

Permission denied raises `VaultError` with code `VAULT_700`. See [RBAC](rbac.md).

## Content Screening (Membrane)

Content is screened before indexing:
1. **Innate scan**: Regex blocklist (prompt injection, jailbreak, XSS, code injection)
2. **Release gate**: Pass/quarantine/reject decision

Content that **fails** screening is rejected outright (`VaultError`). Flagged content is stored but quarantined: excluded from search AND `get_content()`. Quarantined resources get `adversarial_status=SUSPICIOUS` persisted to storage. See [Membrane](membrane.md).

<!-- VERIFIED: vault.py:424-460 — FAIL rejects, quarantine blocks get_content -->

## Input Validation

| Input | Validation |
|-------|-----------|
| Trust tier | Must be valid enum value |
| Resource name | Unicode NFC normalized, path traversal stripped, null bytes removed, 255 char limit |
| Source path | Resolved and rejected if `..` detected (path traversal protection) |
| Tags | Max 50 tags, 100 chars each, control chars stripped |
| Metadata keys | Alphanumeric + dash/underscore/dot, max 100 keys |
| Metadata values | Max 10,000 bytes per value |
| Content | Null bytes stripped, max_file_size_mb enforced |
| Search query | FTS5 special chars sanitized, max 10,000 chars |
| top_k | 1-1,000 |
| threshold | 0.0-1.0 |
| Batch | Max 100 items |

## SQL Injection Prevention

All queries use parameterized placeholders (`?` for SQLite, `$N` for PostgreSQL). Column names in dynamic queries come from hardcoded tuples, never user input.

## Plugin Security

Plugins loaded from `plugins_dir` require a `manifest.json` (SHA3-256 hashes) by default. Without a manifest, the entire directory is skipped. Files not listed in the manifest are rejected. Hash mismatches are logged and the plugin is skipped.

<!-- VERIFIED: plugins/registry.py:131-176 — manifest required, unlisted files rejected -->

## Key Management

- Key zeroization via `ctypes.memset` (`encryption/zeroize.py`)
- AES keys: random 256-bit generation per encryptor instance
- ML-KEM-768 and ML-DSA-65 keypairs: generated via liboqs

See [Encryption](encryption.md).

## Audit Trail

Every mutation emits a `VaultEvent`:

| Event | Trigger |
|-------|---------|
| CREATE | Resource added |
| UPDATE | Metadata changed |
| DELETE | Resource deleted |
| RESTORE | Soft-deleted resource restored |
| TRUST_CHANGE | Trust tier changed |
| CLASSIFICATION_CHANGE | Classification changed |
| LIFECYCLE_TRANSITION | Lifecycle state changed |
| SUPERSEDE | Resource superseded |
| MEMBRANE_SCAN | Content screened |
| MEMBRANE_RELEASE | Content released/quarantined |
| MEMBRANE_FLAG | Content flagged |
| ADVERSARIAL_STATUS_CHANGE | Verification status changed |
| SEARCH | Search on COMPLIANCE layer (audit reads) |

## Content Addressing

Every chunk: SHA3-256 CID. Every resource: Merkle root over sorted chunk CIDs. Every vault: Merkle root over all resources. Any modification detected instantly.

## Denial of Service Protection

| Vector | Protection |
|--------|------------|
| Large upload | max_file_size_mb (default 500MB), content max_length 500MB |
| Unbounded queries | Paginated with 50K hard cap |
| Batch flooding | Max 100 items per request |
| Search params | top_k max 1000, query max 10K chars |
| List params | limit 1-1000, offset 0-1M (FastAPI validated) |
| Chain cycles | Max 1000 links |
| FTS5 complexity | Special operators stripped |
| Tenant flooding | Per-tenant quotas (atomic count, no TOCTOU) |
| Query timeout | Configurable query_timeout_ms (default 30s), task cancelled on timeout |
| Health/status abuse | TTL-cached responses (default 30s) |
| Membrane ReDoS | Content truncated to 500KB for regex scanning |

<!-- VERIFIED: vault.py:247-265 — _with_timeout with task cancellation -->
<!-- VERIFIED: membrane/innate_scan.py:69 — 500KB scan limit -->
<!-- VERIFIED: integrations/fastapi_routes.py:140-141 — limit/offset validation -->

## Threat Model

| Threat | Mitigation |
|--------|------------|
| Content tampering | SHA3-256 CIDs + Merkle verification |
| Silent corruption | Content-addressed hashing detects any change |
| Unauthorized access | RBAC (READER/WRITER/ADMIN) |
| Unauthorized trust promotion | Trust changes emit audit event |
| Data exfiltration | DataClassification blocks CONFIDENTIAL/RESTRICTED |
| Prompt injection | Membrane innate scan + quarantine |
| SQL injection | Parameterized queries only |
| Path traversal | Name sanitization + source path resolve rejects `..` |
| Unicode homographs | NFC normalization prevents visually identical collisions |
| CLI information leakage | Structured error codes, no raw exception output |
| FTS5 injection | Query sanitizer strips operators |
| Audit manipulation | Capsule hash-chains are append-only |
| Key compromise | ML-KEM-768 (quantum-resistant) + zeroization |
| Plugin RCE | SHA3-256 manifest hash verification (required) |
| Database eavesdropping | PostgreSQL SSL by default; SQLite 0600 permissions |

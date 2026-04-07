# Security Model

qp-vault's security architecture for v0.13.0.

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

Quarantined resources get `ResourceStatus.QUARANTINED` and are excluded from search. See [Membrane](membrane.md).

## Input Validation

| Input | Validation |
|-------|-----------|
| Trust tier | Must be valid enum value |
| Resource name | Path traversal stripped, null bytes removed, 255 char limit |
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

Plugins loaded from `plugins_dir` are verified against a `manifest.json` containing SHA3-256 hashes before execution. Hash mismatches are logged and the plugin is skipped.

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
| Large upload | max_file_size_mb (default 500MB) |
| Unbounded queries | Paginated with 50K hard cap |
| Batch flooding | Max 100 items per request |
| Search params | top_k max 1000, query max 10K chars |
| Chain cycles | Max 1000 links |
| FTS5 complexity | Special operators stripped |
| Tenant flooding | Per-tenant resource quotas |
| Query timeout | Configurable query_timeout_ms (default 30s) |

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
| Path traversal | Name sanitization strips path components |
| FTS5 injection | Query sanitizer strips operators |
| Audit manipulation | Capsule hash-chains are append-only |
| Key compromise | ML-KEM-768 (quantum-resistant) + zeroization |
| Plugin RCE | SHA3-256 manifest hash verification |

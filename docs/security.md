# Security Model

qp-vault operates under the assumption that the storage layer is adversarial. Every read is verified. Every write is auditable.

## Cryptography

### Algorithms Used

| Purpose | Algorithm | Standard |
|---------|-----------|----------|
| Content hashing | SHA3-256 | FIPS 202 |
| Content IDs | `vault://sha3-256/{hex}` | Custom URI scheme |
| Merkle trees | SHA3-256 internal nodes | Standard Merkle construction |
| Capsule signatures | Ed25519 + ML-DSA-65 | FIPS 186-5, FIPS 204 |
| Encryption at rest | AES-256-GCM + ML-KEM-768 | FIPS 197, FIPS 203 |

<!-- VERIFIED: core/hasher.py:1-7 — uses hashlib.sha3_256 -->

### Never Used

MD5, SHA1, DES, 3DES, RC4, RSA, Blowfish, ECDSA P-256.

## Content-Addressed Storage

Every chunk receives a SHA3-256 Content ID (CID):

```
vault://sha3-256/a1b2c3d4e5f6...
```

Every resource receives a Merkle root computed over its chunk CIDs:

```
            Resource Merkle Root
            /                  \
     hash(c1+c2)          hash(c3+c4)
      /       \             /       \
   CID(c1)  CID(c2)    CID(c3)  CID(c4)
```

This means:
- Identical content always produces the same CID (deduplication)
- Any modification to any chunk changes the resource hash
- Any modification to any resource changes the vault Merkle root
- Auditors can verify a single resource without downloading the entire vault (Merkle proof)

<!-- VERIFIED: core/hasher.py:55-86 — compute_merkle_root -->
<!-- VERIFIED: core/hasher.py:89-120 — compute_merkle_proof -->

## Input Validation

All validation happens at the API boundary (in `vault.py add()`) before data reaches storage:

| Input | Validation | Limit |
|-------|------------|-------|
| Trust tier | Must be valid `TrustTier` enum value | 4 values |
| Classification | Must be valid `DataClassification` enum value | 4 values |
| Lifecycle | Must be valid `Lifecycle` enum value | 6 values |
| Layer | Must be valid `MemoryLayer` enum value | 3 values |
| Resource name | Path components stripped, null bytes removed, control chars removed | 255 chars |
| Tags | Control chars stripped, empty filtered | 50 max, 100 chars each |
| Metadata keys | Alphanumeric + dash + underscore + dot only | 100 keys, 100 chars/key |
| Metadata values | JSON serialized size check | 10,000 bytes/value |
| Content | Null bytes stripped | Configurable max_file_size_mb (default 500) |
| Search queries | FTS5 special chars stripped (`*`, `"`, `()`, etc.) | Prevents FTS5 injection |

<!-- VERIFIED: vault.py:47-90 — _sanitize_name, _sanitize_tags, _validate_metadata -->
<!-- VERIFIED: storage/sqlite.py:119-130 — _sanitize_fts_query -->

Invalid enum values raise `VaultError` with a clear message:

```python
vault.add("content", trust="INVALID")
# VaultError: Invalid parameter: 'INVALID' is not a valid TrustTier
```

## SQL Injection Prevention

All SQL queries use parameterized placeholders:

- SQLite: `?` placeholders for all user-provided values
- PostgreSQL: `$N` placeholders for all user-provided values

Column names in dynamic queries come from hardcoded tuples (compile-time constants), never from user input.

<!-- VERIFIED: sqlite.py:288-291 — field_name tuple is hardcoded -->
<!-- VERIFIED: postgres.py:390-413 — parameterized filter conditions -->

## Path Traversal Prevention

Resource names are sanitized:

1. Backslashes converted to forward slashes (cross-platform)
2. `Path(name).name` strips directory components
3. Null bytes (`\x00`) removed
4. Control characters (`\x01-\x1f`, `\x7f`) removed
5. Leading/trailing dots and spaces stripped
6. `..` and `.` become `"untitled"`
7. Truncated to 255 characters

<!-- VERIFIED: vault.py:49-63 — _sanitize_name implementation -->

## Audit Trail

Every mutation emits a `VaultEvent` to the configured `AuditProvider`:

| Event | Trigger |
|-------|---------|
| `CREATE` | Resource added |
| `UPDATE` | Resource metadata changed |
| `DELETE` | Resource deleted (soft or hard) |
| `RESTORE` | Soft-deleted resource restored |
| `TRUST_CHANGE` | Trust tier changed |
| `LIFECYCLE_TRANSITION` | Lifecycle state changed |
| `SUPERSEDE` | Resource superseded by newer version |
| `SEARCH` | Search on COMPLIANCE layer (audit reads) |

<!-- VERIFIED: enums.py:109-121 — EventType enum -->

### LogAuditor (Default)

Writes JSON lines to `{vault_path}/audit.jsonl`. File I/O runs in a thread executor to avoid blocking async code.

<!-- VERIFIED: audit/log_auditor.py:39-63 — run_in_executor pattern -->

### CapsuleAuditor (Optional)

With `pip install qp-vault[capsule]`, every event creates a cryptographically sealed Capsule (hash-chained, Ed25519 + ML-DSA-65 dual-signed).

## Denial of Service Protection

| Vector | Protection |
|--------|------------|
| Large file upload | `max_file_size_mb` config (default 500MB) |
| Unbounded list queries | Paginated with 50K hard cap |
| Supersession chain cycles | Max chain length 1000 |
| FTS5 query complexity | Special operators stripped |
| Very long strings as paths | Strings > 4096 chars skip `Path.exists()` check |

<!-- VERIFIED: vault.py:297-303 — max file size enforcement -->
<!-- VERIFIED: vault.py:619-631 — _list_all_bounded with hard_cap=50000 -->
<!-- VERIFIED: lifecycle_engine.py:226-232 — chain max_length guard -->

## Threat Model

| Threat | Category | Mitigation |
|--------|----------|------------|
| Content tampering | Tampering | SHA3-256 CIDs + Merkle verification on read |
| Silent data corruption | Tampering | Content-addressed hashing detects any change |
| Unauthorized trust promotion | Elevation | Trust changes emit auditable VaultEvent |
| Data exfiltration via search | Info Disclosure | DataClassification blocks CONFIDENTIAL/RESTRICTED from cloud |
| Prompt injection via stored docs | Tampering | Trust tiers reduce weight of untrusted sources |
| SQL injection | Injection | Parameterized queries only |
| Path traversal | Injection | Name sanitization strips path components |
| FTS5 injection | Injection | Query sanitizer strips operators |
| Audit trail manipulation | Repudiation | Capsule hash-chains are append-only |

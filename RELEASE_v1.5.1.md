# Security Patch: Adversarial Status Persistence

Fixes the last remaining gap from the Wizard security audit. Adversarial verification status now survives process restarts.

## What Changed

- **Adversarial status persistence (FIX-4)**: `AdversarialVerifier.get_status()` now falls back to the storage backend when the in-memory cache misses. Previously, all resources reverted to `UNVERIFIED` on restart, losing human-reviewed `VERIFIED` and `SUSPICIOUS` classifications.

## What Was Already Fixed

The other 6 items from the Wizard security gap analysis were resolved in prior releases:

| Fix | Status | Release |
|-----|--------|---------|
| FIX-1: Quarantine blocks direct retrieval | Already fixed | v1.3.0+ |
| FIX-2: Classification enforcement on cloud embedders | Already fixed | v1.3.0+ |
| FIX-3: Freshness decay activation | Already fixed | v1.3.0+ |
| FIX-4: Adversarial status persistence | **Fixed this release** | v1.5.1 |
| FIX-5: PostgreSQL SSL enforcement | Already fixed | v1.3.0+ |
| FIX-6: Export/import content roundtrip | Already fixed | v1.3.0+ |
| FIX-7: Provenance auto-verify after self-signing | Already fixed | v1.3.0+ |

## Stats

- 4 new tests
- Security: 100/100 (all 7 Wizard audit gaps resolved)
- 0 breaking changes

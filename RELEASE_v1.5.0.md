# The Reactive Vault

Event subscriptions, reprocessing, text-only search fallback, name-based lookup, and 8 new REST endpoints. Ready for Core integration.

## New Features

- **Event Subscription**: `vault.subscribe(callback)` for real-time mutation events (CREATE, UPDATE, DELETE, LIFECYCLE_TRANSITION). Sync and async callbacks. 5-second timeout, 100-subscriber cap, error isolation. Returns unsubscribe function.
- **Reprocess**: `vault.reprocess(resource_id)` re-chunks and re-embeds when embedding models change. Preserves content, regenerates chunks.
- **Text-Only Search Fallback**: `vault.search()` auto-degrades to text-only when no embedder is configured. Search works day one.
- **Find By Name**: `vault.find_by_name(name)` case-insensitive lookup across the vault.
- **8 New REST Endpoints**: reprocess, grep, find by name, diff, get multiple, adversarial status, import, batch retrieval. 30 total endpoints.

## Security Hardening

- `assert` replaced with `if/raise` (survives `-O` bytecode)
- Async callback timeout (5s) prevents event loop blocking
- Subscriber cap (100) prevents memory exhaustion
- Adversarial status allowlist validation
- Import endpoint path traversal guard
- Resource ID type coercion
- RBAC enforcement on all new methods
- Score: 100/100 (bandit clean, pip-audit clean)

## Stats

- 117 new tests (871+ total)
- 8 new REST endpoints (30 total)
- 3 docs updated (api-reference, fastapi, streaming)
- 0 breaking changes

# Streaming & Telemetry

Real-time event streaming and operation telemetry for autonomous AI systems.

## Event Subscription (Recommended)

The simplest way to react to vault mutations. Register a callback directly on the vault instance:

```python
from qp_vault import AsyncVault, VaultEvent

vault = AsyncVault("./knowledge")

def on_change(event: VaultEvent) -> None:
    print(f"{event.event_type}: {event.resource_name}")
    if event.event_type.value == "create":
        trigger_indexing(event.resource_id)

unsub = vault.subscribe(on_change)

# Every mutation (add, update, delete, transition, reprocess) fires the callback
await vault.add("New document", name="report.md")
# Output: create: report.md

# Stop receiving events
unsub()
```

Async callbacks are also supported:

```python
async def on_change_async(event: VaultEvent) -> None:
    await notify_downstream(event)

vault.subscribe(on_change_async)
```

**Key behaviors:**
- Multiple subscribers are independent
- Errors in callbacks are logged, never propagated
- Calling `unsub()` twice is safe (no error)
- Events are delivered synchronously in mutation order

<!-- VERIFIED: vault.py:289-336 — subscribe + _notify_subscribers -->

## Event Streaming (Advanced)

For async-iterator consumption patterns (e.g., WebSocket broadcasting), use `VaultEventStream`:

```python
from qp_vault import AsyncVault
from qp_vault.streaming import VaultEventStream

stream = VaultEventStream()
vault = AsyncVault("./knowledge", auditor=stream)

# Subscribe and react to events
async for event in stream.subscribe():
    print(f"{event.event_type}: {event.resource_name}")
```

<!-- VERIFIED: streaming.py:20-89 — VaultEventStream class -->

### Replay History

```python
# Replay recent events before going live
async for event in stream.subscribe(replay=True):
    process(event)
```

### Stream Properties

```python
stream.history          # Recent events (bounded buffer)
stream.subscriber_count # Number of active subscribers
```

## Telemetry

Track operation performance for monitoring.

```python
from qp_vault.telemetry import VaultTelemetry

telemetry = VaultTelemetry()

# Track with context manager
with telemetry.track("search"):
    results = vault.search("query")

# Or record manually
telemetry.record("add", 42.5)  # 42.5ms
telemetry.record("add", 37.5, error=True)

# Get metrics
m = telemetry.get("search")
print(f"Count: {m.count}, Avg: {m.avg_duration_ms}ms, Errors: {m.errors}")

# Summary of all operations
print(telemetry.summary())
# {"search": {"count": 10, "errors": 0, "avg_ms": 15.2}, ...}
```

<!-- VERIFIED: telemetry.py:39-105 — VaultTelemetry class -->

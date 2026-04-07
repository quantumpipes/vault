# Streaming & Telemetry

Real-time event streaming and operation telemetry for autonomous AI systems.

## Event Streaming

Subscribe to vault mutations in real-time.

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

# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Basic telemetry for vault operations.

Tracks operation counts, latencies, and error rates.
Designed for autonomous AI systems that need to monitor
their own knowledge infrastructure.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class OperationMetrics:
    """Metrics for a single operation type."""

    count: int = 0
    errors: int = 0
    total_duration_ms: float = 0
    last_duration_ms: float = 0
    last_timestamp: str = ""

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.count if self.count > 0 else 0


class VaultTelemetry:
    """Lightweight telemetry collector for vault operations.

    Usage:
        telemetry = VaultTelemetry()

        with telemetry.track("search"):
            results = vault.search("query")

        print(telemetry.summary())
    """

    def __init__(self) -> None:
        self._metrics: dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._started_at = datetime.now(tz=UTC).isoformat()

    def track(self, operation: str) -> _TrackerContext:
        """Context manager to track an operation's duration.

        Args:
            operation: Name of the operation (e.g., "search", "add", "verify").
        """
        return _TrackerContext(self, operation)

    def record(self, operation: str, duration_ms: float, *, error: bool = False) -> None:
        """Manually record an operation metric."""
        m = self._metrics[operation]
        m.count += 1
        m.total_duration_ms += duration_ms
        m.last_duration_ms = duration_ms
        m.last_timestamp = datetime.now(tz=UTC).isoformat()
        if error:
            m.errors += 1

    def get(self, operation: str) -> OperationMetrics:
        """Get metrics for a specific operation."""
        return self._metrics[operation]

    def summary(self) -> dict[str, dict[str, float | int | str]]:
        """Get a summary of all operation metrics."""
        result: dict[str, dict[str, float | int | str]] = {}
        for op, m in self._metrics.items():
            result[op] = {
                "count": m.count,
                "errors": m.errors,
                "avg_ms": round(m.avg_duration_ms, 2),
                "last_ms": round(m.last_duration_ms, 2),
            }
        result["_meta"] = {"started_at": self._started_at}
        return result

    def reset(self) -> None:
        """Reset all metrics."""
        self._metrics.clear()
        self._started_at = datetime.now(tz=UTC).isoformat()


class _TrackerContext:
    """Context manager for tracking operation duration."""

    def __init__(self, telemetry: VaultTelemetry, operation: str) -> None:
        self._telemetry = telemetry
        self._operation = operation
        self._start: float = 0

    def __enter__(self) -> _TrackerContext:
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type: type | None, *_: object) -> None:
        duration_ms = (time.monotonic() - self._start) * 1000
        self._telemetry.record(
            self._operation,
            duration_ms,
            error=exc_type is not None,
        )

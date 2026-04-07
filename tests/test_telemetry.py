"""Tests for VaultTelemetry operation tracking."""

from __future__ import annotations

import time

from qp_vault.telemetry import VaultTelemetry


class TestVaultTelemetry:
    def test_track_context_manager(self):
        t = VaultTelemetry()
        with t.track("search"):
            time.sleep(0.01)
        m = t.get("search")
        assert m.count == 1
        assert m.last_duration_ms >= 5  # At least 5ms

    def test_track_multiple_operations(self):
        t = VaultTelemetry()
        for _ in range(3):
            with t.track("add"):
                pass
        m = t.get("add")
        assert m.count == 3

    def test_manual_record(self):
        t = VaultTelemetry()
        t.record("verify", 42.5)
        t.record("verify", 37.5, error=True)
        m = t.get("verify")
        assert m.count == 2
        assert m.errors == 1
        assert m.avg_duration_ms == 40.0

    def test_summary(self):
        t = VaultTelemetry()
        t.record("search", 10.0)
        t.record("add", 20.0)
        s = t.summary()
        assert "search" in s
        assert "add" in s
        assert s["search"]["count"] == 1
        assert "_meta" in s

    def test_reset(self):
        t = VaultTelemetry()
        t.record("search", 10.0)
        t.reset()
        assert t.summary().get("search") is None

    def test_error_tracking_in_context(self):
        t = VaultTelemetry()
        try:
            with t.track("failing"):
                raise ValueError("boom")
        except ValueError:
            pass
        m = t.get("failing")
        assert m.count == 1
        assert m.errors == 1

    def test_avg_duration_zero_count(self):
        t = VaultTelemetry()
        m = t.get("empty")
        assert m.avg_duration_ms == 0

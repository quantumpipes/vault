"""Tests for the LogAuditor (JSON lines fallback)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from qp_vault.audit.log_auditor import LogAuditor
from qp_vault.enums import EventType
from qp_vault.models import VaultEvent

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def auditor(tmp_path: Path) -> LogAuditor:
    return LogAuditor(tmp_path / "audit.jsonl")


def _make_event(event_type: EventType = EventType.CREATE) -> VaultEvent:
    return VaultEvent(
        event_type=event_type,
        resource_id="r-1",
        resource_name="test.md",
        resource_hash="abc123",
        details={"key": "value"},
    )


class TestLogAuditor:
    @pytest.mark.asyncio
    async def test_record_creates_file(self, auditor, tmp_path):
        await auditor.record(_make_event())
        assert (tmp_path / "audit.jsonl").exists()

    @pytest.mark.asyncio
    async def test_record_returns_event_id(self, auditor):
        event_id = await auditor.record(_make_event())
        assert event_id
        assert len(event_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_record_writes_json_line(self, auditor, tmp_path):
        await auditor.record(_make_event())
        content = (tmp_path / "audit.jsonl").read_text()
        record = json.loads(content.strip())
        assert record["event_type"] == "create"
        assert record["resource_id"] == "r-1"
        assert record["resource_name"] == "test.md"
        assert record["resource_hash"] == "abc123"
        assert record["details"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_multiple_events_appended(self, auditor, tmp_path):
        await auditor.record(_make_event(EventType.CREATE))
        await auditor.record(_make_event(EventType.UPDATE))
        await auditor.record(_make_event(EventType.DELETE))
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3
        assert json.loads(lines[0])["event_type"] == "create"
        assert json.loads(lines[1])["event_type"] == "update"
        assert json.loads(lines[2])["event_type"] == "delete"

    @pytest.mark.asyncio
    async def test_unique_event_ids(self, auditor):
        id1 = await auditor.record(_make_event())
        id2 = await auditor.record(_make_event())
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path):
        deep_path = tmp_path / "deep" / "nested" / "audit.jsonl"
        auditor = LogAuditor(deep_path)
        await auditor.record(_make_event())
        assert deep_path.exists()

    @pytest.mark.asyncio
    async def test_all_event_types_recorded(self, auditor, tmp_path):
        for et in EventType:
            await auditor.record(_make_event(et))
        lines = (tmp_path / "audit.jsonl").read_text().strip().split("\n")
        assert len(lines) == len(EventType)

"""Tests for VaultEventStream real-time event streaming."""

from __future__ import annotations

import asyncio

import pytest

from qp_vault.enums import EventType
from qp_vault.models import VaultEvent
from qp_vault.streaming import VaultEventStream


@pytest.fixture
def stream():
    return VaultEventStream()


def _event(name: str = "test.md") -> VaultEvent:
    return VaultEvent(event_type=EventType.CREATE, resource_id="r-1", resource_name=name)


class TestVaultEventStream:
    @pytest.mark.asyncio
    async def test_record_returns_id(self, stream):
        eid = await stream.record(_event())
        assert eid
        assert len(eid) == 36  # UUID

    @pytest.mark.asyncio
    async def test_history_populated(self, stream):
        await stream.record(_event("a.md"))
        await stream.record(_event("b.md"))
        assert len(stream.history) == 2
        assert stream.history[0].resource_name == "a.md"

    @pytest.mark.asyncio
    async def test_history_bounded(self):
        stream = VaultEventStream(buffer_size=3)
        for i in range(5):
            await stream.record(_event(f"{i}.md"))
        assert len(stream.history) == 3

    @pytest.mark.asyncio
    async def test_subscriber_count(self, stream):
        assert stream.subscriber_count == 0

    @pytest.mark.asyncio
    async def test_subscribe_receives_events(self, stream):
        received: list[VaultEvent] = []

        async def consumer():
            async for event in stream.subscribe():
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        await stream.record(_event("first.md"))
        await stream.record(_event("second.md"))
        await asyncio.wait_for(task, timeout=1.0)

        assert len(received) == 2
        assert received[0].resource_name == "first.md"

    @pytest.mark.asyncio
    async def test_subscribe_with_replay(self, stream):
        await stream.record(_event("old.md"))

        received: list[VaultEvent] = []

        async def consumer():
            async for event in stream.subscribe(replay=True):
                received.append(event)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        await stream.record(_event("new.md"))
        await asyncio.wait_for(task, timeout=1.0)

        assert received[0].resource_name == "old.md"  # Replayed
        assert received[1].resource_name == "new.md"  # Live

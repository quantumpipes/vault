# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for AsyncVault.subscribe() callback event system."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from qp_vault import AsyncVault, EventType, VaultEvent


@pytest.fixture
async def vault(tmp_vault_path):
    """Fresh AsyncVault for testing."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


class TestSubscribe:
    """Tests for the subscribe/unsubscribe callback system."""

    @pytest.mark.asyncio
    async def test_sync_callback_receives_create_event(self, vault: AsyncVault):
        """Sync callbacks receive VaultEvent on add()."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        await vault.add("Hello world", name="test.md")

        assert len(received) == 1
        assert received[0].event_type == EventType.CREATE
        assert received[0].resource_name == "test.md"
        assert received[0].resource_id

    @pytest.mark.asyncio
    async def test_async_callback_receives_create_event(self, vault: AsyncVault):
        """Async callbacks receive VaultEvent on add()."""
        received: list[VaultEvent] = []

        async def on_event(event: VaultEvent) -> None:
            received.append(event)

        vault.subscribe(on_event)
        await vault.add("Hello world", name="async-test.md")

        assert len(received) == 1
        assert received[0].event_type == EventType.CREATE

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_events(self, vault: AsyncVault):
        """Calling the unsubscribe function stops event delivery."""
        received: list[VaultEvent] = []
        unsub = vault.subscribe(lambda e: received.append(e))

        await vault.add("First", name="first.md")
        assert len(received) == 1

        unsub()
        await vault.add("Second", name="second.md")
        assert len(received) == 1  # No new events

    @pytest.mark.asyncio
    async def test_double_unsubscribe_is_safe(self, vault: AsyncVault):
        """Calling unsubscribe twice does not raise."""
        unsub = vault.subscribe(lambda e: None)
        unsub()
        unsub()  # Should not raise

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, vault: AsyncVault):
        """Multiple subscribers each receive all events."""
        a: list[VaultEvent] = []
        b: list[VaultEvent] = []
        vault.subscribe(lambda e: a.append(e))
        vault.subscribe(lambda e: b.append(e))

        await vault.add("Content", name="multi.md")

        assert len(a) == 1
        assert len(b) == 1

    @pytest.mark.asyncio
    async def test_update_emits_event(self, vault: AsyncVault):
        """update() emits an UPDATE event."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        resource = await vault.add("Content", name="update-me.md")
        received.clear()

        await vault.update(resource.id, tags=["updated"])

        assert len(received) == 1
        assert received[0].event_type == EventType.UPDATE
        assert received[0].resource_id == resource.id

    @pytest.mark.asyncio
    async def test_delete_emits_event(self, vault: AsyncVault):
        """delete() emits a DELETE event."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        resource = await vault.add("Content", name="delete-me.md")
        received.clear()

        await vault.delete(resource.id)

        assert len(received) == 1
        assert received[0].event_type == EventType.DELETE
        assert received[0].resource_id == resource.id
        assert received[0].details.get("hard") is False

    @pytest.mark.asyncio
    async def test_hard_delete_emits_event_with_hard_flag(self, vault: AsyncVault):
        """Hard delete includes hard=True in event details."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        resource = await vault.add("Content", name="hard-delete.md")
        received.clear()

        await vault.delete(resource.id, hard=True)

        assert len(received) == 1
        assert received[0].details.get("hard") is True

    @pytest.mark.asyncio
    async def test_transition_emits_event(self, vault: AsyncVault):
        """transition() emits a LIFECYCLE_TRANSITION event."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        resource = await vault.add("Content", name="transition.md")
        received.clear()

        await vault.transition(resource.id, "archived", reason="end of life")

        assert len(received) == 1
        assert received[0].event_type == EventType.LIFECYCLE_TRANSITION
        assert received[0].details["target"] == "archived"
        assert received[0].details["reason"] == "end of life"

    @pytest.mark.asyncio
    async def test_error_in_callback_does_not_propagate(self, vault: AsyncVault):
        """A failing callback does not break vault operations."""
        good: list[VaultEvent] = []

        def bad_callback(event: VaultEvent) -> None:
            raise RuntimeError("subscriber exploded")

        vault.subscribe(bad_callback)
        vault.subscribe(lambda e: good.append(e))

        # Should not raise despite bad_callback
        resource = await vault.add("Content", name="resilient.md")
        assert resource.name == "resilient.md"
        assert len(good) == 1  # Good callback still received event

    @pytest.mark.asyncio
    async def test_error_in_async_callback_does_not_propagate(self, vault: AsyncVault):
        """A failing async callback does not break vault operations."""
        good: list[VaultEvent] = []

        async def bad_async(event: VaultEvent) -> None:
            raise RuntimeError("async subscriber exploded")

        vault.subscribe(bad_async)
        vault.subscribe(lambda e: good.append(e))

        resource = await vault.add("Content", name="resilient-async.md")
        assert resource.name == "resilient-async.md"
        assert len(good) == 1

    @pytest.mark.asyncio
    async def test_event_contains_resource_hash(self, vault: AsyncVault):
        """Events include the resource content hash."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        await vault.add("Unique content for hashing", name="hashed.md")

        assert received[0].resource_hash
        assert len(received[0].resource_hash) > 0

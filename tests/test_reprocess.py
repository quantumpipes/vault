# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for AsyncVault.reprocess() and POST /resources/{id}/reprocess."""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault, EventType, VaultEvent


@pytest.fixture
async def vault(tmp_vault_path):
    """Fresh AsyncVault for testing."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


class TestReprocess:
    """Tests for the reprocess method."""

    @pytest.mark.asyncio
    async def test_reprocess_returns_indexed_resource(self, vault: AsyncVault):
        """Reprocessing returns a resource with INDEXED status."""
        resource = await vault.add("Some content for reprocessing", name="doc.md")
        result = await vault.reprocess(resource.id)
        assert result.status.value == "indexed"
        assert result.chunk_count > 0

    @pytest.mark.asyncio
    async def test_reprocess_preserves_metadata(self, vault: AsyncVault):
        """Reprocessing does not alter resource metadata."""
        resource = await vault.add(
            "Content with metadata",
            name="meta.md",
            tags=["important"],
            trust_tier="canonical",
        )
        result = await vault.reprocess(resource.id)
        assert result.name == "meta.md"
        assert result.trust_tier.value == "canonical"
        assert "important" in result.tags

    @pytest.mark.asyncio
    async def test_reprocess_updates_chunks(self, vault: AsyncVault):
        """Reprocessing creates fresh chunks."""
        resource = await vault.add("Original content", name="fresh.md")
        old_chunks = await vault._storage.get_chunks_for_resource(resource.id)

        await vault.reprocess(resource.id)
        new_chunks = await vault._storage.get_chunks_for_resource(resource.id)

        # New chunks should have different IDs (regenerated)
        old_ids = {c.id for c in old_chunks}
        new_ids = {c.id for c in new_chunks}
        assert old_ids != new_ids

    @pytest.mark.asyncio
    async def test_reprocess_emits_subscriber_event(self, vault: AsyncVault):
        """Reprocessing fires an UPDATE event to subscribers."""
        received: list[VaultEvent] = []
        vault.subscribe(lambda e: received.append(e))

        resource = await vault.add("Subscriber content", name="sub.md")
        received.clear()

        await vault.reprocess(resource.id)

        assert len(received) == 1
        assert received[0].event_type == EventType.UPDATE
        assert received[0].details.get("reprocessed") is True

    @pytest.mark.asyncio
    async def test_reprocess_missing_resource_raises(self, vault: AsyncVault):
        """Reprocessing a nonexistent resource raises VaultError."""
        from qp_vault.exceptions import VaultError
        with pytest.raises(VaultError):
            await vault.reprocess("nonexistent-id")

    @pytest.mark.asyncio
    async def test_reprocess_no_chunks_raises(self, vault: AsyncVault):
        """Reprocessing a resource with no chunks raises VaultError."""
        # Create resource without content (edge case)
        from qp_vault.exceptions import VaultError
        resource = await vault.add("x", name="empty.md")

        # Manually delete chunks to simulate edge case
        vault._storage._get_conn().execute(
            "DELETE FROM chunks WHERE resource_id = ?", (resource.id,)
        )
        vault._storage._get_conn().commit()

        with pytest.raises(VaultError, match="No content found"):
            await vault.reprocess(resource.id)

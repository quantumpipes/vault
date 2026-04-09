# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for FIX-4: adversarial status persistence across restarts."""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault


@pytest.fixture
async def vault(tmp_vault_path):
    """Fresh AsyncVault."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


class TestAdversarialPersistence:

    @pytest.mark.asyncio
    async def test_set_adversarial_persists_to_storage(self, vault: AsyncVault):
        """Setting adversarial status persists in the storage backend."""
        resource = await vault.add("Test content", name="adv.md")
        await vault.set_adversarial_status(resource.id, "verified")

        # Re-read from storage to confirm persistence
        updated = await vault.get(resource.id)
        assert updated.adversarial_status.value == "verified"

    @pytest.mark.asyncio
    async def test_adversarial_survives_new_vault_instance(self, tmp_vault_path):
        """Adversarial status survives creating a new vault instance (simulates restart)."""
        # Instance 1: create resource and set status
        v1 = AsyncVault(tmp_vault_path)
        await v1._ensure_initialized()
        resource = await v1.add("Persistent content", name="persist.md")
        await v1.set_adversarial_status(resource.id, "suspicious")

        # Instance 2: new vault, same path (simulates restart)
        v2 = AsyncVault(tmp_vault_path)
        await v2._ensure_initialized()
        reloaded = await v2.get(resource.id)
        assert reloaded.adversarial_status.value == "suspicious"

    @pytest.mark.asyncio
    async def test_default_is_unverified(self, vault: AsyncVault):
        """New resources default to UNVERIFIED adversarial status."""
        resource = await vault.add("New content", name="new.md")
        assert resource.adversarial_status.value == "unverified"

    @pytest.mark.asyncio
    async def test_status_readable_after_set(self, vault: AsyncVault):
        """Status is immediately readable via get() after set."""
        resource = await vault.add("Status check content", name="check.md")
        await vault.set_adversarial_status(resource.id, "suspicious")

        updated = await vault.get(resource.id)
        assert updated.adversarial_status.value == "suspicious"

        await vault.set_adversarial_status(resource.id, "verified")
        updated2 = await vault.get(resource.id)
        assert updated2.adversarial_status.value == "verified"

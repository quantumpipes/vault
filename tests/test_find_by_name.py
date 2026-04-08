# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for AsyncVault.find_by_name() resource lookup."""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault


@pytest.fixture
async def vault(tmp_vault_path):
    """Fresh AsyncVault with test docs."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    await v.add("Content A", name="STRATEGY.md")
    await v.add("Content B", name="roadmap.md")
    return v


class TestFindByName:
    """Tests for name-based resource lookup."""

    @pytest.mark.asyncio
    async def test_exact_match(self, vault: AsyncVault):
        """Exact name match returns the resource."""
        result = await vault.find_by_name("STRATEGY.md")
        assert result is not None
        assert result.name == "STRATEGY.md"

    @pytest.mark.asyncio
    async def test_case_insensitive(self, vault: AsyncVault):
        """Name matching is case-insensitive."""
        result = await vault.find_by_name("strategy.md")
        assert result is not None
        assert result.name == "STRATEGY.md"

    @pytest.mark.asyncio
    async def test_case_insensitive_upper(self, vault: AsyncVault):
        """Uppercase query matches lowercase resource."""
        result = await vault.find_by_name("ROADMAP.MD")
        assert result is not None
        assert result.name == "roadmap.md"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, vault: AsyncVault):
        """Non-existent name returns None."""
        result = await vault.find_by_name("nonexistent.md")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_first_match(self, vault: AsyncVault):
        """Returns the first matching resource."""
        result = await vault.find_by_name("roadmap.md")
        assert result is not None
        assert result.id  # Has a valid ID

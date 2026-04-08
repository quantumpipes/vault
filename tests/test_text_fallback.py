# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for text-only search fallback when no embedder is available."""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault


@pytest.fixture
async def vault_no_embedder(tmp_vault_path):
    """Vault with no embedder (text-only search mode)."""
    v = AsyncVault(tmp_vault_path)  # No embedder parameter
    await v._ensure_initialized()
    await v.add(
        "Quarterly revenue exceeded expectations with strong growth in cloud services",
        name="q3-report.md",
    )
    await v.add(
        "Employee onboarding process needs improvement for faster integration",
        name="hr-proposal.md",
    )
    await v.add(
        "Infrastructure costs for cloud computing continue to rise quarter over quarter",
        name="infra-costs.md",
    )
    return v


class TestTextFallback:
    """Tests for text-only search when no embedder is configured."""

    @pytest.mark.asyncio
    async def test_search_returns_results_without_embedder(self, vault_no_embedder: AsyncVault):
        """Search works with text matching even when no embedder is set."""
        results = await vault_no_embedder.search("revenue")
        assert len(results) >= 1
        assert any("revenue" in r.content.lower() for r in results)

    @pytest.mark.asyncio
    async def test_search_text_matching_is_keyword_based(self, vault_no_embedder: AsyncVault):
        """Text-only search matches on keyword presence."""
        results = await vault_no_embedder.search("cloud")
        assert len(results) >= 1
        names = [r.resource_name for r in results]
        # Both cloud-related docs should match
        assert any("q3" in n or "infra" in n for n in names)

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self, vault_no_embedder: AsyncVault):
        """Search for nonexistent term returns empty list."""
        results = await vault_no_embedder.search("xyznonexistent")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self, vault_no_embedder: AsyncVault):
        """top_k limits results even in text-only mode."""
        results = await vault_no_embedder.search("cloud", top_k=1)
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_search_applies_trust_weighting(self, vault_no_embedder: AsyncVault):
        """Trust weighting is applied even in text-only mode."""
        results = await vault_no_embedder.search("cloud")
        for r in results:
            assert r.trust_weight > 0

# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for AsyncVault.grep() multi-keyword OR search."""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault


@pytest.fixture
async def vault_with_docs(tmp_vault_path):
    """Vault with three documents for grep testing."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    await v.add(
        "Python is a great programming language for data science and machine learning",
        name="python-guide.md",
    )
    await v.add(
        "Rust provides memory safety without garbage collection",
        name="rust-overview.md",
    )
    await v.add(
        "Machine learning with Python and Rust is becoming popular for data pipelines",
        name="ml-pipelines.md",
    )
    return v


class TestGrep:
    """Tests for multi-keyword OR search."""

    @pytest.mark.asyncio
    async def test_single_keyword(self, vault_with_docs: AsyncVault):
        """Single keyword returns matching documents."""
        results = await vault_with_docs.grep(["python"])
        assert len(results) >= 1
        names = [r.resource_name for r in results]
        assert any("python" in n.lower() for n in names)

    @pytest.mark.asyncio
    async def test_multiple_keywords_or(self, vault_with_docs: AsyncVault):
        """Multiple keywords use OR matching (any keyword matches)."""
        results = await vault_with_docs.grep(["python", "rust"])
        assert len(results) >= 2  # Both python and rust docs should match

    @pytest.mark.asyncio
    async def test_hit_density_scoring(self, vault_with_docs: AsyncVault):
        """Documents matching more keywords score higher."""
        results = await vault_with_docs.grep(["python", "machine", "learning"])
        if len(results) >= 2:
            # The doc with Python + machine learning should rank higher
            # than a doc with only one keyword
            assert results[0].relevance >= results[-1].relevance

    @pytest.mark.asyncio
    async def test_empty_keywords_returns_empty(self, vault_with_docs: AsyncVault):
        """Empty keyword list returns no results."""
        results = await vault_with_docs.grep([])
        assert results == []

    @pytest.mark.asyncio
    async def test_whitespace_keywords_filtered(self, vault_with_docs: AsyncVault):
        """Whitespace-only keywords are filtered out."""
        results = await vault_with_docs.grep(["", "  ", "python"])
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_max_keywords_enforced(self, vault_with_docs: AsyncVault):
        """Keywords beyond max_keywords are truncated (no error)."""
        many_keywords = [f"keyword{i}" for i in range(30)]
        # Should not raise, just truncates
        results = await vault_with_docs.grep(many_keywords)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, vault_with_docs: AsyncVault):
        """top_k parameter limits result count."""
        results = await vault_with_docs.grep(["python", "rust"], top_k=1)
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, vault_with_docs: AsyncVault):
        """Keywords that match nothing return empty list."""
        results = await vault_with_docs.grep(["xyznonexistent123"])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplicates_by_resource(self, vault_with_docs: AsyncVault):
        """Results are deduplicated by resource_id."""
        results = await vault_with_docs.grep(["python", "data", "science"])
        resource_ids = [r.resource_id for r in results]
        assert len(resource_ids) == len(set(resource_ids))

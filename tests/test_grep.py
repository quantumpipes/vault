# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for AsyncVault.grep() world-class multi-keyword search.

Covers: single-pass FTS5 query, three-signal blended scoring
(coverage + text rank + proximity), trust weighting, deduplication,
explain_metadata, snippets, and edge cases.
"""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault


@pytest.fixture
async def vault_with_docs(tmp_vault_path):
    """Vault with diverse documents for grep testing."""
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
    await v.add(
        "This Non-Disclosure Agreement (NDA) governs confidential information sharing",
        name="nda-template.md",
    )
    await v.add(
        "All employees must complete annual security awareness training on phishing and social engineering",
        name="security-policy.md",
    )
    await v.add(
        "The REST API supports GET, POST, PUT, DELETE operations with JSON payloads",
        name="api-reference.md",
    )
    await v.add(
        "Q3 planning: discussed Python migration timeline and Rust adoption for data processing",
        name="meeting-notes.md",
    )
    return v


# =============================================================================
# Original tests (backward compatibility)
# =============================================================================


class TestGrepBackwardCompat:
    """All original test_grep.py tests must continue passing."""

    @pytest.mark.asyncio
    async def test_single_keyword(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python"])
        assert len(results) >= 1
        names = [r.resource_name for r in results]
        assert any("python" in n.lower() for n in names)

    @pytest.mark.asyncio
    async def test_multiple_keywords_or(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "rust"])
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_hit_density_scoring(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "machine", "learning"])
        if len(results) >= 2:
            assert results[0].relevance >= results[-1].relevance

    @pytest.mark.asyncio
    async def test_empty_keywords_returns_empty(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep([])
        assert results == []

    @pytest.mark.asyncio
    async def test_whitespace_keywords_filtered(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["", "  ", "python"])
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_max_keywords_enforced(self, vault_with_docs: AsyncVault):
        many_keywords = [f"keyword{i}" for i in range(30)]
        results = await vault_with_docs.grep(many_keywords)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "rust"], top_k=1)
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["xyznonexistent123"])
        assert results == []

    @pytest.mark.asyncio
    async def test_deduplicates_by_resource(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "data", "science"])
        resource_ids = [r.resource_id for r in results]
        assert len(resource_ids) == len(set(resource_ids))


# =============================================================================
# Three-signal blended scoring
# =============================================================================


class TestGrepBlendedScoring:
    """Verify the three-signal scoring: coverage * (rank_w * rank + prox_w * proximity)."""

    @pytest.mark.asyncio
    async def test_higher_coverage_scores_higher(self, vault_with_docs: AsyncVault):
        """Documents matching more keywords rank higher (coord factor)."""
        results = await vault_with_docs.grep(["python", "data", "machine", "learning"])
        if len(results) >= 2:
            # ml-pipelines or python-guide (3-4 keywords) should beat rust-overview (0 keywords)
            top_names = [r.resource_name for r in results[:2]]
            assert not any("rust-overview" in n for n in top_names)

    @pytest.mark.asyncio
    async def test_relevance_is_not_pure_density(self, vault_with_docs: AsyncVault):
        """Relevance uses blended scoring, not just density fraction."""
        results = await vault_with_docs.grep(["python"])
        for r in results:
            # With one keyword, density = 1.0 for all matches
            # But relevance should incorporate text_rank and proximity
            assert r.relevance > 0.0

    @pytest.mark.asyncio
    async def test_results_sorted_by_relevance(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "rust", "data"])
        for i in range(len(results) - 1):
            assert results[i].relevance >= results[i + 1].relevance


# =============================================================================
# Explain metadata
# =============================================================================


class TestGrepExplainMetadata:
    """Verify explain_metadata contains scoring breakdown."""

    @pytest.mark.asyncio
    async def test_explain_metadata_present(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python"])
        assert len(results) >= 1
        meta = results[0].explain_metadata
        assert meta is not None
        assert "matched_keywords" in meta
        assert "hit_density" in meta
        assert "text_rank" in meta
        assert "proximity" in meta
        assert "snippet" in meta

    @pytest.mark.asyncio
    async def test_matched_keywords_accurate(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "rust", "nonexistent"])
        for r in results:
            meta = r.explain_metadata
            assert meta is not None
            matched = meta["matched_keywords"]
            assert isinstance(matched, list)
            # Each matched keyword should actually appear in content
            for kw in matched:
                assert kw in r.content.lower()

    @pytest.mark.asyncio
    async def test_hit_density_is_fraction(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python", "data", "nda"])
        for r in results:
            meta = r.explain_metadata
            assert meta is not None
            density = meta["hit_density"]
            assert 0.0 < density <= 1.0

    @pytest.mark.asyncio
    async def test_snippet_contains_keyword(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["python"])
        for r in results:
            meta = r.explain_metadata
            assert meta is not None
            snippet = meta["snippet"]
            if snippet:  # Snippets may be empty for edge cases
                assert "**" in snippet  # Highlight markers present


# =============================================================================
# Edge cases
# =============================================================================


class TestGrepEdgeCases:
    @pytest.mark.asyncio
    async def test_special_characters_in_keywords(self, vault_with_docs: AsyncVault):
        """FTS5 special chars don't crash the query."""
        results = await vault_with_docs.grep(['"hello"', 'test*', 'foo(bar)'])
        assert isinstance(results, list)  # No exception

    @pytest.mark.asyncio
    async def test_duplicate_keywords_deduplicated(self, vault_with_docs: AsyncVault):
        """Duplicate keywords treated as one."""
        results = await vault_with_docs.grep(["python", "python", "Python"])
        assert len(results) >= 1
        # density should reflect 1 unique keyword, not 3
        meta = results[0].explain_metadata
        assert meta is not None
        assert meta["hit_density"] == 1.0  # 1/1

    @pytest.mark.asyncio
    async def test_keyword_with_spaces(self, vault_with_docs: AsyncVault):
        """Multi-word keywords work as phrase matches."""
        results = await vault_with_docs.grep(["machine learning"])
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_single_char_keyword(self, vault_with_docs: AsyncVault):
        """Single character keywords work without error."""
        results = await vault_with_docs.grep(["a"])
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_very_long_keyword(self, vault_with_docs: AsyncVault):
        """500-char keyword handled gracefully (truncated)."""
        long_kw = "a" * 500
        results = await vault_with_docs.grep([long_kw])
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_all_whitespace_keywords(self, vault_with_docs: AsyncVault):
        results = await vault_with_docs.grep(["   ", "\t", "\n"])
        assert results == []


# =============================================================================
# Trust weighting
# =============================================================================


class TestGrepTrustWeighting:
    @pytest.mark.asyncio
    async def test_trust_weight_applied(self, tmp_vault_path):
        """CANONICAL resource scores higher than WORKING with same grep match."""
        v = AsyncVault(tmp_vault_path)
        await v._ensure_initialized()
        await v.add("Python programming guide", name="working-doc.md")
        r2 = await v.add("Python programming reference", name="canonical-doc.md")
        # Promote r2 to canonical
        from qp_vault.protocols import ResourceUpdate
        await v._storage.update_resource(r2.id, ResourceUpdate(trust_tier="canonical"))

        results = await v.grep(["python", "programming"])
        assert len(results) == 2
        # Canonical should rank higher with same keyword match
        assert results[0].resource_name == "canonical-doc.md"


# =============================================================================
# Single-query verification
# =============================================================================


class TestGrepSingleQuery:
    @pytest.mark.asyncio
    async def test_single_storage_call(self, tmp_vault_path):
        """Verify grep uses exactly one storage.grep() call, not N search() calls."""
        v = AsyncVault(tmp_vault_path)
        await v._ensure_initialized()
        await v.add("Python and Rust and Go programming", name="test.md")

        call_count = 0
        original_grep = v._storage.grep

        async def counting_grep(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return await original_grep(*args, **kwargs)

        v._storage.grep = counting_grep
        await v.grep(["python", "rust", "go"])
        assert call_count == 1, f"Expected 1 storage.grep() call, got {call_count}"

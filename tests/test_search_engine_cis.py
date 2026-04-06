# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for search engine Membrane extensions: trust weights, freshness, 2D scoring.

Fills gaps: compute_trust_weight, compute_freshness, apply_trust_weighting edge cases.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qp_vault.core.search_engine import (
    apply_trust_weighting,
    compute_freshness,
    compute_trust_weight,
)
from qp_vault.enums import AdversarialStatus, TrustTier
from qp_vault.models import SearchResult

# =============================================================================
# compute_trust_weight
# =============================================================================


class TestComputeTrustWeight:
    """Trust weight multiplier for each tier."""

    def test_canonical_weight(self):
        assert compute_trust_weight(TrustTier.CANONICAL.value) == 1.5

    def test_working_weight(self):
        assert compute_trust_weight(TrustTier.WORKING.value) == 1.0

    def test_ephemeral_weight(self):
        assert compute_trust_weight(TrustTier.EPHEMERAL.value) == 0.7

    def test_archived_weight(self):
        assert compute_trust_weight(TrustTier.ARCHIVED.value) == 0.25

    def test_unknown_tier_returns_default(self):
        assert compute_trust_weight("nonexistent") == 1.0

    def test_empty_string_returns_default(self):
        assert compute_trust_weight("") == 1.0


# =============================================================================
# compute_freshness
# =============================================================================


class TestComputeFreshness:
    """Freshness decay: exponential based on age and half-life."""

    def test_recent_document_near_one(self):
        now = datetime.now(tz=UTC)
        score = compute_freshness(now, TrustTier.WORKING.value)
        assert score > 0.99

    def test_old_document_decays(self):
        old = datetime.now(tz=UTC) - timedelta(days=365)
        score = compute_freshness(old, TrustTier.WORKING.value)
        # Working half-life = 180 days; 365 days = ~2 half-lives
        assert score < 0.3

    def test_null_date_returns_one(self):
        assert compute_freshness(None, TrustTier.WORKING.value) == 1.0

    def test_string_iso_date_parsed(self):
        recent = datetime.now(tz=UTC).isoformat()
        score = compute_freshness(recent, TrustTier.WORKING.value)
        assert score > 0.99

    def test_invalid_string_returns_one(self):
        assert compute_freshness("not-a-date", TrustTier.WORKING.value) == 1.0

    def test_canonical_decays_slower_than_working(self):
        """Canonical half-life (365d) > Working half-life (180d)."""
        old = datetime.now(tz=UTC) - timedelta(days=200)
        canonical = compute_freshness(old, TrustTier.CANONICAL.value)
        working = compute_freshness(old, TrustTier.WORKING.value)
        assert canonical > working

    def test_ephemeral_decays_faster_than_working(self):
        """Ephemeral half-life (30d) < Working half-life (180d)."""
        old = datetime.now(tz=UTC) - timedelta(days=60)
        ephemeral = compute_freshness(old, TrustTier.EPHEMERAL.value)
        working = compute_freshness(old, TrustTier.WORKING.value)
        assert ephemeral < working

    def test_negative_age_returns_one(self):
        """Future date should not produce weird scores."""
        future = datetime.now(tz=UTC) + timedelta(days=10)
        score = compute_freshness(future, TrustTier.WORKING.value)
        assert score == 1.0


# =============================================================================
# apply_trust_weighting: edge cases
# =============================================================================


class TestApplyTrustWeightingEdgeCases:
    """Edge cases for 2D trust weighting and sorting."""

    def test_empty_results(self):
        assert apply_trust_weighting([]) == []

    def test_sorting_by_composite_relevance(self):
        """Higher 2D trust score should rank higher even with same raw relevance."""
        results = [
            SearchResult(
                chunk_id="c1", resource_id="r1", resource_name="low.pdf",
                content="x", trust_tier=TrustTier.EPHEMERAL,
                adversarial_status=AdversarialStatus.SUSPICIOUS,
                relevance=1.0,
            ),
            SearchResult(
                chunk_id="c2", resource_id="r2", resource_name="high.pdf",
                content="x", trust_tier=TrustTier.CANONICAL,
                adversarial_status=AdversarialStatus.VERIFIED,
                relevance=1.0,
            ),
        ]
        weighted = apply_trust_weighting(results)
        assert weighted[0].resource_name == "high.pdf"
        assert weighted[1].resource_name == "low.pdf"
        # CANONICAL+VERIFIED = 1.5*1.0 = 1.5
        # EPHEMERAL+SUSPICIOUS = 0.7*0.3 = 0.21
        assert weighted[0].relevance > weighted[1].relevance

    def test_raw_relevance_still_matters(self):
        """Raw relevance can overcome trust disadvantage."""
        results = [
            SearchResult(
                chunk_id="c1", resource_id="r1", resource_name="high_rel.pdf",
                content="x", trust_tier=TrustTier.WORKING,
                adversarial_status=AdversarialStatus.UNVERIFIED,
                relevance=10.0,
            ),
            SearchResult(
                chunk_id="c2", resource_id="r2", resource_name="low_rel.pdf",
                content="x", trust_tier=TrustTier.CANONICAL,
                adversarial_status=AdversarialStatus.VERIFIED,
                relevance=1.0,
            ),
        ]
        weighted = apply_trust_weighting(results)
        # 10.0 * 1.0 * 0.7 = 7.0 > 1.0 * 1.5 * 1.0 = 1.5
        assert weighted[0].resource_name == "high_rel.pdf"

    def test_missing_adversarial_status_uses_default(self):
        """SearchResult without adversarial_status defaults to UNVERIFIED (0.7x)."""
        results = [
            SearchResult(
                chunk_id="c1", resource_id="r1", resource_name="doc.pdf",
                content="x", trust_tier=TrustTier.WORKING, relevance=1.0,
            ),
        ]
        weighted = apply_trust_weighting(results)
        # WORKING (1.0) * UNVERIFIED default (0.7) = 0.7
        assert weighted[0].trust_weight == pytest.approx(0.7, rel=0.01)

    def test_all_trust_tiers_with_all_statuses(self):
        """Comprehensive matrix: every tier x every status."""
        results = []
        for tier in TrustTier:
            for status in AdversarialStatus:
                results.append(SearchResult(
                    chunk_id=f"c-{tier.value}-{status.value}",
                    resource_id=f"r-{tier.value}-{status.value}",
                    resource_name=f"{tier.value}_{status.value}.pdf",
                    content="x",
                    trust_tier=tier,
                    adversarial_status=status,
                    relevance=1.0,
                ))
        weighted = apply_trust_weighting(results)

        # All should have non-zero relevance
        for r in weighted:
            assert r.relevance > 0

        # CANONICAL+VERIFIED should be at the top
        assert weighted[0].resource_name == "canonical_verified.pdf"

        # ARCHIVED+SUSPICIOUS should be near the bottom
        archived_suspicious = [r for r in weighted if "archived_suspicious" in r.resource_name]
        assert archived_suspicious[0].relevance < 0.1

"""Tests for trust-weighted search engine."""

from datetime import UTC, datetime, timedelta

import pytest

from qp_vault.core.search_engine import (
    apply_trust_weighting,
    compute_freshness,
    compute_trust_weight,
)
from qp_vault.enums import TrustTier
from qp_vault.models import SearchResult


def _make_result(trust: str = "working", relevance: float = 0.8) -> SearchResult:
    return SearchResult(
        chunk_id="c-1",
        resource_id="r-1",
        resource_name="test.md",
        content="test content",
        vector_similarity=relevance,
        text_rank=relevance,
        trust_tier=TrustTier(trust),
        relevance=relevance,
    )


class TestTrustWeight:
    def test_canonical_weight(self):
        assert compute_trust_weight("canonical") == 1.5

    def test_working_weight(self):
        assert compute_trust_weight("working") == 1.0

    def test_ephemeral_weight(self):
        assert compute_trust_weight("ephemeral") == 0.7

    def test_archived_weight(self):
        assert compute_trust_weight("archived") == 0.25

    def test_unknown_tier_defaults(self):
        assert compute_trust_weight("unknown") == 1.0


class TestFreshness:
    def test_recent_is_fresh(self):
        now = datetime.now(tz=UTC)
        f = compute_freshness(now, "working")
        assert f > 0.99

    def test_old_decays(self):
        old = datetime.now(tz=UTC) - timedelta(days=365)
        f = compute_freshness(old, "working")
        assert f < 0.5  # 180 day half-life for working

    def test_canonical_decays_slowly(self):
        old = datetime.now(tz=UTC) - timedelta(days=365)
        f_canonical = compute_freshness(old, "canonical")
        f_ephemeral = compute_freshness(old, "ephemeral")
        assert f_canonical > f_ephemeral

    def test_none_returns_fresh(self):
        assert compute_freshness(None, "working") == 1.0

    def test_string_datetime(self):
        now = datetime.now(tz=UTC).isoformat()
        f = compute_freshness(now, "working")
        assert f > 0.99


class TestApplyTrustWeighting:
    def test_canonical_boosted(self):
        results = [
            _make_result("canonical", 0.8),
            _make_result("working", 0.8),
        ]
        weighted = apply_trust_weighting(results)
        # Canonical should have higher relevance
        assert weighted[0].trust_tier == TrustTier.CANONICAL
        assert weighted[0].relevance > weighted[1].relevance

    def test_archived_penalized(self):
        results = [
            _make_result("working", 0.8),
            _make_result("archived", 0.8),
        ]
        weighted = apply_trust_weighting(results)
        # Working should rank above archived
        assert weighted[0].trust_tier == TrustTier.WORKING

    def test_empty_results(self):
        assert apply_trust_weighting([]) == []

    def test_sorts_by_composite_relevance(self):
        results = [
            _make_result("ephemeral", 0.9),   # 0.9 * 0.7 = 0.63
            _make_result("canonical", 0.5),    # 0.5 * 1.5 = 0.75
        ]
        weighted = apply_trust_weighting(results)
        # Canonical should win despite lower raw score
        assert weighted[0].trust_tier == TrustTier.CANONICAL

    def test_trust_weight_field_set(self):
        results = [_make_result("canonical", 0.8)]
        weighted = apply_trust_weighting(results)
        # 2D trust: CANONICAL (1.5) * UNVERIFIED (0.7) = 1.05
        assert weighted[0].trust_weight == pytest.approx(1.05)

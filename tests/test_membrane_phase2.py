# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for Membrane Phase 2.

Covers: AdversarialVerifier, source diversity, approval budgets, anomaly detection.
"""

from __future__ import annotations

import pytest

from qp_vault.adversarial import VALID_TRANSITIONS, AdversarialVerifier
from qp_vault.enums import AdversarialStatus

# =============================================================================
# ADVERSARIAL VERIFIER TESTS
# =============================================================================


class TestAdversarialVerifier:
    """AdversarialVerifier: manage adversarial_status transitions."""

    @pytest.fixture
    def verifier(self):
        return AdversarialVerifier()

    @pytest.mark.asyncio
    async def test_default_status_is_unverified(self, verifier):
        status = await verifier.get_status("r1")
        assert status == AdversarialStatus.UNVERIFIED

    @pytest.mark.asyncio
    async def test_transition_unverified_to_verified(self, verifier):
        result = await verifier.set_status("r1", AdversarialStatus.VERIFIED, reason="Membrane passed")
        assert result == AdversarialStatus.VERIFIED
        assert await verifier.get_status("r1") == AdversarialStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_transition_unverified_to_suspicious(self, verifier):
        result = await verifier.set_status("r1", AdversarialStatus.SUSPICIOUS, reason="Flagged")
        assert result == AdversarialStatus.SUSPICIOUS

    @pytest.mark.asyncio
    async def test_transition_suspicious_to_verified(self, verifier):
        await verifier.set_status("r1", AdversarialStatus.SUSPICIOUS)
        result = await verifier.set_status("r1", AdversarialStatus.VERIFIED, reason="Human cleared")
        assert result == AdversarialStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_transition_verified_to_suspicious(self, verifier):
        await verifier.set_status("r1", AdversarialStatus.VERIFIED)
        result = await verifier.set_status("r1", AdversarialStatus.SUSPICIOUS, reason="Re-assessed")
        assert result == AdversarialStatus.SUSPICIOUS

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, verifier):
        await verifier.set_status("r1", AdversarialStatus.VERIFIED)
        with pytest.raises(ValueError, match="Invalid transition"):
            await verifier.set_status("r1", AdversarialStatus.UNVERIFIED)

    @pytest.mark.asyncio
    async def test_bulk_reassess(self, verifier):
        await verifier.set_status("r1", AdversarialStatus.VERIFIED)
        await verifier.set_status("r2", AdversarialStatus.VERIFIED)
        results = await verifier.bulk_reassess(
            ["r1", "r2"], AdversarialStatus.SUSPICIOUS, reason="Source compromised"
        )
        assert results["r1"] == AdversarialStatus.SUSPICIOUS
        assert results["r2"] == AdversarialStatus.SUSPICIOUS

    @pytest.mark.asyncio
    async def test_bulk_reassess_skips_invalid(self, verifier):
        """Bulk reassess skips invalid transitions without raising."""
        await verifier.set_status("r1", AdversarialStatus.SUSPICIOUS)
        # SUSPICIOUS -> UNVERIFIED is invalid
        results = await verifier.bulk_reassess(
            ["r1"], AdversarialStatus.UNVERIFIED, reason="test"
        )
        assert results["r1"] == AdversarialStatus.SUSPICIOUS  # unchanged

    @pytest.mark.asyncio
    async def test_counts(self, verifier):
        await verifier.set_status("r1", AdversarialStatus.VERIFIED)
        await verifier.set_status("r2", AdversarialStatus.VERIFIED)
        await verifier.set_status("r3", AdversarialStatus.SUSPICIOUS)
        assert await verifier.get_verified_count() == 2
        assert await verifier.get_suspicious_count() == 1

    def test_valid_transitions_complete(self):
        """All statuses have transition rules defined."""
        for status in AdversarialStatus:
            assert status in VALID_TRANSITIONS

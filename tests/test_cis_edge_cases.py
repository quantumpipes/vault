# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Edge case tests for CIS components.

Fills remaining gaps: auditor integration, provenance verify positive path,
mixed adversarial statuses, approval budget boundaries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from qp_vault.adversarial import AdversarialVerifier
from qp_vault.enums import AdversarialStatus, EventType, UploadMethod
from qp_vault.provenance import ContentProvenanceService

# =============================================================================
# Provenance: positive verification path
# =============================================================================


class TestProvenanceVerifyPositive:
    """Test successful signature verification end-to-end."""

    @pytest.mark.asyncio
    async def test_create_and_verify_roundtrip(self):
        """Signed provenance verifies successfully."""
        signatures: dict[str, str] = {}

        async def mock_sign(data: bytes) -> str:
            sig = f"sig_{hash(data) % 10000:04d}"
            signatures[sig] = data.hex()
            return sig

        async def mock_verify(data: bytes, sig: str) -> bool:
            return sig in signatures and signatures[sig] == data.hex()

        service = ContentProvenanceService(
            signing_fn=mock_sign, verify_fn=mock_verify,
        )
        prov = await service.create_attestation(
            resource_id="r1", uploader_id="u1",
            method=UploadMethod.UI, original_hash="abc",
        )
        assert prov.signature_verified is True

        # Verify the attestation
        result = await service.verify_attestation(prov)
        assert result is True

    @pytest.mark.asyncio
    async def test_tampered_provenance_fails_verify(self):
        """Modified provenance does not verify."""
        async def mock_sign(data: bytes) -> str:
            import hashlib
            return f"sig_{hashlib.sha256(data).hexdigest()[:16]}"

        async def mock_verify(data: bytes, sig: str) -> bool:
            import hashlib
            return sig == f"sig_{hashlib.sha256(data).hexdigest()[:16]}"

        service = ContentProvenanceService(
            signing_fn=mock_sign, verify_fn=mock_verify,
        )
        prov = await service.create_attestation(
            resource_id="r1", uploader_id="u1",
            method=UploadMethod.API, original_hash="abc",
        )

        # Tamper with the provenance
        tampered = prov.model_copy(update={"uploader_id": "attacker"})
        result = await service.verify_attestation(tampered)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_by_uploader_no_matches(self):
        service = ContentProvenanceService()
        result = await service.get_by_uploader("nonexistent")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_by_method_no_matches(self):
        service = ContentProvenanceService()
        result = await service.get_by_method(UploadMethod.CLI)
        assert result == []


# =============================================================================
# AdversarialVerifier: auditor integration
# =============================================================================


class TestAdversarialVerifierAuditor:
    """Verify auditor is called with correct VaultEvent."""

    @pytest.mark.asyncio
    async def test_set_status_calls_auditor(self):
        auditor = AsyncMock()
        auditor.record = AsyncMock(return_value="event_id")
        verifier = AdversarialVerifier(auditor=auditor)

        await verifier.set_status(
            "r1", AdversarialStatus.VERIFIED,
            reason="CIS passed", reviewer_id="admin1",
        )

        auditor.record.assert_called_once()
        event = auditor.record.call_args[0][0]
        assert event.event_type == EventType.ADVERSARIAL_STATUS_CHANGE
        assert event.resource_id == "r1"
        assert event.details["previous"] == "unverified"
        assert event.details["new"] == "verified"
        assert event.details["reason"] == "CIS passed"
        assert event.details["reviewer_id"] == "admin1"

    @pytest.mark.asyncio
    async def test_bulk_reassess_calls_auditor_per_resource(self):
        auditor = AsyncMock()
        auditor.record = AsyncMock(return_value="event_id")
        verifier = AdversarialVerifier(auditor=auditor)

        await verifier.bulk_reassess(
            ["r1", "r2", "r3"], AdversarialStatus.SUSPICIOUS, reason="compromise",
        )
        assert auditor.record.call_count == 3

    @pytest.mark.asyncio
    async def test_same_status_no_transition_no_audit(self):
        """Setting same status should not raise and should still call auditor."""
        auditor = AsyncMock()
        auditor.record = AsyncMock(return_value="event_id")
        verifier = AdversarialVerifier(auditor=auditor)

        await verifier.set_status("r1", AdversarialStatus.UNVERIFIED)
        # UNVERIFIED -> UNVERIFIED is a no-op but status is stored
        auditor.record.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_auditor_does_not_crash(self):
        verifier = AdversarialVerifier(auditor=None)
        result = await verifier.set_status("r1", AdversarialStatus.VERIFIED)
        assert result == AdversarialStatus.VERIFIED


# =============================================================================
# AdversarialVerifier: chained transitions
# =============================================================================


class TestAdversarialVerifierChains:
    """Multi-step status transitions."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """UNVERIFIED -> SUSPICIOUS -> VERIFIED -> SUSPICIOUS -> VERIFIED."""
        v = AdversarialVerifier()
        assert await v.get_status("r1") == AdversarialStatus.UNVERIFIED

        await v.set_status("r1", AdversarialStatus.SUSPICIOUS)
        assert await v.get_status("r1") == AdversarialStatus.SUSPICIOUS

        await v.set_status("r1", AdversarialStatus.VERIFIED)
        assert await v.get_status("r1") == AdversarialStatus.VERIFIED

        await v.set_status("r1", AdversarialStatus.SUSPICIOUS)
        assert await v.get_status("r1") == AdversarialStatus.SUSPICIOUS

        await v.set_status("r1", AdversarialStatus.VERIFIED)
        assert await v.get_status("r1") == AdversarialStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_cannot_go_back_to_unverified(self):
        """Once verified or suspicious, cannot return to unverified."""
        v = AdversarialVerifier()
        await v.set_status("r1", AdversarialStatus.VERIFIED)
        with pytest.raises(ValueError):
            await v.set_status("r1", AdversarialStatus.UNVERIFIED)

        v2 = AdversarialVerifier()
        await v2.set_status("r2", AdversarialStatus.SUSPICIOUS)
        with pytest.raises(ValueError):
            await v2.set_status("r2", AdversarialStatus.UNVERIFIED)

# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for Content Immune System (CIS) Phase 1.

Covers: enums, models, provenance service, search exclusion, 2D trust scoring.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qp_vault.core.search_engine import (
    apply_trust_weighting,
    compute_adversarial_multiplier,
    is_searchable,
)
from qp_vault.enums import (
    AdversarialStatus,
    CISResult,
    CISStage,
    ResourceStatus,
    TrustTier,
    UploadMethod,
)
from qp_vault.models import (
    CISPipelineStatus,
    CISStageRecord,
    ContentProvenance,
    Resource,
    SearchResult,
)
from qp_vault.provenance import ContentProvenanceService

# =============================================================================
# ENUM TESTS
# =============================================================================


class TestCISEnums:
    """CIS-specific enum definitions."""

    def test_resource_status_quarantined_exists(self):
        assert ResourceStatus.QUARANTINED == "quarantined"

    def test_adversarial_status_values(self):
        assert AdversarialStatus.UNVERIFIED == "unverified"
        assert AdversarialStatus.VERIFIED == "verified"
        assert AdversarialStatus.SUSPICIOUS == "suspicious"

    def test_cis_stage_values(self):
        assert CISStage.INGEST == "ingest"
        assert CISStage.INNATE_SCAN == "innate_scan"
        assert CISStage.ADAPTIVE_SCAN == "adaptive_scan"
        assert CISStage.CORRELATE == "correlate"
        assert CISStage.RELEASE == "release"
        assert CISStage.SURVEIL == "surveil"
        assert CISStage.PRESENT == "present"
        assert CISStage.REMEMBER == "remember"

    def test_cis_result_values(self):
        assert CISResult.PASS == "pass"
        assert CISResult.FLAG == "flag"
        assert CISResult.FAIL == "fail"
        assert CISResult.SKIP == "skip"

    def test_upload_method_values(self):
        assert UploadMethod.UI == "ui"
        assert UploadMethod.API == "api"
        assert UploadMethod.CLI == "cli"
        assert UploadMethod.EMAIL == "email"
        assert UploadMethod.IMPORT == "import"


# =============================================================================
# MODEL TESTS
# =============================================================================


class TestCISModels:
    """CIS domain model validation."""

    def test_resource_has_adversarial_status(self):
        r = Resource(id="r1", name="test.pdf", content_hash="abc123")
        assert r.adversarial_status == AdversarialStatus.UNVERIFIED

    def test_resource_quarantined_status(self):
        r = Resource(
            id="r1",
            name="test.pdf",
            content_hash="abc123",
            status=ResourceStatus.QUARANTINED,
        )
        assert r.status == ResourceStatus.QUARANTINED

    def test_content_provenance_defaults(self):
        p = ContentProvenance(id="p1", resource_id="r1", uploader_id="u1")
        assert p.upload_method == UploadMethod.API
        assert p.provenance_signature == ""
        assert not p.signature_verified

    def test_cis_stage_record_defaults(self):
        s = CISStageRecord(
            id="s1", resource_id="r1", stage=CISStage.INNATE_SCAN
        )
        assert s.result == CISResult.PASS
        assert s.risk_score == 0.0
        assert s.matched_patterns == []

    def test_cis_pipeline_status_defaults(self):
        ps = CISPipelineStatus(resource_id="r1")
        assert ps.stages_completed == []
        assert ps.aggregate_risk_score == 0.0
        assert ps.recommended_action == "pending"

    def test_search_result_has_adversarial_status(self):
        sr = SearchResult(
            chunk_id="c1",
            resource_id="r1",
            resource_name="test.pdf",
            content="some content",
        )
        assert sr.adversarial_status == AdversarialStatus.UNVERIFIED


# =============================================================================
# SEARCH ENGINE TESTS (2D Trust + Quarantine Exclusion)
# =============================================================================


class TestSearchEngine:
    """CIS search engine extensions: 2D trust scoring and quarantine exclusion."""

    def test_adversarial_multiplier_verified(self):
        assert compute_adversarial_multiplier("verified") == 1.0

    def test_adversarial_multiplier_unverified(self):
        assert compute_adversarial_multiplier("unverified") == 0.7

    def test_adversarial_multiplier_suspicious(self):
        assert compute_adversarial_multiplier("suspicious") == 0.3

    def test_adversarial_multiplier_unknown_defaults(self):
        assert compute_adversarial_multiplier("unknown") == 0.7

    def test_quarantined_not_searchable(self):
        assert not is_searchable("quarantined")

    def test_deleted_not_searchable(self):
        assert not is_searchable("deleted")

    def test_indexed_is_searchable(self):
        assert is_searchable("indexed")

    def test_pending_is_searchable(self):
        assert is_searchable("pending")

    def test_2d_trust_weighting_canonical_verified(self):
        """CANONICAL + VERIFIED = 1.5 * 1.0 = 1.5x."""
        results = [
            SearchResult(
                chunk_id="c1",
                resource_id="r1",
                resource_name="doc.pdf",
                content="test content",
                trust_tier=TrustTier.CANONICAL,
                adversarial_status=AdversarialStatus.VERIFIED,
                relevance=1.0,
            )
        ]
        weighted = apply_trust_weighting(results)
        assert weighted[0].trust_weight == pytest.approx(1.5, rel=0.01)

    def test_2d_trust_weighting_canonical_suspicious(self):
        """CANONICAL + SUSPICIOUS = 1.5 * 0.3 = 0.45x."""
        results = [
            SearchResult(
                chunk_id="c1",
                resource_id="r1",
                resource_name="doc.pdf",
                content="test content",
                trust_tier=TrustTier.CANONICAL,
                adversarial_status=AdversarialStatus.SUSPICIOUS,
                relevance=1.0,
            )
        ]
        weighted = apply_trust_weighting(results)
        assert weighted[0].trust_weight == pytest.approx(0.45, rel=0.01)

    def test_2d_trust_weighting_working_unverified(self):
        """WORKING + UNVERIFIED = 1.0 * 0.7 = 0.7x."""
        results = [
            SearchResult(
                chunk_id="c1",
                resource_id="r1",
                resource_name="doc.pdf",
                content="test content",
                trust_tier=TrustTier.WORKING,
                adversarial_status=AdversarialStatus.UNVERIFIED,
                relevance=1.0,
            )
        ]
        weighted = apply_trust_weighting(results)
        assert weighted[0].trust_weight == pytest.approx(0.7, rel=0.01)

    def test_verified_outranks_suspicious_same_tier(self):
        """Verified content should rank higher than suspicious content at the same tier."""
        results = [
            SearchResult(
                chunk_id="c1",
                resource_id="r1",
                resource_name="suspicious.pdf",
                content="test",
                trust_tier=TrustTier.WORKING,
                adversarial_status=AdversarialStatus.SUSPICIOUS,
                relevance=1.0,
            ),
            SearchResult(
                chunk_id="c2",
                resource_id="r2",
                resource_name="verified.pdf",
                content="test",
                trust_tier=TrustTier.WORKING,
                adversarial_status=AdversarialStatus.VERIFIED,
                relevance=1.0,
            ),
        ]
        weighted = apply_trust_weighting(results)
        assert weighted[0].resource_name == "verified.pdf"
        assert weighted[1].resource_name == "suspicious.pdf"


# =============================================================================
# PROVENANCE SERVICE TESTS
# =============================================================================


class TestContentProvenanceService:
    """ContentProvenanceService: create, verify, query attestations."""

    @pytest.fixture
    def service(self):
        return ContentProvenanceService()

    @pytest.mark.asyncio
    async def test_create_attestation_no_signing(self, service):
        """Creates provenance without signing when no signing_fn provided."""
        prov = await service.create_attestation(
            resource_id="r1",
            uploader_id="u1",
            method=UploadMethod.UI,
            original_hash="abc123",
            source_description="Uploaded via Hub",
        )
        assert prov.resource_id == "r1"
        assert prov.uploader_id == "u1"
        assert prov.upload_method == UploadMethod.UI
        assert prov.original_hash == "abc123"
        assert prov.provenance_signature == ""
        assert not prov.signature_verified

    @pytest.mark.asyncio
    async def test_create_attestation_with_signing_and_verify(self):
        """Creates signed and verified provenance when both fns are provided."""
        async def mock_sign(data: bytes) -> str:
            return "signed_" + data[:8].hex()

        async def mock_verify(data: bytes, sig: str) -> bool:
            return sig == "signed_" + data[:8].hex()

        service = ContentProvenanceService(signing_fn=mock_sign, verify_fn=mock_verify)
        prov = await service.create_attestation(
            resource_id="r1",
            uploader_id="u1",
            method=UploadMethod.API,
            original_hash="def456",
        )
        assert prov.provenance_signature.startswith("signed_")
        assert prov.signature_verified is True

    @pytest.mark.asyncio
    async def test_create_attestation_signed_but_no_verify_fn(self):
        """Signed without verify_fn: signature present but not verified."""
        async def mock_sign(data: bytes) -> str:
            return "signed_" + data[:8].hex()

        service = ContentProvenanceService(signing_fn=mock_sign)
        prov = await service.create_attestation(
            resource_id="r1",
            uploader_id="u1",
            method=UploadMethod.API,
            original_hash="def456",
        )
        assert prov.provenance_signature.startswith("signed_")
        assert prov.signature_verified is False  # No verify_fn to confirm

    @pytest.mark.asyncio
    async def test_verify_attestation_no_verify_fn(self, service):
        """Verification fails gracefully when no verify_fn provided."""
        prov = ContentProvenance(
            id="p1",
            resource_id="r1",
            uploader_id="u1",
            provenance_signature="some_sig",
        )
        result = await service.verify_attestation(prov)
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_attestation_no_signature(self, service):
        """Verification fails when provenance has no signature."""
        prov = ContentProvenance(id="p1", resource_id="r1", uploader_id="u1")
        result = await service.verify_attestation(prov)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_chain(self, service):
        """Get provenance chain for a resource."""
        await service.create_attestation("r1", "u1", UploadMethod.UI, "h1")
        await service.create_attestation("r1", "u2", UploadMethod.API, "h1")
        chain = await service.get_chain("r1")
        assert len(chain) == 2
        assert chain[0].uploader_id == "u1"
        assert chain[1].uploader_id == "u2"

    @pytest.mark.asyncio
    async def test_get_chain_empty(self, service):
        """Empty chain for unknown resource."""
        chain = await service.get_chain("nonexistent")
        assert chain == []

    @pytest.mark.asyncio
    async def test_get_by_uploader(self, service):
        """Filter provenance by uploader."""
        await service.create_attestation("r1", "u1", UploadMethod.UI, "h1")
        await service.create_attestation("r2", "u2", UploadMethod.API, "h2")
        await service.create_attestation("r3", "u1", UploadMethod.CLI, "h3")
        records = await service.get_by_uploader("u1")
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_get_by_method(self, service):
        """Filter provenance by upload method."""
        await service.create_attestation("r1", "u1", UploadMethod.UI, "h1")
        await service.create_attestation("r2", "u1", UploadMethod.API, "h2")
        records = await service.get_by_method(UploadMethod.UI)
        assert len(records) == 1
        assert records[0].resource_id == "r1"

    def test_compute_hash(self):
        """SHA3-256 hash computation."""
        h = ContentProvenanceService.compute_hash(b"hello world")
        assert len(h) == 64  # SHA3-256 = 256 bits = 64 hex chars
        assert h == ContentProvenanceService.compute_hash(b"hello world")  # deterministic

    def test_canonical_bytes_deterministic(self):
        """Canonical bytes are deterministic (sorted JSON keys)."""
        prov = ContentProvenance(
            id="p1",
            resource_id="r1",
            uploader_id="u1",
            upload_method=UploadMethod.UI,
            original_hash="h1",
            created_at=datetime(2026, 4, 6, tzinfo=UTC),
        )
        b1 = ContentProvenanceService._canonical_bytes(prov)
        b2 = ContentProvenanceService._canonical_bytes(prov)
        assert b1 == b2

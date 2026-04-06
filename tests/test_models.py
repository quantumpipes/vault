"""Tests for qp-vault domain models."""

from qp_vault.enums import (
    DataClassification,
    EventType,
    Lifecycle,
    MemoryLayer,
    ResourceStatus,
    ResourceType,
    TrustTier,
)
from qp_vault.models import (
    Chunk,
    Resource,
    SearchResult,
    VaultEvent,
    VaultVerificationResult,
    VerificationResult,
)


class TestResource:
    def test_defaults(self):
        r = Resource(id="test-1", name="doc.md", content_hash="abc123")
        assert r.trust_tier == TrustTier.WORKING
        assert r.data_classification == DataClassification.INTERNAL
        assert r.resource_type == ResourceType.DOCUMENT
        assert r.status == ResourceStatus.PENDING
        assert r.lifecycle == Lifecycle.ACTIVE
        assert r.tags == []
        assert r.metadata == {}
        assert r.chunk_count == 0

    def test_trust_tiers(self):
        for tier in TrustTier:
            r = Resource(id="t", name="t", content_hash="h", trust_tier=tier)
            assert r.trust_tier == tier

    def test_lifecycle_states(self):
        for state in Lifecycle:
            r = Resource(id="t", name="t", content_hash="h", lifecycle=state)
            assert r.lifecycle == state

    def test_memory_layers(self):
        for layer in MemoryLayer:
            r = Resource(id="t", name="t", content_hash="h", layer=layer)
            assert r.layer == layer


class TestChunk:
    def test_defaults(self):
        c = Chunk(id="c-1", resource_id="r-1", content="Hello world")
        assert c.embedding is None
        assert c.chunk_index == 0
        assert c.token_count == 0
        assert c.speaker is None

    def test_with_embedding(self):
        c = Chunk(
            id="c-1",
            resource_id="r-1",
            content="Hello",
            embedding=[0.1, 0.2, 0.3],
        )
        assert len(c.embedding) == 3


class TestSearchResult:
    def test_scoring_fields(self):
        r = SearchResult(
            chunk_id="c-1",
            resource_id="r-1",
            resource_name="doc.md",
            content="test content",
            vector_similarity=0.85,
            text_rank=0.6,
            trust_weight=1.5,
            freshness=0.9,
            relevance=0.95,
        )
        assert r.vector_similarity == 0.85
        assert r.trust_weight == 1.5
        assert r.trust_tier == TrustTier.WORKING


class TestVaultEvent:
    def test_create_event(self):
        e = VaultEvent(
            event_type=EventType.CREATE,
            resource_id="r-1",
            resource_name="doc.md",
            resource_hash="abc123",
        )
        assert e.event_type == EventType.CREATE
        assert e.actor is None


class TestVerification:
    def test_verification_result(self):
        v = VerificationResult(
            resource_id="r-1",
            passed=True,
            stored_hash="abc",
            computed_hash="abc",
            chunk_count=5,
        )
        assert v.passed
        assert v.failed_chunks == []

    def test_vault_verification_result(self):
        v = VaultVerificationResult(
            passed=True,
            merkle_root="root_hash",
            resource_count=100,
            verified_count=100,
        )
        assert v.passed
        assert v.failed_resources == []


class TestEnumValues:
    def test_trust_tier_values(self):
        assert TrustTier.CANONICAL.value == "canonical"
        assert TrustTier.WORKING.value == "working"
        assert TrustTier.EPHEMERAL.value == "ephemeral"
        assert TrustTier.ARCHIVED.value == "archived"

    def test_data_classification_values(self):
        assert DataClassification.PUBLIC.value == "public"
        assert DataClassification.RESTRICTED.value == "restricted"

    def test_lifecycle_values(self):
        assert Lifecycle.DRAFT.value == "draft"
        assert Lifecycle.SUPERSEDED.value == "superseded"

    def test_memory_layer_values(self):
        assert MemoryLayer.OPERATIONAL.value == "operational"
        assert MemoryLayer.STRATEGIC.value == "strategic"
        assert MemoryLayer.COMPLIANCE.value == "compliance"

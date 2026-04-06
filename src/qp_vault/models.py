"""Domain models for qp-vault."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field

from qp_vault.enums import (
    AdversarialStatus,
    CISResult,
    CISStage,
    DataClassification,
    EventType,
    Lifecycle,
    MemoryLayer,
    ResourceStatus,
    ResourceType,
    TrustTier,
    UploadMethod,
)


def _utcnow() -> datetime:
    """Timezone-aware UTC now. Used as Pydantic default_factory."""
    return datetime.now(tz=UTC)


class Resource(BaseModel):
    """A document, file, or content unit stored in the Vault."""

    id: str
    name: str
    content_hash: str
    cid: str = ""

    # Classification
    trust_tier: TrustTier = TrustTier.WORKING
    data_classification: DataClassification = DataClassification.INTERNAL
    resource_type: ResourceType = ResourceType.DOCUMENT

    # Status and lifecycle
    status: ResourceStatus = ResourceStatus.PENDING
    lifecycle: Lifecycle = Lifecycle.ACTIVE
    adversarial_status: AdversarialStatus = AdversarialStatus.UNVERIFIED
    valid_from: date | None = None
    valid_until: date | None = None
    supersedes: str | None = None
    superseded_by: str | None = None

    # Multi-tenancy
    tenant_id: str | None = None

    # Organization
    collection_id: str | None = None
    layer: MemoryLayer | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # File info
    mime_type: str | None = None
    size_bytes: int = 0
    chunk_count: int = 0
    merkle_root: str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    indexed_at: datetime | None = None
    deleted_at: datetime | None = None


class Chunk(BaseModel):
    """A semantic unit of text from a Resource, with optional embedding."""

    id: str
    resource_id: str
    content: str
    cid: str = ""
    embedding: list[float] | None = None

    # Position
    chunk_index: int = 0
    page_number: int | None = None
    section_title: str | None = None
    token_count: int = 0

    # Speaker (for transcripts)
    speaker: str | None = None


class Collection(BaseModel):
    """Logical grouping of Resources."""

    id: str
    name: str
    description: str = ""
    is_public: bool = False
    resource_count: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SearchResult(BaseModel):
    """A single search result with relevance scoring."""

    chunk_id: str
    resource_id: str
    resource_name: str
    collection_name: str | None = None
    content: str
    page_number: int | None = None
    section_title: str | None = None

    # Scoring
    vector_similarity: float = 0.0
    text_rank: float = 0.0
    trust_weight: float = 1.0
    freshness: float = 1.0
    relevance: float = 0.0

    # Resource metadata (for ranking and display)
    updated_at: str | None = None
    created_at: str | None = None
    resource_type: str | None = None
    data_classification: str | None = None

    # Provenance
    trust_tier: TrustTier = TrustTier.WORKING
    adversarial_status: AdversarialStatus = AdversarialStatus.UNVERIFIED
    cid: str | None = None
    lifecycle: Lifecycle = Lifecycle.ACTIVE


class VaultEvent(BaseModel):
    """Emitted on every vault mutation. Consumed by AuditProvider."""

    event_type: EventType
    resource_id: str
    resource_name: str = ""
    resource_hash: str = ""
    actor: str | None = None
    timestamp: datetime = Field(default_factory=_utcnow)
    details: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    """Result of verifying a single resource."""

    resource_id: str
    passed: bool
    stored_hash: str
    computed_hash: str
    chunk_count: int = 0
    failed_chunks: list[str] = Field(default_factory=list)


class VaultVerificationResult(BaseModel):
    """Result of verifying the entire vault."""

    passed: bool
    merkle_root: str
    resource_count: int = 0
    verified_count: int = 0
    failed_resources: list[VerificationResult] = Field(default_factory=list)
    duration_ms: int = 0


class MerkleProof(BaseModel):
    """Cryptographic proof that a resource belongs to the vault's Merkle tree."""

    resource_id: str
    resource_hash: str
    merkle_root: str
    path: list[dict[str, str]] = Field(default_factory=list)
    leaf_index: int = 0
    tree_size: int = 0


class HealthScore(BaseModel):
    """Composite integrity assessment."""

    overall: float = 0.0
    coherence: float = 0.0
    freshness: float = 0.0
    uniqueness: float = 0.0
    connectivity: float = 0.0
    trust_alignment: float = 0.0
    issue_count: int = 0
    resource_count: int = 0


# --- Content Immune System models ---


class ContentProvenance(BaseModel):
    """Cryptographic attestation of a document's origin and chain of custody.

    Every document entering the Vault gets a provenance record signed with
    Ed25519 (+ optional ML-DSA-65). This creates accountability: who uploaded
    what, when, and how.
    """

    id: str
    resource_id: str
    uploader_id: str
    upload_method: UploadMethod = UploadMethod.API
    source_description: str = ""
    original_hash: str = ""
    provenance_signature: str = ""
    signature_verified: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class CISStageRecord(BaseModel):
    """Result of a single CIS pipeline stage evaluation.

    Every stage (INGEST through REMEMBER) creates one record per document.
    Records are immutable once created.
    """

    id: str
    resource_id: str
    stage: CISStage
    result: CISResult = CISResult.PASS
    risk_score: float = 0.0
    reasoning: str = ""
    matched_patterns: list[str] = Field(default_factory=list)
    capsule_id: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class CISPipelineStatus(BaseModel):
    """Aggregate status of the CIS pipeline for a single document."""

    resource_id: str
    stages_completed: list[CISStage] = Field(default_factory=list)
    stages_pending: list[CISStage] = Field(default_factory=list)
    aggregate_risk_score: float = 0.0
    recommended_action: str = "pending"
    stage_results: list[CISStageRecord] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

"""Enumerations for qp-vault domain concepts."""

from enum import StrEnum


class TrustTier(StrEnum):
    """Governance classification for resources.

    Affects search ranking via trust_weight multiplier.
    """

    CANONICAL = "canonical"
    """Immutable, authoritative. 1.5x search boost."""

    WORKING = "working"
    """Editable, default. 1.0x baseline."""

    EPHEMERAL = "ephemeral"
    """Temporary, auto-purge after TTL. 0.7x penalty."""

    ARCHIVED = "archived"
    """Historical, low relevance. 0.25x penalty."""


class DataClassification(StrEnum):
    """Sensitivity level controlling AI provider routing."""

    PUBLIC = "public"
    """Cloud AI allowed."""

    INTERNAL = "internal"
    """Default. Cloud AI allowed."""

    CONFIDENTIAL = "confidential"
    """Local models only. Encryption required."""

    RESTRICTED = "restricted"
    """Local only. Strict audit. Every read logged."""


class ResourceType(StrEnum):
    """Content type of a vault resource."""

    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    NOTE = "note"
    CODE = "code"
    SPREADSHEET = "spreadsheet"
    TRANSCRIPT = "transcript"
    OTHER = "other"


class ResourceStatus(StrEnum):
    """Processing status of a resource."""

    PENDING = "pending"
    """Registered, not yet processed."""

    QUARANTINED = "quarantined"
    """CIS screening in progress. Excluded from search and RAG retrieval."""

    PROCESSING = "processing"
    """Being chunked and embedded."""

    INDEXED = "indexed"
    """Ready for search."""

    ERROR = "error"
    """Processing failed."""

    DELETED = "deleted"
    """Soft-deleted (recoverable)."""


class AdversarialStatus(StrEnum):
    """CIS adversarial verification status (second dimension of trust).

    Orthogonal to TrustTier (organizational confidence).
    Effective RAG weight = trust_tier_weight * adversarial_multiplier.
    """

    UNVERIFIED = "unverified"
    """Not yet screened by CIS. Default for legacy content. Multiplier: 0.7x."""

    VERIFIED = "verified"
    """Passed all CIS stages. Multiplier: 1.0x."""

    SUSPICIOUS = "suspicious"
    """Flagged by one or more CIS stages. Multiplier: 0.3x."""


class CISStage(StrEnum):
    """Content Immune System pipeline stages."""

    INGEST = "ingest"
    """Stage 1: Provenance recording, format validation."""

    INNATE_SCAN = "innate_scan"
    """Stage 2: Pattern-based detection (ExternalContentGuard)."""

    ADAPTIVE_SCAN = "adaptive_scan"
    """Stage 3: LLM-based semantic screening (Paranoid Twin)."""

    CORRELATE = "correlate"
    """Stage 4: Cross-document analysis, temporal anomaly detection."""

    RELEASE = "release"
    """Stage 5: Risk-proportionate release with approval gates."""

    SURVEIL = "surveil"
    """Stage 6: Query-context re-evaluation at RAG retrieval time."""

    PRESENT = "present"
    """Stage 7: Source transparency, risk badges in approval UX."""

    REMEMBER = "remember"
    """Stage 8: Attack Pattern Registry feedback loop."""


class CISResult(StrEnum):
    """Result of a single CIS stage evaluation."""

    PASS = "pass"
    """Content cleared this stage."""

    FLAG = "flag"
    """Content flagged for human review."""

    FAIL = "fail"
    """Content blocked (if block_mode enabled)."""

    SKIP = "skip"
    """Stage skipped (disabled or degraded mode)."""


class UploadMethod(StrEnum):
    """How a document entered the Vault."""

    UI = "ui"
    """Uploaded via Hub web interface."""

    API = "api"
    """Uploaded via REST API."""

    CLI = "cli"
    """Uploaded via qp CLI."""

    EMAIL = "email"
    """Ingested from email (Comms)."""

    IMPORT = "import"
    """Bulk import or migration."""


class Lifecycle(StrEnum):
    """Knowledge lifecycle state."""

    DRAFT = "draft"
    """In preparation."""

    REVIEW = "review"
    """Under review or approval."""

    ACTIVE = "active"
    """Current, authoritative."""

    SUPERSEDED = "superseded"
    """Replaced by newer version."""

    EXPIRED = "expired"
    """Past valid_until date."""

    ARCHIVED = "archived"
    """Terminal state."""


class MemoryLayer(StrEnum):
    """Semantic partition of vault knowledge."""

    OPERATIONAL = "operational"
    """SOPs, runbooks, active procedures."""

    STRATEGIC = "strategic"
    """Decisions, OKRs, ADRs, architecture records."""

    COMPLIANCE = "compliance"
    """Audit evidence, certifications, regulatory docs."""


class EventType(StrEnum):
    """Types of vault mutation events."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    TRUST_CHANGE = "trust_change"
    CLASSIFICATION_CHANGE = "classification_change"
    LIFECYCLE_TRANSITION = "lifecycle_transition"
    SUPERSEDE = "supersede"
    VERIFY = "verify"
    SEARCH = "search"
    CIS_SCAN = "cis_scan"
    CIS_RELEASE = "cis_release"
    CIS_FLAG = "cis_flag"
    ADVERSARIAL_STATUS_CHANGE = "adversarial_status_change"

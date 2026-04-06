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

    PROCESSING = "processing"
    """Being chunked and embedded."""

    INDEXED = "indexed"
    """Ready for search."""

    ERROR = "error"
    """Processing failed."""

    DELETED = "deleted"
    """Soft-deleted (recoverable)."""


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

"""Knowledge graph domain models.

Pure Pydantic models with zero Core dependencies. Ported from
quantumpipes.vault.models (graph section) and
quantumpipes.services.entity_detector (DetectedEntity).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """A node in the knowledge graph representing a real-world entity.

    Entity types are emergent, not prescribed. The system discovers types
    from the data it processes (person, gene, theorem, spacecraft, protocol,
    or any domain-specific type).

    Args:
        id: Primary key.
        tenant_id: Tenant isolation boundary.
        name: Canonical display name.
        slug: URL-safe identifier, auto-generated from name.
        entity_type: Emergent type label discovered from data.
        properties: Structured key-value attributes (schema varies by type).
        tags: Searchable tags array.
        primary_space_id: Space where profile files live.
        resource_id: profile.md vault resource.
        manifest_resource_id: manifest.json vault resource.
        mention_count: Denormalized count of mentions across resources.
        last_mentioned_at: Most recent mention timestamp.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID = Field(default_factory=uuid4)
    name: str = Field(..., max_length=500)
    slug: str = Field(..., max_length=500)
    entity_type: str = Field(..., max_length=50)
    properties: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    primary_space_id: UUID | None = Field(default=None)
    resource_id: UUID | None = Field(default=None)
    manifest_resource_id: UUID | None = Field(default=None)
    mention_count: int = Field(default=0, ge=0)
    last_mentioned_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}


class GraphEdge(BaseModel):
    """A directed relationship between two graph nodes.

    Relation types are emergent, not prescribed. Each edge has a weight
    (0.0-1.0) indicating relationship strength, an optional bidirectional
    flag, and an optional source document reference.

    Args:
        id: Primary key.
        tenant_id: Tenant isolation boundary.
        source_node_id: Source entity.
        target_node_id: Target entity.
        relation_type: Emergent relation label discovered from data.
        properties: Edge metadata.
        weight: Relationship strength (0.0-1.0).
        bidirectional: Whether edge applies both directions.
        source_resource_id: Document establishing this relationship.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID = Field(default_factory=uuid4)
    source_node_id: UUID = Field(...)
    target_node_id: UUID = Field(...)
    relation_type: str = Field(..., max_length=100)
    properties: dict[str, Any] = Field(default_factory=dict)
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    bidirectional: bool = Field(default=False)
    source_resource_id: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}


class GraphMention(BaseModel):
    """Tracks where an entity is mentioned across vault resources.

    Powers the backlink index: for any entity, find all resources that
    reference it. One mention record per entity per resource (deduped via
    unique constraint).

    Args:
        id: Primary key.
        node_id: The mentioned entity.
        resource_id: The document containing the mention.
        space_id: Space context (denormalized for query performance).
        context_snippet: Surrounding text for preview (max 500 chars).
        mentioned_at: When the mention was recorded.
    """

    id: UUID = Field(default_factory=uuid4)
    node_id: UUID = Field(...)
    resource_id: UUID = Field(...)
    space_id: UUID | None = Field(default=None)
    context_snippet: str = Field(default="", max_length=500)
    mentioned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = {"from_attributes": True}


class NeighborResult(BaseModel):
    """Result from a graph traversal query (N-hop neighbors)."""

    node_id: UUID
    node_name: str
    entity_type: str
    depth: int
    path: list[UUID] = Field(default_factory=list)
    relation_type: str | None = None
    edge_weight: float | None = None

    model_config = {"from_attributes": True}


class GraphScanJob(BaseModel):
    """Persistent record for a knowledge-graph extraction scan job.

    Tracks lifecycle of space-level scans: running, completed, failed,
    cancelled.

    Args:
        id: Primary key.
        tenant_id: Tenant isolation boundary.
        space_id: Space being scanned.
        status: running | completed | failed | cancelled | cancelling.
        started_at: Scan start time.
        finished_at: Scan completion time.
        summary: Extraction summary counters.
        error: Error message if failed.
    """

    id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID = Field(default_factory=uuid4)
    space_id: UUID = Field(...)
    status: str = Field(default="running")
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = Field(default=None)
    summary: dict[str, int] | None = Field(default=None)
    error: str | None = Field(default=None)

    model_config = {"from_attributes": True}


class DetectedEntity(BaseModel):
    """An entity detected in text by the EntityDetector.

    Args:
        name: Entity display name as found in text.
        entity_type: Detected type label.
        node_id: Resolved graph node UUID (if resolved).
        confidence: Detection confidence score (0.0-1.0).
        start: Character offset in source text.
        end: Character offset end in source text.
    """

    name: str
    entity_type: str = Field(default="unknown")
    node_id: UUID | None = Field(default=None)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    start: int | None = Field(default=None)
    end: int | None = Field(default=None)

    model_config = {"from_attributes": True}

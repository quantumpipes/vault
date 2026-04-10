"""GraphEngine: Knowledge graph operations on an AsyncVault instance.

Wraps GraphStorageBackend with business logic (slug generation,
self-edge rejection, merge orchestration), Pydantic model conversion,
and VaultEvent firing on every mutation.

Access via ``vault.graph``. Returns ``None`` from ``vault.graph`` when
graph storage is not initialized (document-only mode).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from qp_vault.enums import EventType
from qp_vault.graph.models import (
    DetectedEntity,
    GraphEdge,
    GraphMention,
    GraphNode,
    GraphScanJob,
    NeighborResult,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from qp_vault.protocols import GraphStorageBackend

logger = logging.getLogger(__name__)

_MAX_NAME_LENGTH = 500
_MAX_TYPE_LENGTH = 50
_MAX_RELATION_LENGTH = 100
_MAX_PROPERTIES_SIZE = 50_000  # bytes, JSON-serialized
_MAX_TAGS = 50
_MAX_TAG_LENGTH = 100
_MAX_LIST_LIMIT = 10_000
_MAX_CONTEXT_IDS = 50
_VALID_DIRECTIONS = frozenset({"outgoing", "incoming", "both"})


def _strip_null_bytes(s: str) -> str:
    """Remove null bytes that can corrupt storage engines."""
    return s.replace("\x00", "")


def _validate_name(name: str) -> str:
    """Validate and truncate entity name."""
    if not name or not name.strip():
        raise ValueError("Entity name must not be empty")
    return _strip_null_bytes(name[:_MAX_NAME_LENGTH].strip())


def _validate_type(entity_type: str) -> str:
    """Validate and truncate entity/relation type."""
    if not entity_type or not entity_type.strip():
        raise ValueError("Entity type must not be empty")
    return _strip_null_bytes(entity_type[:_MAX_TYPE_LENGTH].strip())


def _validate_relation_type(relation_type: str) -> str:
    """Validate and truncate relation type."""
    if not relation_type or not relation_type.strip():
        raise ValueError("Relation type must not be empty")
    return _strip_null_bytes(relation_type[:_MAX_RELATION_LENGTH].strip())


def _validate_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    """Validate properties dict size and per-value limits.

    Returns a (possibly truncated) copy. Never mutates the caller's dict.
    """
    import json as _json
    if properties is None:
        return {}
    cleaned = {}
    for k, v in properties.items():
        if isinstance(v, str) and len(v) > 2000:
            cleaned[k] = v[:2000]
        else:
            cleaned[k] = v
    serialized = _json.dumps(cleaned, default=str)
    if len(serialized) > _MAX_PROPERTIES_SIZE:
        raise ValueError(
            f"Properties exceed {_MAX_PROPERTIES_SIZE} bytes "
            f"({len(serialized)} bytes serialized)"
        )
    return cleaned


def _validate_tags(tags: list[str] | None) -> list[str]:
    """Validate tag list length and individual tag lengths."""
    if tags is None:
        return []
    if len(tags) > _MAX_TAGS:
        raise ValueError(f"Too many tags ({len(tags)}), maximum {_MAX_TAGS}")
    clean: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = _strip_null_bytes(tag.strip())
        if not tag:
            continue
        if len(tag) > _MAX_TAG_LENGTH:
            raise ValueError(f"Tag exceeds {_MAX_TAG_LENGTH} chars")
        clean.append(tag)
    return clean


def _validate_weight(weight: float) -> float:
    """Validate edge weight is within 0.0-1.0."""
    if not isinstance(weight, (int, float)):
        raise ValueError("Weight must be a number")
    weight = float(weight)
    if weight < 0.0 or weight > 1.0:
        raise ValueError(f"Weight must be 0.0-1.0, got {weight}")
    return weight


def _cap_limit(limit: int) -> int:
    """Cap list/query limits to prevent resource exhaustion."""
    return min(max(1, limit), _MAX_LIST_LIMIT)


def slugify(name: str) -> str:
    """Generate a URL-safe slug from an entity name.

    Args:
        name: The entity display name.

    Returns:
        A lowercase, hyphenated slug safe for URLs.
    """
    normalized = unicodedata.normalize("NFKD", name)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug or "entity"


class GraphEngine:
    """Knowledge graph operations on an AsyncVault instance.

    Provides typed async methods for node/edge CRUD, traversal,
    mention tracking, merging, and scan orchestration. Every mutation
    fires a VaultEvent through the vault's audit path.

    Args:
        storage: A GraphStorageBackend implementation.
        vault: The owning AsyncVault (for event firing and tenant context).
    """

    def __init__(
        self,
        storage: GraphStorageBackend,
        vault: Any,
    ) -> None:
        self._storage = storage
        self._vault = vault
        self._extractor: Any | None = None
        self._detector: Any | None = None

    def set_chat_fn(self, chat_fn: Callable[..., Any]) -> None:
        """Configure LLM callback for KnowledgeExtractor."""
        if self._extractor is not None:
            self._extractor.set_chat_fn(chat_fn)

    def set_extractor(self, extractor: Any) -> None:
        """Inject a KnowledgeExtractor instance."""
        self._extractor = extractor

    def set_detector(self, detector: Any) -> None:
        """Inject an EntityDetector instance."""
        self._detector = detector

    # --- Event Firing ---

    async def _fire_event(self, event_type: EventType, **kwargs: Any) -> None:
        """Fire a VaultEvent for a graph mutation."""
        from qp_vault.models import VaultEvent

        event = VaultEvent(
            event_type=event_type,
            resource_id=kwargs.get("resource_id", ""),
            resource_name=kwargs.get("resource_name", ""),
            resource_hash=kwargs.get("resource_hash", ""),
            details=kwargs.get("details") or {},
            actor=kwargs.get("actor"),
        )
        if hasattr(self._vault, "_auditor") and self._vault._auditor is not None:
            try:
                await self._vault._auditor.record(event)
            except Exception:
                logger.warning("Failed to record graph audit event", exc_info=True)

        if hasattr(self._vault, "_notify_subscribers"):
            try:
                await self._vault._notify_subscribers(event)
            except Exception:
                logger.warning("Failed to notify graph event subscribers", exc_info=True)

    # --- Slug Helpers ---

    async def _unique_slug(self, name: str, *, exclude_id: str | None = None) -> str:
        """Generate a unique slug, appending -2, -3 etc. on collision.

        Loads existing slugs once, then checks candidates against the set.
        Falls back to UUID suffix after 99 collisions.
        """
        base = slugify(name)

        all_nodes, _ = await self._storage.list_nodes({"limit": 10000})
        taken_slugs = {
            r.get("slug")
            for r in all_nodes
            if str(r.get("id")) != str(exclude_id)
        }

        candidate = base
        if candidate not in taken_slugs:
            return candidate

        for suffix in range(2, 101):
            candidate = f"{base}-{suffix}"
            if candidate not in taken_slugs:
                return candidate

        return f"{base}-{uuid4().hex[:6]}"

    # --- Node CRUD ---

    async def create_node(
        self,
        *,
        name: str,
        entity_type: str,
        properties: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        primary_space_id: UUID | str | None = None,
        tenant_id: UUID | str | None = None,
    ) -> GraphNode:
        """Create a new graph node (entity).

        Args:
            name: Canonical display name.
            entity_type: person, company, concept, etc.
            properties: Structured key-value attributes.
            tags: Searchable tags.
            primary_space_id: Space where profile files live.
            tenant_id: Owning tenant UUID.

        Returns:
            The created GraphNode.
        """
        name = _validate_name(name)
        entity_type = _validate_type(entity_type)
        properties = _validate_properties(properties)
        tags = _validate_tags(tags)

        resolved_tenant = self._resolve_tenant(tenant_id)
        slug = await self._unique_slug(name)
        node_id = uuid4()

        node_dict: dict[str, Any] = {
            "id": str(node_id),
            "tenant_id": str(resolved_tenant),
            "name": name,
            "slug": slug,
            "entity_type": entity_type,
            "properties": properties,
            "tags": tags,
            "primary_space_id": str(primary_space_id) if primary_space_id else None,
            "mention_count": 0,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

        await self._storage.store_node(node_dict)

        node = self._dict_to_node(node_dict)

        await self._fire_event(
            EventType.ENTITY_CREATE,
            resource_id=str(node_id),
            resource_name=f"entity_create {name}",
            details={"entity_type": entity_type, "name": name},
            actor=str(resolved_tenant),
        )

        return node

    async def get_node(self, node_id: UUID | str) -> GraphNode | None:
        """Get a graph node by ID.

        Args:
            node_id: The node's primary key.

        Returns:
            The GraphNode, or None if not found.
        """
        d = await self._storage.get_node(str(node_id))
        if d is None:
            return None
        return self._dict_to_node(d)

    async def list_nodes(
        self,
        *,
        space_id: UUID | str | None = None,
        entity_type: str | None = None,
        tags: list[str] | None = None,
        tenant_id: UUID | str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GraphNode], int]:
        """List graph nodes with optional filtering.

        Args:
            space_id: Filter by primary or cross-space membership.
            entity_type: Filter by entity type.
            tags: Filter by tags.
            tenant_id: Filter by tenant.
            limit: Max results.
            offset: Pagination offset.

        Returns:
            Tuple of (nodes, total_count).
        """
        limit = _cap_limit(limit)
        filters: dict[str, Any] = {"limit": limit, "offset": offset}
        if space_id:
            filters["space_id"] = str(space_id)
        if entity_type:
            filters["entity_type"] = entity_type
        if tags:
            filters["tags"] = tags
        if tenant_id:
            filters["tenant_id"] = str(tenant_id)

        rows, total = await self._storage.list_nodes(filters)
        return [self._dict_to_node(r) for r in rows], total

    async def search_nodes(
        self,
        query: str,
        *,
        space_id: UUID | str | None = None,
        limit: int = 20,
    ) -> list[GraphNode]:
        """Search graph nodes by name.

        Args:
            query: Search text.
            space_id: Optional space filter.
            limit: Max results (capped at 10,000).

        Returns:
            Matching nodes ordered by similarity. Empty list for empty queries.
        """
        if not query or not query.strip():
            return []
        limit = _cap_limit(limit)
        rows = await self._storage.search_nodes(
            query, str(space_id) if space_id else None, limit,
        )
        return [self._dict_to_node(r) for r in rows]

    async def update_node(self, node_id: UUID | str, **updates: Any) -> GraphNode:
        """Update a graph node's fields.

        Args:
            node_id: The node to update.
            **updates: Fields to update (name, entity_type, properties, tags, primary_space_id).

        Returns:
            The updated GraphNode.

        Raises:
            ValueError: If node does not exist.
        """
        allowed = {"name", "entity_type", "properties", "tags", "primary_space_id"}
        patch: dict[str, Any] = {k: v for k, v in updates.items() if k in allowed and v is not None}

        if "name" in patch:
            patch["name"] = _validate_name(patch["name"])
            patch["slug"] = await self._unique_slug(patch["name"], exclude_id=str(node_id))
        if "entity_type" in patch:
            patch["entity_type"] = _validate_type(patch["entity_type"])
        if "properties" in patch:
            patch["properties"] = _validate_properties(patch["properties"])
        if "tags" in patch:
            patch["tags"] = _validate_tags(patch["tags"])

        d = await self._storage.update_node(str(node_id), patch)
        node = self._dict_to_node(d)

        await self._fire_event(
            EventType.ENTITY_UPDATE,
            resource_id=str(node_id),
            resource_name=f"entity_update {node.name}",
            details={"updated_fields": list(patch.keys())},
        )

        return node

    async def delete_node(self, node_id: UUID | str) -> None:
        """Delete a graph node and cascade edges, mentions, and space memberships.

        Args:
            node_id: The node to delete.
        """
        node = await self.get_node(node_id)
        name = node.name if node else str(node_id)

        await self._storage.delete_node(str(node_id))

        await self._fire_event(
            EventType.ENTITY_DELETE,
            resource_id=str(node_id),
            resource_name=f"entity_delete {name}",
        )

    # --- Edge CRUD ---

    async def create_edge(
        self,
        *,
        source_id: UUID | str,
        target_id: UUID | str,
        relation_type: str,
        properties: dict[str, Any] | None = None,
        weight: float = 0.5,
        bidirectional: bool = False,
        source_resource_id: UUID | str | None = None,
        tenant_id: UUID | str | None = None,
    ) -> GraphEdge:
        """Create a relationship between two nodes.

        Args:
            source_id: Source node ID.
            target_id: Target node ID.
            relation_type: Relationship type (works_at, knows, etc.).
            properties: Edge metadata.
            weight: Relationship strength (0.0-1.0).
            bidirectional: Whether edge applies both directions.
            source_resource_id: Document establishing this relationship.
            tenant_id: Owning tenant UUID.

        Returns:
            The created GraphEdge.

        Raises:
            ValueError: If source equals target (self-edge).
        """
        if str(source_id) == str(target_id):
            raise ValueError("Self-edges are not allowed")

        relation_type = _validate_relation_type(relation_type)
        properties = _validate_properties(properties)
        weight = _validate_weight(weight)

        resolved_tenant = self._resolve_tenant(tenant_id)
        edge_id = uuid4()

        edge_dict: dict[str, Any] = {
            "id": str(edge_id),
            "tenant_id": str(resolved_tenant),
            "source_node_id": str(source_id),
            "target_node_id": str(target_id),
            "relation_type": relation_type,
            "properties": properties,
            "weight": weight,
            "bidirectional": bidirectional,
            "source_resource_id": str(source_resource_id) if source_resource_id else None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }

        await self._storage.store_edge(edge_dict)
        edge = self._dict_to_edge(edge_dict)

        await self._fire_event(
            EventType.EDGE_CREATE,
            resource_id=str(edge_id),
            resource_name=f"edge_create {relation_type}",
            details={
                "source_node_id": str(source_id),
                "target_node_id": str(target_id),
                "relation_type": relation_type,
            },
        )

        return edge

    async def get_edges(
        self,
        node_id: UUID | str,
        *,
        direction: str = "both",
    ) -> list[GraphEdge]:
        """Get all edges connected to a node.

        Args:
            node_id: The node to query.
            direction: "outgoing", "incoming", or "both".

        Returns:
            List of connected edges.
        """
        if direction not in _VALID_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(_VALID_DIRECTIONS)}, got {direction!r}")
        rows = await self._storage.get_edges(str(node_id), direction)
        return [self._dict_to_edge(r) for r in rows]

    async def update_edge(self, edge_id: UUID | str, **updates: Any) -> GraphEdge:
        """Update an edge's fields.

        Args:
            edge_id: The edge to update.
            **updates: Fields to update (relation_type, properties, weight, bidirectional).

        Returns:
            The updated GraphEdge.
        """
        allowed = {"relation_type", "properties", "weight", "bidirectional"}
        patch = {k: v for k, v in updates.items() if k in allowed and v is not None}

        if "relation_type" in patch:
            patch["relation_type"] = _validate_relation_type(patch["relation_type"])
        if "properties" in patch:
            patch["properties"] = _validate_properties(patch["properties"])
        if "weight" in patch:
            patch["weight"] = _validate_weight(patch["weight"])

        d = await self._storage.update_edge(str(edge_id), patch)
        return self._dict_to_edge(d)

    async def delete_edge(self, edge_id: UUID | str) -> None:
        """Delete an edge.

        Args:
            edge_id: The edge to delete.
        """
        await self._storage.delete_edge(str(edge_id))

        await self._fire_event(
            EventType.EDGE_DELETE,
            resource_id=str(edge_id),
            resource_name=f"edge_delete {edge_id}",
        )

    # --- Traversal ---

    async def neighbors(
        self,
        node_id: UUID | str,
        *,
        depth: int = 1,
        relation_types: list[str] | None = None,
        space_id: UUID | str | None = None,
    ) -> list[NeighborResult]:
        """Get N-hop neighbors.

        Args:
            node_id: Starting node.
            depth: Max traversal depth (1-3).
            relation_types: Filter by relationship types.
            space_id: Filter by space membership.

        Returns:
            List of neighbor results with depth and path info.
        """
        depth = min(depth, 3)
        rows = await self._storage.neighbors(
            str(node_id), depth, relation_types,
            str(space_id) if space_id else None,
        )
        return [
            NeighborResult(
                node_id=UUID(str(r["node_id"])),
                node_name=r["node_name"],
                entity_type=r["entity_type"],
                depth=r["depth"],
                path=[UUID(str(p)) for p in (r.get("path") or [])],
                relation_type=r.get("relation_type"),
                edge_weight=r.get("edge_weight"),
            )
            for r in rows
        ]

    async def context_for(self, entity_ids: list[UUID | str]) -> str:
        """Build a structured markdown summary for LLM prompts.

        Args:
            entity_ids: List of entity UUIDs to summarize.

        Returns:
            Markdown string with entity names, types, properties, and relationships.
        """
        if not entity_ids:
            return ""

        entity_ids = entity_ids[:_MAX_CONTEXT_IDS]
        sections: list[str] = ["## Knowledge Graph Context\n"]

        for eid in entity_ids:
            node = await self.get_node(eid)
            if not node:
                continue

            section = f"### {node.name} ({node.entity_type})\n"

            if node.properties:
                props = ", ".join(
                    f"{k}: {v}" for k, v in list(node.properties.items())[:8]
                )
                section += f"Properties: {props}\n"

            if node.tags:
                section += f"Tags: {', '.join(node.tags)}\n"

            edges = await self.get_edges(eid)
            if edges:
                rels: list[str] = []
                for edge in edges[:10]:
                    direction = "→" if str(edge.source_node_id) == str(eid) else "←"
                    other_id = (
                        edge.target_node_id
                        if str(edge.source_node_id) == str(eid)
                        else edge.source_node_id
                    )
                    other = await self.get_node(other_id)
                    other_name = other.name if other else str(other_id)
                    rels.append(f"  - {direction} {edge.relation_type} {other_name}")
                section += "Relationships:\n" + "\n".join(rels) + "\n"

            sections.append(section)

        return "\n".join(sections)

    # --- Mentions ---

    async def track_mention(
        self,
        node_id: UUID | str,
        resource_id: UUID | str,
        *,
        space_id: UUID | str | None = None,
        context_snippet: str = "",
    ) -> None:
        """Record that an entity is mentioned in a vault resource.

        Args:
            node_id: The mentioned entity.
            resource_id: The document containing the mention.
            space_id: Space context (denormalized).
            context_snippet: Surrounding text for preview.
        """
        await self._storage.upsert_mention(
            str(node_id), str(resource_id),
            str(space_id) if space_id else None,
            context_snippet,
        )

        await self._fire_event(
            EventType.MENTION_TRACK,
            resource_id=str(node_id),
            resource_name=f"mention_track in {resource_id}",
            details={"resource_id": str(resource_id)},
        )

    async def get_backlinks(
        self,
        node_id: UUID | str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GraphMention]:
        """Get all resources that mention an entity.

        Args:
            node_id: The entity to find mentions for.
            limit: Max results.
            offset: Pagination offset.

        Returns:
            List of mentions ordered by recency.
        """
        limit = _cap_limit(limit)
        rows = await self._storage.get_backlinks(str(node_id), limit, offset)
        return [self._dict_to_mention(r) for r in rows]

    async def get_entities_in_resource(self, resource_id: UUID | str) -> list[GraphNode]:
        """Get all entities mentioned in a vault resource.

        Args:
            resource_id: The document to query.

        Returns:
            List of mentioned entities.
        """
        rows = await self._storage.get_entities_for_resource(str(resource_id))
        return [self._dict_to_node(r) for r in rows]

    # --- Cross-space ---

    async def add_to_space(self, node_id: UUID | str, space_id: UUID | str) -> None:
        """Make an entity visible in an additional Space.

        Args:
            node_id: The entity.
            space_id: The Space to add visibility in.
        """
        await self._storage.add_node_to_space(str(node_id), str(space_id))

    async def remove_from_space(self, node_id: UUID | str, space_id: UUID | str) -> None:
        """Remove an entity's visibility from a Space.

        Args:
            node_id: The entity.
            space_id: The Space to remove visibility from.
        """
        await self._storage.remove_node_from_space(str(node_id), str(space_id))

    # --- Merge ---

    async def merge_nodes(self, keep_id: UUID | str, merge_id: UUID | str) -> GraphNode:
        """Merge two nodes: re-point edges, mentions, spaces; delete merge_id.

        Args:
            keep_id: The node to keep.
            merge_id: The node to absorb and delete.

        Returns:
            The updated keep node.

        Raises:
            ValueError: If keep_id equals merge_id (self-merge).
            StorageError: If either node does not exist.
        """
        if str(keep_id) == str(merge_id):
            raise ValueError("Cannot merge a node with itself")
        d = await self._storage.merge_nodes(str(keep_id), str(merge_id))
        node = self._dict_to_node(d)

        await self._fire_event(
            EventType.ENTITY_MERGE,
            resource_id=str(keep_id),
            resource_name=f"entity_merge {node.name}",
            details={"keep_id": str(keep_id), "merge_id": str(merge_id)},
        )

        return node

    # --- Intelligence (delegation points for Phase 2) ---

    async def detect(
        self,
        text: str,
        *,
        space_id: UUID | str | None = None,
        fuzzy: bool = False,
    ) -> list[DetectedEntity]:
        """Detect entities in text.

        Args:
            text: Input text to scan.
            space_id: Space scope for entity index.
            fuzzy: Enable fuzzy matching via EntityResolver.

        Returns:
            List of detected entities.
        """
        if self._detector is None:
            return []
        return await self._detector.detect(
            text, fuzzy=fuzzy,
            space_id=str(space_id) if space_id else None,
        )

    async def scan(
        self,
        space_id: UUID | str,
        *,
        tenant_id: UUID | str | None = None,
    ) -> GraphScanJob:
        """Start a batch extraction scan for a space.

        Args:
            space_id: The space to scan.
            tenant_id: Owning tenant.

        Returns:
            The created scan job record.
        """
        resolved_tenant = self._resolve_tenant(tenant_id)
        job_id = uuid4()
        now = datetime.now(UTC)

        job_dict: dict[str, Any] = {
            "id": str(job_id),
            "tenant_id": str(resolved_tenant),
            "space_id": str(space_id),
            "status": "running",
            "started_at": now,
        }

        await self._storage.store_scan_job(job_dict)

        await self._fire_event(
            EventType.SCAN_START,
            resource_id=str(job_id),
            resource_name=f"scan_start space={space_id}",
            details={"space_id": str(space_id)},
        )

        return GraphScanJob(
            id=job_id,
            tenant_id=UUID(str(resolved_tenant)),
            space_id=UUID(str(space_id)),
            status="running",
            started_at=now,
        )

    async def get_scan(self, job_id: UUID | str) -> GraphScanJob | None:
        """Get a scan job by ID.

        Args:
            job_id: The scan job ID.

        Returns:
            The scan job, or None.
        """
        d = await self._storage.get_scan_job(str(job_id))
        if d is None:
            return None
        return self._dict_to_scan_job(d)

    # --- Helpers ---

    def _resolve_tenant(self, tenant_id: UUID | str | None) -> UUID | str:
        """Resolve tenant_id from vault context if not provided."""
        if tenant_id is not None:
            return tenant_id
        if hasattr(self._vault, "_locked_tenant_id") and self._vault._locked_tenant_id:
            return self._vault._locked_tenant_id
        return str(uuid4())

    @staticmethod
    def _dict_to_node(d: dict[str, Any]) -> GraphNode:
        """Convert a storage dict to a GraphNode."""
        return GraphNode(
            id=UUID(str(d["id"])),
            tenant_id=UUID(str(d["tenant_id"])),
            name=d["name"],
            slug=d["slug"],
            entity_type=d["entity_type"],
            properties=d.get("properties") or {},
            tags=d.get("tags") or [],
            primary_space_id=UUID(str(d["primary_space_id"])) if d.get("primary_space_id") else None,
            resource_id=UUID(str(d["resource_id"])) if d.get("resource_id") else None,
            manifest_resource_id=UUID(str(d["manifest_resource_id"])) if d.get("manifest_resource_id") else None,
            mention_count=d.get("mention_count", 0) or 0,
            last_mentioned_at=d.get("last_mentioned_at"),
            created_at=d.get("created_at") or datetime.now(UTC),
            updated_at=d.get("updated_at") or datetime.now(UTC),
        )

    @staticmethod
    def _dict_to_edge(d: dict[str, Any]) -> GraphEdge:
        """Convert a storage dict to a GraphEdge."""
        return GraphEdge(
            id=UUID(str(d["id"])),
            tenant_id=UUID(str(d["tenant_id"])) if d.get("tenant_id") else UUID(str(d.get("id", uuid4()))),
            source_node_id=UUID(str(d["source_node_id"])),
            target_node_id=UUID(str(d["target_node_id"])),
            relation_type=d["relation_type"],
            properties=d.get("properties") or {},
            weight=float(d.get("weight", 0.5)),
            bidirectional=bool(d.get("bidirectional", False)),
            source_resource_id=UUID(str(d["source_resource_id"])) if d.get("source_resource_id") else None,
            created_at=d.get("created_at") or datetime.now(UTC),
            updated_at=d.get("updated_at") or datetime.now(UTC),
        )

    @staticmethod
    def _dict_to_mention(d: dict[str, Any]) -> GraphMention:
        """Convert a storage dict to a GraphMention."""
        return GraphMention(
            id=UUID(str(d["id"])),
            node_id=UUID(str(d["node_id"])),
            resource_id=UUID(str(d["resource_id"])),
            space_id=UUID(str(d["space_id"])) if d.get("space_id") else None,
            context_snippet=d.get("context_snippet", ""),
            mentioned_at=d.get("mentioned_at") or datetime.now(UTC),
        )

    @staticmethod
    def _dict_to_scan_job(d: dict[str, Any]) -> GraphScanJob:
        """Convert a storage dict to a GraphScanJob."""
        return GraphScanJob(
            id=UUID(str(d["id"])),
            tenant_id=UUID(str(d["tenant_id"])),
            space_id=UUID(str(d["space_id"])),
            status=d.get("status", "running"),
            started_at=d.get("started_at") or datetime.now(UTC),
            finished_at=d.get("finished_at"),
            summary=d.get("summary"),
            error=d.get("error"),
        )

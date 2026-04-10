"""EntityResolver: Deduplicate extracted entities against the knowledge graph.

Resolves entity names to existing graph nodes using a three-stage cascade:
1. Exact name match (case-insensitive)
2. Trigram/FTS similarity (via GraphStorageBackend.search_nodes)
3. Create new node if no match found

Uses GraphEngine and GraphStorageBackend instead of direct SQL.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from qp_vault.graph.models import GraphNode
    from qp_vault.graph.service import GraphEngine

logger = logging.getLogger(__name__)


class EntityResolver:
    """Resolve entity names to existing graph nodes or create new ones.

    Args:
        graph_engine: GraphEngine for node creation and listing.
        similarity_threshold: Minimum score to consider a search match (0.0-1.0).
    """

    def __init__(
        self,
        graph_engine: GraphEngine,
        *,
        similarity_threshold: float = 0.6,
    ) -> None:
        self._graph = graph_engine
        self._threshold = similarity_threshold

    async def resolve(
        self,
        name: str,
        entity_type: str,
        *,
        space_id: UUID | str | None = None,
    ) -> GraphNode | None:
        """Find an existing graph node matching this entity.

        Args:
            name: The entity name from extraction.
            entity_type: The entity type (person, company, etc.).
            space_id: Optional space filter for scoped resolution.

        Returns:
            Matching GraphNode, or None if no match found.
        """
        if not name or not name.strip():
            return None

        clean_name = name.strip()

        node = await self._exact_match(clean_name, entity_type, space_id)
        if node:
            return node

        node = await self._search_match(clean_name, entity_type, space_id)
        if node:
            return node

        return None

    async def resolve_or_create(
        self,
        name: str,
        entity_type: str,
        *,
        properties: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        space_id: UUID | str | None = None,
    ) -> GraphNode:
        """Resolve an entity to an existing node, or create a new one.

        Args:
            name: The entity name.
            entity_type: The entity type.
            properties: Optional properties for new nodes.
            tags: Optional tags for new nodes.
            space_id: Space for scoped resolution and creation.

        Returns:
            Existing or newly created GraphNode.
        """
        existing = await self.resolve(name, entity_type, space_id=space_id)
        if existing:
            return existing

        node = await self._graph.create_node(
            name=name.strip(),
            entity_type=entity_type,
            properties=properties,
            tags=tags,
            primary_space_id=space_id,
        )
        logger.info("Created new entity '%s' (%s): %s", name, entity_type, node.id)
        return node

    async def resolve_by_name(
        self,
        name: str,
        *,
        space_id: UUID | str | None = None,
    ) -> GraphNode | None:
        """Find an existing graph node by name across ALL entity types.

        Type-agnostic resolution for wikilink resolution and similar use cases.

        Args:
            name: The entity name to search for.
            space_id: Optional space filter.

        Returns:
            Matching GraphNode, or None.
        """
        if not name or not name.strip():
            return None

        clean_name = name.strip()

        nodes, _ = await self._graph.list_nodes(space_id=space_id, limit=10000)
        for node in nodes:
            if node.name.lower() == clean_name.lower():
                return node

        results = await self._graph.search_nodes(clean_name, space_id=space_id, limit=1)
        if results:
            return results[0]

        return None

    async def _exact_match(
        self,
        name: str,
        entity_type: str,
        space_id: UUID | str | None,
    ) -> GraphNode | None:
        """Case-insensitive exact match on name + entity_type."""
        nodes, _ = await self._graph.list_nodes(
            entity_type=entity_type, space_id=space_id, limit=10000,
        )
        for node in nodes:
            if node.name.lower() == name.lower():
                return node
        return None

    async def _search_match(
        self,
        name: str,
        entity_type: str,
        space_id: UUID | str | None,
    ) -> GraphNode | None:
        """Search-based similarity match filtered by entity_type."""
        results = await self._graph.search_nodes(
            name, space_id=space_id, limit=5,
        )
        for node in results:
            if node.entity_type == entity_type:
                return node
        return None

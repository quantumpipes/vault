"""EntityDetector: Lightweight entity detection in user messages.

Scans text for known entity names from the knowledge graph using
in-memory name matching. No LLM calls. Optional fuzzy matching via
EntityResolver.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qp_vault.graph.models import DetectedEntity

if TYPE_CHECKING:
    from qp_vault.graph.models import GraphNode
    from qp_vault.graph.resolution import EntityResolver
    from qp_vault.graph.service import GraphEngine

logger = logging.getLogger(__name__)

_MAX_TEXT_LENGTH = 50_000
_MAX_FUZZY_CANDIDATES = 100
_MAX_INDEX_SIZE = 10_000


class EntityDetector:
    """Detects known entities in text using name matching.

    Args:
        graph_engine: The GraphEngine for loading entity names.
        entity_resolver: Optional EntityResolver for fuzzy matching.
    """

    def __init__(
        self,
        graph_engine: GraphEngine,
        entity_resolver: EntityResolver | None = None,
    ) -> None:
        self._graph = graph_engine
        self._resolver = entity_resolver
        self._name_index: dict[str, GraphNode] = {}
        self._loaded = False

    async def load_index(self, space_id: UUID | str | None = None) -> int:
        """Load entity names into the in-memory index.

        Args:
            space_id: Optional space filter. If None, loads all entities.

        Returns:
            Number of entities loaded.
        """
        nodes, _ = await self._graph.list_nodes(
            space_id=space_id, limit=_MAX_INDEX_SIZE,
        )
        self._name_index = {node.name.lower(): node for node in nodes}
        self._loaded = True
        logger.info("Entity index loaded: %d entities", len(self._name_index))
        return len(self._name_index)

    async def detect(
        self,
        text: str,
        *,
        fuzzy: bool = False,
        space_id: UUID | str | None = None,
    ) -> list[DetectedEntity]:
        """Detect entities mentioned in text.

        Args:
            text: The input text to scan.
            fuzzy: Whether to attempt fuzzy matching for unresolved names.
            space_id: Optional space filter for fuzzy resolution.

        Returns:
            List of DetectedEntity objects, sorted by position.
        """
        if not text or not text.strip():
            return []

        text = text[:_MAX_TEXT_LENGTH]

        if not self._loaded:
            await self.load_index(space_id)

        results: list[DetectedEntity] = []
        seen_ids: set[UUID] = set()

        sorted_names = sorted(self._name_index.keys(), key=len, reverse=True)

        for name_lower in sorted_names:
            node = self._name_index[name_lower]
            if node.id in seen_ids:
                continue

            pattern = re.compile(r"\b" + re.escape(name_lower) + r"\b", re.IGNORECASE)
            for match in pattern.finditer(text):
                if node.id not in seen_ids:
                    results.append(DetectedEntity(
                        name=node.name,
                        entity_type=node.entity_type,
                        node_id=node.id,
                        confidence=1.0,
                        start=match.start(),
                        end=match.end(),
                    ))
                    seen_ids.add(node.id)

        if fuzzy and self._resolver:
            candidates = re.findall(
                r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text,
            )[:_MAX_FUZZY_CANDIDATES]
            for candidate in candidates:
                if candidate.lower() in self._name_index:
                    continue

                node = await self._resolver.resolve_by_name(
                    candidate, space_id=space_id,
                )
                if node and node.id not in seen_ids:
                    idx = text.find(candidate)
                    if idx >= 0:
                        results.append(DetectedEntity(
                            name=node.name,
                            entity_type=node.entity_type,
                            node_id=node.id,
                            confidence=0.7,
                            start=idx,
                            end=idx + len(candidate),
                        ))
                        seen_ids.add(node.id)

        results.sort(key=lambda d: d.start or 0)
        return results

    async def detect_ids(
        self,
        text: str,
        *,
        fuzzy: bool = False,
        space_id: UUID | str | None = None,
    ) -> list[UUID]:
        """Convenience method returning just entity UUIDs.

        Args:
            text: The input text to scan.
            fuzzy: Whether to attempt fuzzy matching.
            space_id: Optional space filter.

        Returns:
            List of matched entity UUIDs.
        """
        detections = await self.detect(text, fuzzy=fuzzy, space_id=space_id)
        return [d.node_id for d in detections if d.node_id]

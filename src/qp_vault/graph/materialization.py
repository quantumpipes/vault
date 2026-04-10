"""EntityMaterializer: Generate profile.md and manifest.json for graph entities.

Converts GraphNode data into human-readable (profile.md) and machine-readable
(manifest.json) vault resources. Domain-agnostic: works for any entity type
the system discovers.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from qp_vault.graph.models import GraphNode
    from qp_vault.graph.service import GraphEngine

logger = logging.getLogger(__name__)


class EntityMaterializer:
    """Generates and refreshes entity profile resources.

    Args:
        graph_engine: GraphEngine instance for entity and edge lookups.
        vault: AsyncVault instance for resource creation.
    """

    def __init__(self, graph_engine: GraphEngine, vault: Any) -> None:
        self._graph = graph_engine
        self._vault = vault

    async def materialize(self, node_id: UUID | str) -> dict[str, Any]:
        """Generate profile.md and manifest.json for an entity.

        Args:
            node_id: UUID of the GraphNode to materialize.

        Returns:
            Dict with 'profile_resource_id' and 'manifest_resource_id'.

        Raises:
            ValueError: If the node does not exist.
        """
        node = await self._graph.get_node(node_id)
        if not node:
            raise ValueError(f"Node {node_id} not found")

        profile_md = await self._build_profile(node)
        manifest_json = await self._build_manifest(node)

        profile_rid = await self._upsert_resource(
            node=node,
            filename=f"{node.slug}/profile.md",
            content=profile_md,
        )

        manifest_rid = await self._upsert_resource(
            node=node,
            filename=f"{node.slug}/manifest.json",
            content=manifest_json,
        )

        updates: dict[str, Any] = {}
        if profile_rid and profile_rid != node.resource_id:
            updates["resource_id"] = profile_rid
        if manifest_rid and manifest_rid != node.manifest_resource_id:
            updates["manifest_resource_id"] = manifest_rid
        if updates:
            await self._graph.update_node(node_id, **updates)

        return {
            "profile_resource_id": profile_rid,
            "manifest_resource_id": manifest_rid,
        }

    async def _build_profile(self, node: GraphNode) -> str:
        """Build a rich markdown profile for the entity."""
        lines: list[str] = []

        lines.append(f"# {node.name}")
        lines.append("")
        lines.append(f"**Type:** {node.entity_type}")
        lines.append(f"**Last updated:** {datetime.now(UTC).strftime('%Y-%m-%d')}")
        lines.append("")

        if node.properties:
            lines.append("## Properties")
            lines.append("")
            lines.append("| Property | Value |")
            lines.append("|----------|-------|")
            for key, value in node.properties.items():
                lines.append(f"| {key} | {value} |")
            lines.append("")

        if node.tags:
            lines.append("## Tags")
            lines.append("")
            lines.append(", ".join(f"`{tag}`" for tag in node.tags))
            lines.append("")

        edges = await self._graph.get_edges(node.id)
        if edges:
            lines.append("## Relationships")
            lines.append("")
            for edge in edges:
                is_outgoing = str(edge.source_node_id) == str(node.id)
                other_id = edge.target_node_id if is_outgoing else edge.source_node_id
                other = await self._graph.get_node(other_id)
                if not other:
                    continue
                direction = "to" if is_outgoing else "from"
                lines.append(f"- {edge.relation_type} ({direction}) [[{other.name}]]")
            lines.append("")

        mentions = await self._graph.get_backlinks(node.id, limit=20)
        if mentions:
            lines.append("## Mentions")
            lines.append("")
            for mention in mentions:
                if mention.context_snippet:
                    lines.append(f'> "{mention.context_snippet}"')
                    lines.append("")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append(f"*Entity ID: `{node.slug}`*")
        lines.append(f"*Mention count: {node.mention_count}*")
        if node.last_mentioned_at:
            lines.append(f"*Last mentioned: {node.last_mentioned_at}*")

        return "\n".join(lines)

    async def _build_manifest(self, node: GraphNode) -> str:
        """Build a structured JSON manifest for the entity."""
        edges = await self._graph.get_edges(node.id)
        relationships: list[dict[str, Any]] = []

        for edge in edges:
            is_outgoing = str(edge.source_node_id) == str(node.id)
            other_id = edge.target_node_id if is_outgoing else edge.source_node_id
            other = await self._graph.get_node(other_id)
            relationships.append({
                "relation_type": edge.relation_type,
                "direction": "outgoing" if is_outgoing else "incoming",
                "target_id": str(other_id),
                "target_name": other.name if other else None,
                "target_type": other.entity_type if other else None,
                "weight": edge.weight,
                "bidirectional": edge.bidirectional,
            })

        manifest = {
            "schema_version": "1.0",
            "entity_id": str(node.id),
            "entity_type": node.entity_type,
            "name": node.name,
            "slug": node.slug,
            "properties": node.properties or {},
            "tags": node.tags or [],
            "relationships": relationships,
            "primary_space_id": str(node.primary_space_id) if node.primary_space_id else None,
            "mention_count": node.mention_count,
            "last_mentioned_at": node.last_mentioned_at,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
            "materialized_at": datetime.now(UTC).isoformat(),
        }

        return json.dumps(manifest, indent=2, default=str)

    async def _upsert_resource(
        self,
        *,
        node: GraphNode,
        filename: str,
        content: str,
    ) -> UUID | None:
        """Create or update a vault resource for the entity via upsert."""
        try:
            resource = await self._vault.upsert(
                content,
                name=filename,
                tenant_id=str(node.tenant_id) if node.tenant_id else None,
            )
            return UUID(str(resource.id))
        except Exception as exc:
            logger.warning(
                "Failed to upsert resource %s for entity %s: %s",
                filename, node.name, exc,
            )
            return None

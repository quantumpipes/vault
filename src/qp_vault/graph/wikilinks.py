"""WikilinkResolver: Parse and resolve ``[[Entity Name]]`` syntax in markdown.

Supports two forms:
- ``[[Entity Name]]`` -- display the entity name as-is
- ``[[Entity Name|Display Text]]`` -- show Display Text, link to Entity Name

Skips wikilinks inside code fences and inline code to avoid false positives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from qp_vault.graph.resolution import EntityResolver

_WIKILINK_PATTERN = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")
_CODE_FENCE_PATTERN = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")


@dataclass
class WikilinkRef:
    """A parsed wikilink reference from source text."""

    name: str
    display_text: str | None
    start: int
    end: int


@dataclass
class ResolvedWikilink:
    """A wikilink resolved to a graph node (or unresolved)."""

    name: str
    display_text: str | None
    node_id: UUID | None
    entity_type: str | None
    resolved: bool


def parse_wikilinks(text: str) -> list[WikilinkRef]:
    """Parse ``[[Entity Name]]`` and ``[[Entity Name|Display]]`` from text.

    Skips wikilinks inside code fences and inline code blocks.

    Args:
        text: The markdown text to parse.

    Returns:
        List of WikilinkRef with positions.
    """
    if not text:
        return []

    excluded: set[int] = set()
    for pattern in (_CODE_FENCE_PATTERN, _INLINE_CODE_PATTERN):
        for match in pattern.finditer(text):
            for i in range(match.start(), match.end()):
                excluded.add(i)

    refs: list[WikilinkRef] = []
    seen_names: set[str] = set()

    for match in _WIKILINK_PATTERN.finditer(text):
        if match.start() in excluded:
            continue

        name = match.group(1).strip()
        display = match.group(2)
        if display:
            display = display.strip()

        if not name:
            continue

        name_lower = name.lower()
        if name_lower in seen_names:
            continue
        seen_names.add(name_lower)

        refs.append(WikilinkRef(
            name=name,
            display_text=display,
            start=match.start(),
            end=match.end(),
        ))

    return refs


async def resolve_wikilinks(
    refs: list[WikilinkRef],
    resolver: EntityResolver,
    *,
    space_id: UUID | str | None = None,
) -> list[ResolvedWikilink]:
    """Resolve parsed wikilink references to graph nodes.

    Args:
        refs: Parsed wikilink references.
        resolver: EntityResolver for matching.
        space_id: Optional space filter.

    Returns:
        List of ResolvedWikilink with resolution status.
    """
    results: list[ResolvedWikilink] = []

    for ref in refs:
        node = await resolver.resolve_by_name(ref.name, space_id=space_id)

        if node:
            results.append(ResolvedWikilink(
                name=ref.name,
                display_text=ref.display_text,
                node_id=node.id,
                entity_type=node.entity_type,
                resolved=True,
            ))
        else:
            results.append(ResolvedWikilink(
                name=ref.name,
                display_text=ref.display_text,
                node_id=None,
                entity_type=None,
                resolved=False,
            ))

    return results

"""Protocol interfaces for qp-vault extensibility.

All pluggable components are defined as Protocols (structural subtyping).
Implement any Protocol to extend qp-vault without inheriting from base classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from qp_vault.models import Chunk, Resource, SearchResult, VaultEvent


@dataclass
class ResourceFilter:
    """Filtering criteria for resource listing."""

    tenant_id: str | None = None
    trust_tier: str | None = None
    data_classification: str | None = None
    resource_type: str | None = None
    status: str | None = None
    lifecycle: str | None = None
    layer: str | None = None
    collection_id: str | None = None
    tags: list[str] | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class ResourceUpdate:
    """Fields that can be updated on a resource."""

    name: str | None = None
    trust_tier: str | None = None
    data_classification: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    lifecycle: str | None = None
    adversarial_status: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes: str | None = None
    superseded_by: str | None = None


@dataclass
class SearchQuery:
    """Search query parameters."""

    query_embedding: list[float] | None = None
    query_text: str = ""
    top_k: int = 10
    threshold: float = 0.0
    vector_weight: float = 0.7
    text_weight: float = 0.3
    filters: ResourceFilter | None = None
    as_of: str | None = None


@dataclass
class ParseResult:
    """Result of parsing a file."""

    text: str = ""
    metadata: dict[str, Any] | None = None
    pages: int = 0


@dataclass
class PolicyResult:
    """Result of a policy evaluation."""

    allowed: bool = True
    reason: str = ""


@runtime_checkable
class StorageBackend(Protocol):
    """Persistence layer for vault resources and chunks."""

    async def initialize(self) -> None: ...
    async def store_resource(self, resource: Resource) -> str: ...
    async def get_resource(self, resource_id: str) -> Resource | None: ...
    async def list_resources(self, filters: ResourceFilter) -> list[Resource]: ...
    async def update_resource(self, resource_id: str, updates: ResourceUpdate) -> Resource: ...
    async def delete_resource(self, resource_id: str, *, hard: bool = False) -> None: ...
    async def store_chunks(self, resource_id: str, chunks: list[Chunk]) -> None: ...
    async def search(self, query: SearchQuery) -> list[SearchResult]: ...
    async def get_all_hashes(self) -> list[tuple[str, str]]: ...
    async def get_chunks_for_resource(self, resource_id: str) -> list[Chunk]: ...
    async def restore_resource(self, resource_id: str) -> Resource: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Generates vector embeddings from text."""

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class AuditProvider(Protocol):
    """Records audit events for vault operations."""

    async def record(self, event: VaultEvent) -> str: ...


@runtime_checkable
class ParserProvider(Protocol):
    """Converts files to text for indexing."""

    @property
    def supported_extensions(self) -> set[str]: ...

    async def parse(self, path: Path) -> ParseResult: ...


@runtime_checkable
class PolicyProvider(Protocol):
    """Evaluates governance policies on vault operations."""

    async def evaluate(
        self, resource: Resource, action: str, context: dict[str, Any]
    ) -> PolicyResult: ...

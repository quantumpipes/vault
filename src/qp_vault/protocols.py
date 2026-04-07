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

    async def initialize(self) -> None:
        """Create tables and indexes."""
        ...

    async def store_resource(self, resource: Resource) -> str:
        """Persist a resource, returning its ID."""
        ...

    async def get_resource(self, resource_id: str) -> Resource | None:
        """Retrieve a resource by ID, or None if not found."""
        ...

    async def list_resources(self, filters: ResourceFilter) -> list[Resource]:
        """List resources matching filter criteria."""
        ...

    async def update_resource(self, resource_id: str, updates: ResourceUpdate) -> Resource:
        """Apply partial updates to a resource."""
        ...

    async def delete_resource(self, resource_id: str, *, hard: bool = False) -> None:
        """Soft-delete (default) or permanently remove a resource."""
        ...

    async def store_chunks(self, resource_id: str, chunks: list[Chunk]) -> None:
        """Store content chunks for a resource."""
        ...

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Execute a hybrid search query."""
        ...

    async def get_all_hashes(self) -> list[tuple[str, str]]:
        """Return (resource_id, content_hash) pairs for Merkle verification."""
        ...

    async def get_chunks_for_resource(self, resource_id: str) -> list[Chunk]:
        """Retrieve all chunks belonging to a resource."""
        ...

    async def restore_resource(self, resource_id: str) -> Resource:
        """Restore a soft-deleted resource to indexed status."""
        ...

    async def get_provenance(self, resource_id: str) -> list[dict[str, Any]]:
        """Get provenance records for a resource."""
        ...

    async def store_provenance(
        self,
        provenance_id: str,
        resource_id: str,
        uploader_id: str | None,
        upload_method: str | None,
        source_description: str,
        original_hash: str,
        signature: str | None,
        verified: bool,
        created_at: str,
    ) -> None:
        """Store a content provenance attestation."""
        ...

    async def store_collection(
        self, collection_id: str, name: str, description: str, created_at: str
    ) -> None:
        """Create a new collection."""
        ...

    async def list_collections(self) -> list[dict[str, Any]]:
        """List all collections."""
        ...

    async def count_resources(self, tenant_id: str) -> int:
        """Count non-deleted resources for a tenant (atomic)."""
        ...


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


@dataclass
class ScreeningResult:
    """Result of LLM-based content screening."""

    risk_score: float = 0.0  # 0.0 (safe) to 1.0 (dangerous)
    reasoning: str = ""
    flags: list[str] | None = None  # e.g. ["prompt_injection", "encoded_payload"]


@runtime_checkable
class LLMScreener(Protocol):
    """LLM-based content screening for the Membrane ADAPTIVE_SCAN stage.

    Implementations can use any LLM backend: Anthropic (Claude), OpenAI (GPT),
    Ollama (local/air-gap), or custom. The screener evaluates content for
    adversarial intent that regex patterns cannot catch.
    """

    async def screen(self, content: str) -> ScreeningResult:
        """Evaluate content for adversarial intent.

        Args:
            content: Text content to screen (may be truncated by caller).

        Returns:
            ScreeningResult with risk_score, reasoning, and optional flags.
        """
        ...

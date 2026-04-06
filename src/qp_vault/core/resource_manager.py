"""Resource management: CRUD operations with chunking, hashing, and embedding.

Orchestrates the full ingest pipeline:
  file/text -> parse -> chunk -> hash (CID) -> embed -> store -> audit
"""

from __future__ import annotations

import mimetypes
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from qp_vault.core.chunker import ChunkerConfig, chunk_text
from qp_vault.core.hasher import compute_cid, compute_resource_hash
from qp_vault.enums import (
    DataClassification,
    EventType,
    Lifecycle,
    MemoryLayer,
    ResourceStatus,
    ResourceType,
    TrustTier,
)
from qp_vault.exceptions import VaultError
from qp_vault.models import Chunk, Resource, VaultEvent
from qp_vault.protocols import (
    AuditProvider,
    EmbeddingProvider,
    ResourceFilter,
    ResourceUpdate,
    StorageBackend,
)


def _detect_resource_type(name: str) -> ResourceType:
    """Detect resource type from filename extension."""
    ext = Path(name).suffix.lower()
    mapping = {
        ".pdf": ResourceType.DOCUMENT,
        ".docx": ResourceType.DOCUMENT,
        ".doc": ResourceType.DOCUMENT,
        ".pptx": ResourceType.DOCUMENT,
        ".xlsx": ResourceType.SPREADSHEET,
        ".csv": ResourceType.SPREADSHEET,
        ".png": ResourceType.IMAGE,
        ".jpg": ResourceType.IMAGE,
        ".jpeg": ResourceType.IMAGE,
        ".gif": ResourceType.IMAGE,
        ".webp": ResourceType.IMAGE,
        ".mp3": ResourceType.AUDIO,
        ".wav": ResourceType.AUDIO,
        ".mp4": ResourceType.VIDEO,
        ".webm": ResourceType.VIDEO,
        ".py": ResourceType.CODE,
        ".js": ResourceType.CODE,
        ".ts": ResourceType.CODE,
        ".rs": ResourceType.CODE,
        ".go": ResourceType.CODE,
        ".java": ResourceType.CODE,
        ".md": ResourceType.NOTE,
        ".txt": ResourceType.NOTE,
        ".rst": ResourceType.NOTE,
        ".vtt": ResourceType.TRANSCRIPT,
        ".srt": ResourceType.TRANSCRIPT,
    }
    return mapping.get(ext, ResourceType.DOCUMENT)


def _detect_mime_type(name: str) -> str | None:
    """Detect MIME type from filename."""
    mime, _ = mimetypes.guess_type(name)
    return mime


class ResourceManager:
    """Manages resource lifecycle: create, read, update, delete."""

    def __init__(
        self,
        storage: StorageBackend,
        embedder: EmbeddingProvider | None = None,
        auditor: AuditProvider | None = None,
        chunker_config: ChunkerConfig | None = None,
    ) -> None:
        self._storage = storage
        self._embedder = embedder
        self._auditor = auditor
        self._chunker_config = chunker_config or ChunkerConfig()

    async def add(
        self,
        text: str,
        *,
        name: str = "untitled",
        trust: TrustTier | str = TrustTier.WORKING,
        classification: DataClassification | str = DataClassification.INTERNAL,
        layer: MemoryLayer | str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        lifecycle: Lifecycle | str = Lifecycle.ACTIVE,
        valid_from: date | None = None,
        valid_until: date | None = None,
    ) -> Resource:
        """Add a resource from text content.

        Pipeline: text -> chunk -> CID -> embed -> store -> audit
        """
        resource_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)

        # Normalize enums
        trust_tier = TrustTier(trust) if isinstance(trust, str) else trust
        data_class = DataClassification(classification) if isinstance(classification, str) else classification
        lc = Lifecycle(lifecycle) if isinstance(lifecycle, str) else lifecycle
        mem_layer = MemoryLayer(layer) if isinstance(layer, str) else layer

        # Chunk the text
        chunk_results = chunk_text(text, self._chunker_config)

        # Compute CIDs for each chunk
        chunks: list[Chunk] = []
        for cr in chunk_results:
            chunk_id = str(uuid.uuid4())
            cid = compute_cid(cr.content)
            chunks.append(
                Chunk(
                    id=chunk_id,
                    resource_id=resource_id,
                    content=cr.content,
                    cid=cid,
                    chunk_index=cr.chunk_index,
                    page_number=cr.page_number,
                    section_title=cr.section_title,
                    token_count=cr.token_count,
                )
            )

        # Generate embeddings if provider available
        if self._embedder and chunks:
            texts_to_embed = [c.content for c in chunks]
            embeddings = await self._embedder.embed(texts_to_embed)
            for chunk, emb in zip(chunks, embeddings, strict=False):
                chunk.embedding = emb

        # Compute resource-level hash from chunk CIDs
        chunk_cids = [c.cid for c in chunks]
        content_hash = compute_resource_hash(chunk_cids) if chunk_cids else compute_cid(text).split("/")[-1]
        resource_cid = f"vault://sha3-256/{content_hash}"

        # Create resource
        resource = Resource(
            id=resource_id,
            name=name,
            content_hash=content_hash,
            cid=resource_cid,
            trust_tier=trust_tier,
            data_classification=data_class,
            resource_type=_detect_resource_type(name),
            status=ResourceStatus.INDEXED if chunks else ResourceStatus.PENDING,
            lifecycle=lc,
            valid_from=valid_from,
            valid_until=valid_until,
            collection_id=collection,
            layer=mem_layer,
            tags=tags or [],
            metadata=metadata or {},
            mime_type=_detect_mime_type(name),
            size_bytes=len(text.encode("utf-8")),
            chunk_count=len(chunks),
            created_at=now,
            updated_at=now,
            indexed_at=now if chunks else None,
        )

        # Store
        await self._storage.store_resource(resource)
        if chunks:
            await self._storage.store_chunks(resource_id, chunks)

        # Audit
        if self._auditor:
            event = VaultEvent(
                event_type=EventType.CREATE,
                resource_id=resource_id,
                resource_name=name,
                resource_hash=content_hash,
                timestamp=now,
                details={"trust_tier": trust_tier.value, "chunk_count": len(chunks)},
            )
            await self._auditor.record(event)

        return resource

    async def get(self, resource_id: str) -> Resource:
        """Get a resource by ID."""
        resource = await self._storage.get_resource(resource_id)
        if resource is None:
            raise VaultError(f"Resource {resource_id} not found")
        return resource

    async def list(
        self,
        *,
        trust: TrustTier | str | None = None,
        classification: DataClassification | str | None = None,
        layer: MemoryLayer | str | None = None,
        collection: str | None = None,
        lifecycle: Lifecycle | str | None = None,
        status: ResourceStatus | str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Resource]:
        """List resources with filters."""
        filters = ResourceFilter(
            trust_tier=trust.value if hasattr(trust, "value") else trust,
            data_classification=classification.value if hasattr(classification, "value") else classification,
            layer=layer.value if hasattr(layer, "value") else layer,
            collection_id=collection,
            lifecycle=lifecycle.value if hasattr(lifecycle, "value") else lifecycle,
            status=status.value if hasattr(status, "value") else status,
            tags=tags,
            limit=limit,
            offset=offset,
        )
        return await self._storage.list_resources(filters)

    async def update(
        self,
        resource_id: str,
        *,
        name: str | None = None,
        trust: TrustTier | str | None = None,
        classification: DataClassification | str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Resource:
        """Update resource metadata."""
        updates = ResourceUpdate(
            name=name,
            trust_tier=trust.value if hasattr(trust, "value") else trust,
            data_classification=classification.value if hasattr(classification, "value") else classification,
            tags=tags,
            metadata=metadata,
        )

        resource = await self._storage.update_resource(resource_id, updates)

        # Audit trust changes
        if trust and self._auditor:
            event = VaultEvent(
                event_type=EventType.TRUST_CHANGE,
                resource_id=resource_id,
                resource_name=resource.name,
                resource_hash=resource.content_hash,
                details={"new_trust_tier": trust.value if hasattr(trust, "value") else trust},
            )
            await self._auditor.record(event)

        return resource

    async def delete(self, resource_id: str, *, hard: bool = False) -> None:
        """Delete a resource (soft by default)."""
        resource = await self.get(resource_id)
        await self._storage.delete_resource(resource_id, hard=hard)

        if self._auditor:
            event = VaultEvent(
                event_type=EventType.DELETE,
                resource_id=resource_id,
                resource_name=resource.name,
                resource_hash=resource.content_hash,
                details={"hard": hard},
            )
            await self._auditor.record(event)

    async def restore(self, resource_id: str) -> Resource:
        """Restore a soft-deleted resource back to indexed status."""
        resource = await self.get(resource_id)
        restored = await self._storage.restore_resource(resource_id)

        if self._auditor:
            event = VaultEvent(
                event_type=EventType.RESTORE,
                resource_id=resource_id,
                resource_name=resource.name,
                resource_hash=resource.content_hash,
            )
            await self._auditor.record(event)

        return restored

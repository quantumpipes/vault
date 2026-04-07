"""PostgreSQL storage backend for qp-vault.

Production-grade backend with pgvector (HNSW) for vector similarity
and pg_trgm (GIN) for full-text trigram matching.

Requires: pip install qp-vault[postgres]
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from qp_vault.enums import TrustTier
from qp_vault.exceptions import StorageError
from qp_vault.models import Chunk, Resource, SearchResult

if TYPE_CHECKING:
    from qp_vault.protocols import ResourceFilter, ResourceUpdate, SearchQuery

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

_SCHEMA = """
CREATE SCHEMA IF NOT EXISTS qp_vault;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS qp_vault.resources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    cid TEXT NOT NULL,
    merkle_root TEXT,
    trust_tier TEXT NOT NULL DEFAULT 'working',
    data_classification TEXT NOT NULL DEFAULT 'internal',
    resource_type TEXT NOT NULL DEFAULT 'document',
    status TEXT NOT NULL DEFAULT 'pending',
    lifecycle TEXT NOT NULL DEFAULT 'active',
    adversarial_status TEXT NOT NULL DEFAULT 'unverified',
    valid_from DATE,
    valid_until DATE,
    supersedes TEXT,
    superseded_by TEXT,
    tenant_id TEXT,
    collection_id TEXT,
    layer TEXT,
    tags JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    mime_type TEXT,
    size_bytes BIGINT DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    indexed_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS qp_vault.chunks (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES qp_vault.resources(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    cid TEXT NOT NULL,
    embedding vector({dimensions}),
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    section_title TEXT,
    token_count INTEGER DEFAULT 0,
    speaker TEXT
);

CREATE TABLE IF NOT EXISTS qp_vault.collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_public BOOLEAN DEFAULT FALSE,
    resource_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qp_vault.vault_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resources_status ON qp_vault.resources(status);
CREATE INDEX IF NOT EXISTS idx_resources_trust ON qp_vault.resources(trust_tier);
CREATE INDEX IF NOT EXISTS idx_resources_lifecycle ON qp_vault.resources(lifecycle);
CREATE INDEX IF NOT EXISTS idx_resources_layer ON qp_vault.resources(layer);
CREATE INDEX IF NOT EXISTS idx_resources_hash ON qp_vault.resources(content_hash);
CREATE INDEX IF NOT EXISTS idx_resources_valid ON qp_vault.resources(valid_from, valid_until);
CREATE INDEX IF NOT EXISTS idx_chunks_resource ON qp_vault.chunks(resource_id);
CREATE INDEX IF NOT EXISTS idx_chunks_cid ON qp_vault.chunks(cid);
CREATE INDEX IF NOT EXISTS idx_resources_tenant ON qp_vault.resources(tenant_id);
CREATE INDEX IF NOT EXISTS idx_resources_adversarial ON qp_vault.resources(adversarial_status);
CREATE INDEX IF NOT EXISTS idx_resources_classification ON qp_vault.resources(data_classification);
CREATE INDEX IF NOT EXISTS idx_resources_type ON qp_vault.resources(resource_type);
CREATE INDEX IF NOT EXISTS idx_resources_tags ON qp_vault.resources USING gin (tags);

CREATE TABLE IF NOT EXISTS qp_vault.provenance (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES qp_vault.resources(id) ON DELETE CASCADE,
    uploader_id TEXT,
    upload_method TEXT,
    source_description TEXT DEFAULT '',
    original_hash TEXT NOT NULL,
    provenance_signature TEXT,
    signature_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provenance_resource ON qp_vault.provenance(resource_id);
"""

_HNSW_INDEX = """
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON qp_vault.chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""

_TRGM_INDEX = """
CREATE INDEX IF NOT EXISTS idx_chunks_content_trgm ON qp_vault.chunks
    USING gin (content gin_trgm_ops);
"""

_HYBRID_SEARCH_SQL = """
WITH scored AS (
    SELECT
        c.id AS chunk_id,
        c.resource_id,
        c.content,
        c.cid AS chunk_cid,
        c.page_number,
        c.section_title,
        r.name AS resource_name,
        r.trust_tier,
        r.lifecycle,
        CASE WHEN $1::vector IS NOT NULL AND c.embedding IS NOT NULL
             THEN 1 - (c.embedding <=> $1::vector)
             ELSE 0
        END AS vector_sim,
        CASE WHEN $2 != ''
             THEN similarity(c.content, $2)
             ELSE 0
        END AS text_rank
    FROM qp_vault.chunks c
    JOIN qp_vault.resources r ON c.resource_id = r.id
    WHERE r.status = 'indexed'
      {extra_where}
)
SELECT *,
       ($3 * vector_sim + $4 * text_rank) AS raw_score
FROM scored
WHERE (vector_sim > 0 OR text_rank > 0)
  AND ($3 * vector_sim + $4 * text_rank) >= $5
ORDER BY raw_score DESC
LIMIT $6
"""


def _enum_val(v: Any) -> Any:
    """Extract .value from enum if applicable."""
    return v.value if hasattr(v, "value") else v


def _resource_from_record(record: dict[str, Any]) -> Resource:
    """Convert an asyncpg Record to a Resource."""
    data = dict(record)
    if isinstance(data.get("tags"), str):
        data["tags"] = json.loads(data["tags"])
    if isinstance(data.get("metadata"), str):
        data["metadata"] = json.loads(data["metadata"])
    return Resource(**data)


class PostgresBackend:
    """PostgreSQL storage backend with pgvector + pg_trgm hybrid search.

    Uses asyncpg for async connection pooling. Requires:
    - PostgreSQL 16+ with pgvector and pg_trgm extensions
    - pip install qp-vault[postgres]
    """

    def __init__(
        self, dsn: str, *, embedding_dimensions: int = 768, command_timeout: float = 30.0
    ) -> None:
        if not HAS_ASYNCPG:
            raise ImportError(
                "asyncpg is required for PostgresBackend. "
                "Install with: pip install qp-vault[postgres]"
            )
        self._dsn = dsn
        self._dimensions = embedding_dimensions
        self._command_timeout = command_timeout
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        """Get or create connection pool."""
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=2,
                max_size=10,
                command_timeout=self._command_timeout,
            )
        return self._pool

    async def initialize(self) -> None:
        """Create schema, tables, and indexes."""
        pool = await self._get_pool()
        schema = _SCHEMA.format(dimensions=self._dimensions)
        async with pool.acquire() as conn:
            await conn.execute(schema)
            with contextlib.suppress(Exception):
                await conn.execute(_HNSW_INDEX)
            with contextlib.suppress(Exception):
                await conn.execute(_TRGM_INDEX)

    async def store_resource(self, resource: Resource) -> str:
        """Store a resource."""
        pool = await self._get_pool()
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO qp_vault.resources (
                        id, name, content_hash, cid, merkle_root,
                        trust_tier, data_classification, resource_type,
                        status, lifecycle, adversarial_status, valid_from, valid_until,
                        supersedes, superseded_by, tenant_id, collection_id, layer,
                        tags, metadata, mime_type, size_bytes, chunk_count,
                        created_at, updated_at, indexed_at, deleted_at
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8,
                        $9, $10, $11, $12, $13,
                        $14, $15, $16, $17, $18,
                        $19, $20, $21, $22, $23,
                        $24, $25, $26, $27
                    )""",
                    resource.id,
                    resource.name,
                    resource.content_hash,
                    resource.cid,
                    resource.merkle_root,
                    _enum_val(resource.trust_tier),
                    _enum_val(resource.data_classification),
                    _enum_val(resource.resource_type),
                    _enum_val(resource.status),
                    _enum_val(resource.lifecycle),
                    _enum_val(getattr(resource, "adversarial_status", "unverified")),
                    resource.valid_from,
                    resource.valid_until,
                    resource.supersedes,
                    resource.superseded_by,
                    resource.tenant_id,
                    resource.collection_id,
                    _enum_val(resource.layer) if resource.layer else None,
                    json.dumps(resource.tags),
                    json.dumps(resource.metadata),
                    resource.mime_type,
                    resource.size_bytes,
                    resource.chunk_count,
                    resource.created_at,
                    resource.updated_at,
                    resource.indexed_at,
                    resource.deleted_at,
                )
        except Exception as e:
            raise StorageError(f"Failed to store resource {resource.id}: {e}") from e
        return resource.id

    async def get_resource(self, resource_id: str) -> Resource | None:
        """Retrieve a resource by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM qp_vault.resources WHERE id = $1", resource_id
            )
            if row is None:
                return None
            return _resource_from_record(dict(row))

    async def list_resources(self, filters: ResourceFilter) -> list[Resource]:
        """List resources matching filters."""
        pool = await self._get_pool()
        conditions = []
        params: list[Any] = []
        idx = 1

        if filters.tenant_id:
            conditions.append(f"tenant_id = ${idx}")
            params.append(filters.tenant_id)
            idx += 1
        if filters.trust_tier:
            conditions.append(f"trust_tier = ${idx}")
            params.append(filters.trust_tier)
            idx += 1
        if filters.status:
            conditions.append(f"status = ${idx}")
            params.append(filters.status)
            idx += 1
        else:
            conditions.append("status != 'deleted'")
        if filters.lifecycle:
            conditions.append(f"lifecycle = ${idx}")
            params.append(filters.lifecycle)
            idx += 1
        if filters.layer:
            conditions.append(f"layer = ${idx}")
            params.append(filters.layer)
            idx += 1
        if filters.collection_id:
            conditions.append(f"collection_id = ${idx}")
            params.append(filters.collection_id)
            idx += 1

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([filters.limit, filters.offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM qp_vault.resources WHERE {where} "  # nosec B608
                f"ORDER BY updated_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params,
            )
            return [_resource_from_record(dict(r)) for r in rows]

    async def update_resource(self, resource_id: str, updates: ResourceUpdate) -> Resource:
        """Update resource fields."""
        pool = await self._get_pool()
        sets = []
        params: list[Any] = []
        idx = 1

        for field in ("name", "trust_tier", "data_classification", "lifecycle",
                       "valid_from", "valid_until", "supersedes", "superseded_by"):
            val = getattr(updates, field, None)
            if val is not None:
                sets.append(f"{field} = ${idx}")
                params.append(val)
                idx += 1

        if updates.tags is not None:
            sets.append(f"tags = ${idx}")
            params.append(json.dumps(updates.tags))
            idx += 1
        if updates.metadata is not None:
            sets.append(f"metadata = ${idx}")
            params.append(json.dumps(updates.metadata))
            idx += 1

        if not sets:
            resource = await self.get_resource(resource_id)
            if resource is None:
                raise StorageError(f"Resource {resource_id} not found")
            return resource

        sets.append(f"updated_at = ${idx}")
        params.append(datetime.now(tz=UTC))
        idx += 1
        params.append(resource_id)

        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE qp_vault.resources SET {', '.join(sets)} WHERE id = ${idx}",  # nosec B608
                *params,
            )

        resource = await self.get_resource(resource_id)
        if resource is None:
            raise StorageError(f"Resource {resource_id} not found after update")
        return resource

    async def delete_resource(self, resource_id: str, *, hard: bool = False) -> None:
        """Soft or hard delete."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if hard:
                await conn.execute("DELETE FROM qp_vault.chunks WHERE resource_id = $1", resource_id)
                await conn.execute("DELETE FROM qp_vault.resources WHERE id = $1", resource_id)
            else:
                now = datetime.now(tz=UTC)
                await conn.execute(
                    "UPDATE qp_vault.resources SET status = 'deleted', deleted_at = $1, updated_at = $1 WHERE id = $2",
                    now, resource_id,
                )

    async def store_chunks(self, resource_id: str, chunks: list[Chunk]) -> None:
        """Store chunks with embeddings."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM qp_vault.chunks WHERE resource_id = $1", resource_id)

            for chunk in chunks:
                embedding_str = str(chunk.embedding) if chunk.embedding else None
                await conn.execute(
                    """INSERT INTO qp_vault.chunks (
                        id, resource_id, content, cid, embedding,
                        chunk_index, page_number, section_title, token_count, speaker
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                    chunk.id, chunk.resource_id, chunk.content, chunk.cid,
                    embedding_str, chunk.chunk_index, chunk.page_number,
                    chunk.section_title, chunk.token_count, chunk.speaker,
                )

            now = datetime.now(tz=UTC)
            await conn.execute(
                "UPDATE qp_vault.resources SET chunk_count = $1, status = 'indexed', "
                "indexed_at = $2, updated_at = $2 WHERE id = $3",
                len(chunks), now, resource_id,
            )

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Hybrid search: pgvector cosine + pg_trgm similarity."""
        pool = await self._get_pool()

        # Build parameterized filter conditions (no string interpolation)
        extra_conditions: list[str] = []
        extra_params: list[Any] = []
        param_idx = 7  # $1-$6 are used by the base query

        if query.filters:
            if query.filters.trust_tier:
                extra_conditions.append(f"r.trust_tier = ${param_idx}")
                extra_params.append(query.filters.trust_tier)
                param_idx += 1
            if query.filters.layer:
                extra_conditions.append(f"r.layer = ${param_idx}")
                extra_params.append(query.filters.layer)
                param_idx += 1
            if query.filters.collection_id:
                extra_conditions.append(f"r.collection_id = ${param_idx}")
                extra_params.append(query.filters.collection_id)
                param_idx += 1

        extra_where = (" AND " + " AND ".join(extra_conditions)) if extra_conditions else ""
        sql = _HYBRID_SEARCH_SQL.format(extra_where=extra_where)

        embedding_param = str(query.query_embedding) if query.query_embedding else None

        all_params = [
            embedding_param,
            query.query_text or "",
            query.vector_weight,
            query.text_weight,
            query.threshold,
            query.top_k,
            *extra_params,
        ]

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *all_params)

        results = []
        for row in rows:
            results.append(SearchResult(
                chunk_id=row["chunk_id"],
                resource_id=row["resource_id"],
                resource_name=row["resource_name"],
                content=row["content"],
                page_number=row["page_number"],
                section_title=row["section_title"],
                vector_similarity=float(row["vector_sim"]),
                text_rank=float(row["text_rank"]),
                trust_tier=TrustTier(row["trust_tier"]),
                cid=row["chunk_cid"],
                lifecycle=row["lifecycle"],
                relevance=float(row["raw_score"]),
            ))

        return results

    async def get_all_hashes(self) -> list[tuple[str, str]]:
        """Return (resource_id, content_hash) for all non-deleted resources."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, content_hash FROM qp_vault.resources WHERE status != 'deleted' ORDER BY id"
            )
            return [(row["id"], row["content_hash"]) for row in rows]

    async def restore_resource(self, resource_id: str) -> Resource:
        """Restore a soft-deleted resource back to indexed status."""
        pool = await self._get_pool()
        now = datetime.now(tz=UTC)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE qp_vault.resources SET status = 'indexed', deleted_at = NULL, updated_at = $1 WHERE id = $2",
                now, resource_id,
            )
        resource = await self.get_resource(resource_id)
        if resource is None:
            raise StorageError(f"Resource {resource_id} not found after restore")
        return resource

    async def get_chunks_for_resource(self, resource_id: str) -> list[Chunk]:
        """Get all chunks for a resource."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM qp_vault.chunks WHERE resource_id = $1 ORDER BY chunk_index",
                resource_id,
            )
            result = []
            for row in rows:
                d = dict(row)
                # Parse embedding from pgvector string format
                emb = d.get("embedding")
                if emb and isinstance(emb, str):
                    emb = [float(x) for x in emb.strip("[]").split(",")]
                d["embedding"] = emb
                result.append(Chunk(**d))
            return result

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
        """Store a provenance record."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO qp_vault.provenance (
                    id, resource_id, uploader_id, upload_method,
                    source_description, original_hash, provenance_signature,
                    signature_verified, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                provenance_id, resource_id, uploader_id, upload_method,
                source_description, original_hash, signature,
                verified, created_at,
            )

    async def get_provenance(self, resource_id: str) -> list[dict[str, Any]]:
        """Get all provenance records for a resource."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM qp_vault.provenance WHERE resource_id = $1 ORDER BY created_at",
                resource_id,
            )
            return [dict(r) for r in rows]

    async def store_collection(
        self, collection_id: str, name: str, description: str, created_at: str
    ) -> None:
        """Store a new collection."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO qp_vault.collections (id, name, description, created_at, updated_at) VALUES ($1, $2, $3, $4, $5)",
                collection_id, name, description, created_at, created_at,
            )

    async def list_collections(self) -> list[dict[str, Any]]:
        """List all collections."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM qp_vault.collections ORDER BY name"
            )
            return [dict(r) for r in rows]

    async def count_resources(self, tenant_id: str) -> int:
        """Count resources for a tenant (atomic, single query)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT COUNT(*) FROM qp_vault.resources WHERE tenant_id = $1 AND status != 'deleted'",
                tenant_id,
            )
            return int(row) if row else 0

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

"""PostgreSQL storage backend for qp-vault.

Production-grade backend with pgvector (HNSW) for vector similarity
and pg_trgm (GIN) for full-text trigram matching.

Requires: pip install qp-vault[postgres]
"""

from __future__ import annotations

import contextlib
import json
import re
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
    metadata JSONB DEFAULT '{{}}'::jsonb,
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

_GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS qp_vault.graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL UNIQUE,
    entity_type VARCHAR(50) NOT NULL,
    properties JSONB DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    primary_space_id UUID,
    resource_id UUID REFERENCES qp_vault.resources(id) ON DELETE SET NULL,
    manifest_resource_id UUID REFERENCES qp_vault.resources(id) ON DELETE SET NULL,
    mention_count INTEGER DEFAULT 0,
    last_mentioned_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS qp_vault.graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_node_id UUID NOT NULL REFERENCES qp_vault.graph_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES qp_vault.graph_nodes(id) ON DELETE CASCADE,
    relation_type VARCHAR(100) NOT NULL,
    properties JSONB DEFAULT '{}',
    weight FLOAT DEFAULT 0.5,
    bidirectional BOOLEAN DEFAULT FALSE,
    source_resource_id UUID REFERENCES qp_vault.resources(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source_node_id, target_node_id, relation_type)
);

CREATE TABLE IF NOT EXISTS qp_vault.graph_node_spaces (
    node_id UUID NOT NULL REFERENCES qp_vault.graph_nodes(id) ON DELETE CASCADE,
    space_id UUID NOT NULL,
    PRIMARY KEY (node_id, space_id)
);

CREATE TABLE IF NOT EXISTS qp_vault.graph_mentions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id UUID NOT NULL REFERENCES qp_vault.graph_nodes(id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES qp_vault.resources(id) ON DELETE CASCADE,
    space_id UUID,
    context_snippet VARCHAR(500) DEFAULT '',
    mentioned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (node_id, resource_id)
);

CREATE TABLE IF NOT EXISTS qp_vault.graph_scan_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    space_id UUID NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    summary_json JSONB,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_tenant ON qp_vault.graph_nodes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_space ON qp_vault.graph_nodes(primary_space_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON qp_vault.graph_nodes(entity_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_slug ON qp_vault.graph_nodes(slug);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON qp_vault.graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON qp_vault.graph_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_mentions_node ON qp_vault.graph_mentions(node_id);
CREATE INDEX IF NOT EXISTS idx_graph_mentions_resource ON qp_vault.graph_mentions(resource_id);
CREATE INDEX IF NOT EXISTS idx_graph_scan_jobs_space ON qp_vault.graph_scan_jobs(space_id);
"""

_GRAPH_TRGM_INDEX = """
CREATE INDEX IF NOT EXISTS idx_graph_nodes_name_trgm ON qp_vault.graph_nodes
    USING gin (name gin_trgm_ops);
"""

_GRAPH_NEIGHBORS_FN = """
CREATE OR REPLACE FUNCTION qp_vault.graph_neighbors(
    start_node_id UUID,
    max_depth INT DEFAULT 1,
    filter_types TEXT[] DEFAULT NULL,
    filter_space UUID DEFAULT NULL
)
RETURNS TABLE(
    node_id UUID,
    node_name VARCHAR,
    entity_type VARCHAR,
    depth INT,
    path UUID[],
    relation_type VARCHAR,
    edge_weight FLOAT
) AS $$
WITH RECURSIVE traversal AS (
    SELECT
        e.target_node_id AS node_id,
        n.name AS node_name,
        n.entity_type,
        1 AS depth,
        ARRAY[start_node_id, e.target_node_id] AS path,
        e.relation_type,
        e.weight AS edge_weight
    FROM qp_vault.graph_edges e
    JOIN qp_vault.graph_nodes n ON n.id = e.target_node_id
    WHERE e.source_node_id = start_node_id
      AND (filter_types IS NULL OR e.relation_type = ANY(filter_types))
      AND (filter_space IS NULL OR n.primary_space_id = filter_space
           OR EXISTS (SELECT 1 FROM qp_vault.graph_node_spaces ns WHERE ns.node_id = n.id AND ns.space_id = filter_space))

    UNION ALL

    SELECT
        e.target_node_id,
        n.name,
        n.entity_type,
        t.depth + 1,
        t.path || e.target_node_id,
        e.relation_type,
        e.weight
    FROM traversal t
    JOIN qp_vault.graph_edges e ON e.source_node_id = t.node_id
    JOIN qp_vault.graph_nodes n ON n.id = e.target_node_id
    WHERE t.depth < max_depth
      AND NOT (e.target_node_id = ANY(t.path))
      AND (filter_types IS NULL OR e.relation_type = ANY(filter_types))
      AND (filter_space IS NULL OR n.primary_space_id = filter_space
           OR EXISTS (SELECT 1 FROM qp_vault.graph_node_spaces ns WHERE ns.node_id = n.id AND ns.space_id = filter_space))
)
SELECT DISTINCT ON (traversal.node_id) * FROM traversal ORDER BY traversal.node_id, traversal.depth;
$$ LANGUAGE SQL STABLE;
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
        self,
        dsn: str,
        *,
        embedding_dimensions: int = 768,
        command_timeout: float = 30.0,
        ssl: str = "prefer",
        ssl_verify: bool = False,
        graph_schema: str = "qp_vault",
    ) -> None:
        """Initialize PostgresBackend.

        Args:
            dsn: PostgreSQL connection string (``postgresql://user:pass@host/db``).
            embedding_dimensions: Vector dimensions for pgvector columns.
            command_timeout: Statement timeout in seconds.
            ssl: SSL mode. Supports ``"prefer"`` (try SSL, fall back to plaintext),
                ``"require"`` (SSL required), ``"disable"`` (no SSL), or ``True``/``False``
                for backward compat. ``sslmode=`` in the DSN always takes precedence.
            ssl_verify: When True, verify the server certificate against the system CA store.
            graph_schema: Schema prefix for graph tables. Set to ``"quantumpipes"``
                to read/write Core's existing ``quantumpipes_graph_*`` tables
                during the migration period. Default: ``"qp_vault"``.
        """
        if not HAS_ASYNCPG:
            raise ImportError(
                "asyncpg is required for PostgresBackend. "
                "Install with: pip install qp-vault[postgres]"
            )
        self._dsn = dsn
        self._dimensions = embedding_dimensions
        self._command_timeout = command_timeout
        # Normalize ssl param: True -> "prefer", False -> "disable"
        if ssl is True:
            self._ssl_mode = "prefer"
        elif ssl is False:
            self._ssl_mode = "disable"
        else:
            self._ssl_mode = ssl
        self._ssl_verify = ssl_verify
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", graph_schema):
            raise ValueError(
                f"graph_schema must be a valid SQL identifier (alphanumeric + underscore), "
                f"got: {graph_schema!r}"
            )
        self._graph_schema = graph_schema
        self._pool: Any = None

    def _gt(self, table: str) -> str:
        """Return schema-qualified graph table name.

        When ``graph_schema="qp_vault"`` (default): ``qp_vault.graph_nodes``
        When ``graph_schema="quantumpipes"``: ``quantumpipes.graph_nodes``
        """
        return f"{self._graph_schema}.{table}"

    def _gsql(self, sql: str) -> str:
        """Replace ``qp_vault.graph_`` with the configured graph schema in SQL.

        Allows all graph methods to use ``qp_vault.graph_`` in their SQL
        strings while supporting schema redirection at runtime.
        """
        if self._graph_schema == "qp_vault":
            return sql
        return sql.replace("qp_vault.graph_", f"{self._graph_schema}.graph_")

    async def _get_pool(self) -> Any:
        """Get or create connection pool.

        SSL behavior follows the ``sslmode`` parameter from the DSN if present,
        otherwise falls back to the ``ssl`` constructor argument (default: ``prefer``).

        ``prefer`` mode: attempt SSL first; on failure, retry without SSL.
        This matches the default behavior of libpq and psycopg.
        """
        if self._pool is None:
            # DSN-level sslmode takes precedence over constructor arg
            if "sslmode=disable" in self._dsn:
                effective_mode = "disable"
            elif "sslmode=require" in self._dsn or "sslmode=verify" in self._dsn:
                effective_mode = "require"
            elif "sslmode=prefer" in self._dsn:
                effective_mode = "prefer"
            else:
                effective_mode = self._ssl_mode

            self._pool = await self._create_pool(effective_mode)
        return self._pool

    async def _create_pool(self, ssl_mode: str) -> Any:
        """Create the connection pool with the given SSL mode."""
        import ssl as _ssl

        pool_kwargs: dict[str, Any] = {
            "min_size": 2,
            "max_size": 10,
            "command_timeout": self._command_timeout,
        }

        if ssl_mode == "disable":
            # No SSL
            pass
        elif ssl_mode in ("require", "verify-full", "verify-ca"):
            ssl_context = _ssl.create_default_context()
            if not self._ssl_verify:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = _ssl.CERT_NONE
            pool_kwargs["ssl"] = ssl_context
        elif ssl_mode == "prefer":
            # Try SSL first, fall back to plaintext on rejection
            ssl_context = _ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = _ssl.CERT_NONE
            pool_kwargs["ssl"] = ssl_context
            try:
                return await asyncpg.create_pool(self._dsn, **pool_kwargs)
            except Exception:
                # SSL rejected; retry without
                pool_kwargs.pop("ssl", None)

        return await asyncpg.create_pool(self._dsn, **pool_kwargs)

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
            gs = self._graph_schema
            graph_ddl = _GRAPH_SCHEMA.replace("qp_vault.", f"{gs}.")
            await conn.execute(graph_ddl)
            with contextlib.suppress(Exception):
                trgm = _GRAPH_TRGM_INDEX.replace("qp_vault.", f"{gs}.")
                await conn.execute(trgm)
            with contextlib.suppress(Exception):
                fn = _GRAPH_NEIGHBORS_FN.replace("qp_vault.", f"{gs}.")
                await conn.execute(fn)

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

    async def get_resources(self, resource_ids: list[str]) -> list[Resource]:
        """Retrieve multiple resources by ID (batch)."""
        if not resource_ids:
            return []
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            placeholders = ", ".join(f"${i + 1}" for i in range(len(resource_ids)))
            rows = await conn.fetch(
                f"SELECT * FROM qp_vault.resources WHERE id IN ({placeholders})",  # noqa: S608
                *resource_ids,
            )
            return [_resource_from_record(dict(r)) for r in rows]

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

    async def grep(
        self,
        keywords: list[str],
        filters: ResourceFilter | None = None,
        top_k: int = 60,
    ) -> list[Any]:
        """Multi-keyword ILIKE + trigram search in a single query.

        Builds a single SQL query with per-keyword CASE expressions for
        hit counting and GREATEST(similarity(...)) for text ranking.
        The GIN trigram index on content accelerates ILIKE matching.

        Args:
            keywords: Pre-sanitized keyword list.
            filters: Optional resource-level filters.
            top_k: Maximum results.

        Returns:
            List of GrepMatch dataclass instances.
        """
        from qp_vault.storage.grep_utils import GrepMatch

        if not keywords:
            return []

        pool = await self._get_pool()

        # Build parameterized query pieces
        # $1 = top_k, $2 = keyword_count, $3..N = keyword patterns
        param_idx = 3
        or_parts: list[str] = []
        hit_parts: list[str] = []
        sim_parts: list[str] = []
        params: list[Any] = [top_k, len(keywords)]

        for kw in keywords:
            or_parts.append(f"c.content ILIKE ${param_idx}")
            hit_parts.append(f"CASE WHEN c.content ILIKE ${param_idx} THEN 1 ELSE 0 END")
            sim_parts.append(f"similarity(c.content, ${param_idx})")
            params.append(f"%{kw}%")
            param_idx += 1

        or_clause = " OR ".join(or_parts)
        hit_count_expr = " + ".join(hit_parts)
        similarity_expr = f"GREATEST({', '.join(sim_parts)})"

        # Extra filters (must include tenant_id for multi-tenant isolation)
        extra_conditions: list[str] = []
        if filters:
            if filters.tenant_id:
                extra_conditions.append(f"r.tenant_id = ${param_idx}")
                params.append(filters.tenant_id)
                param_idx += 1
            if filters.trust_tier:
                extra_conditions.append(f"r.trust_tier = ${param_idx}")
                params.append(filters.trust_tier)
                param_idx += 1
            if filters.layer:
                extra_conditions.append(f"r.layer = ${param_idx}")
                params.append(filters.layer)
                param_idx += 1
            if filters.collection_id:
                extra_conditions.append(f"r.collection_id = ${param_idx}")
                params.append(filters.collection_id)
                param_idx += 1

        extra_where = (" AND " + " AND ".join(extra_conditions)) if extra_conditions else ""

        sql = f"""
            SELECT
                c.id AS chunk_id,
                c.resource_id,
                c.content,
                c.cid,
                c.page_number,
                c.section_title,
                r.name AS resource_name,
                r.trust_tier,
                r.adversarial_status,
                r.lifecycle,
                r.updated_at,
                r.resource_type,
                r.data_classification,
                ({hit_count_expr})::FLOAT / $2 AS hit_density,
                {similarity_expr} AS text_rank
            FROM qp_vault.chunks c
            JOIN qp_vault.resources r ON c.resource_id = r.id
            WHERE r.status = 'indexed'
              AND ({or_clause})
              {extra_where}
            ORDER BY ({hit_count_expr}) DESC, {similarity_expr} DESC
            LIMIT $1
        """  # nosec B608 — all user input parameterized via $N; column/table names hardcoded

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)

        results: list[GrepMatch] = []
        for row in rows:
            content = row["content"]
            content_lower = content.lower()
            matched = [kw for kw in keywords if kw in content_lower]

            results.append(GrepMatch(
                chunk_id=row["chunk_id"],
                resource_id=row["resource_id"],
                resource_name=row["resource_name"],
                content=content,
                matched_keywords=matched,
                hit_density=float(row["hit_density"]),
                text_rank=float(row["text_rank"]),
                trust_tier=row["trust_tier"],
                adversarial_status=row.get("adversarial_status", "unverified"),
                lifecycle=row.get("lifecycle", "active"),
                updated_at=row.get("updated_at"),
                page_number=row["page_number"],
                section_title=row["section_title"],
                resource_type=row.get("resource_type"),
                data_classification=row.get("data_classification"),
                cid=row.get("cid"),
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
                verified, datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at,
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
                collection_id, name, description,
                datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at,
                datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at,
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

    async def find_by_cid(self, cid: str, tenant_id: str | None = None) -> Resource | None:
        """Find a resource by content ID (for deduplication)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            if tenant_id:
                row = await conn.fetchrow(
                    "SELECT * FROM qp_vault.resources WHERE cid = $1 AND tenant_id = $2 AND status != 'deleted' LIMIT 1",
                    cid, tenant_id,
                )
            else:
                row = await conn.fetchrow(
                    "SELECT * FROM qp_vault.resources WHERE cid = $1 AND status != 'deleted' LIMIT 1",
                    cid,
                )
            return _resource_from_record(dict(row)) if row else None

    async def get_embedding_dimension(self) -> int | None:
        """Return embedding dimension from first chunk with embeddings, or None."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT vector_dims(embedding) FROM qp_vault.chunks WHERE embedding IS NOT NULL LIMIT 1"
            )
            return int(row) if row else None

    # --- GraphStorageBackend methods ---

    async def store_node(self, node: dict[str, Any]) -> str:
        """Persist a graph node."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO qp_vault.graph_nodes (
                    id, tenant_id, name, slug, entity_type,
                    properties, tags, primary_space_id,
                    resource_id, manifest_resource_id,
                    mention_count, last_mentioned_at,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)""",
                node["id"], node["tenant_id"], node["name"], node["slug"],
                node["entity_type"], json.dumps(node.get("properties", {})),
                node.get("tags", []), node.get("primary_space_id"),
                node.get("resource_id"), node.get("manifest_resource_id"),
                node.get("mention_count", 0), node.get("last_mentioned_at"),
                node.get("created_at", datetime.now(tz=UTC)),
                node.get("updated_at", datetime.now(tz=UTC)),
            )
        return str(node["id"])

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a graph node by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM qp_vault.graph_nodes WHERE id = $1", node_id,
            )
            if row is None:
                return None
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            return d

    async def list_nodes(
        self, filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """List graph nodes with optional filtering."""
        pool = await self._get_pool()
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if filters.get("tenant_id"):
            conditions.append(f"n.tenant_id = ${idx}")
            params.append(filters["tenant_id"])
            idx += 1
        if filters.get("entity_type"):
            conditions.append(f"n.entity_type = ${idx}")
            params.append(filters["entity_type"])
            idx += 1
        if filters.get("space_id"):
            sid = filters["space_id"]
            conditions.append(
                f"(n.primary_space_id = ${idx} OR EXISTS "
                f"(SELECT 1 FROM qp_vault.graph_node_spaces ns WHERE ns.node_id = n.id AND ns.space_id = ${idx}))"
            )
            params.append(sid)
            idx += 1
        if filters.get("tags"):
            conditions.append(f"n.tags @> ${idx}")
            params.append(filters["tags"])
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"
        limit = filters.get("limit", 50)
        offset = filters.get("offset", 0)

        async with pool.acquire() as conn:
            count_row = await conn.fetchval(
                f"SELECT COUNT(*) FROM qp_vault.graph_nodes n WHERE {where}",  # nosec B608
                *params,
            )
            total = int(count_row) if count_row else 0

            rows = await conn.fetch(
                f"SELECT * FROM qp_vault.graph_nodes n WHERE {where} "  # nosec B608
                f"ORDER BY n.updated_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params, limit, offset,
            )
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("properties"), str):
                    d["properties"] = json.loads(d["properties"])
                results.append(d)
            return results, total

    async def search_nodes(
        self, query: str, space_id: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        """Search graph nodes using trigram similarity on name."""
        pool = await self._get_pool()
        params: list[Any] = [query, limit]
        space_filter = ""
        if space_id:
            space_filter = "AND n.primary_space_id = $3"
            params.append(space_id)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT n.*, similarity(n.name, $1) AS score "  # nosec B608
                f"FROM qp_vault.graph_nodes n "
                f"WHERE similarity(n.name, $1) > 0.3 {space_filter} "
                f"ORDER BY score DESC LIMIT $2",
                *params,
            )
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("properties"), str):
                    d["properties"] = json.loads(d["properties"])
                results.append(d)
            return results

    async def update_node(
        self, node_id: str, updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply partial updates to a graph node."""
        pool = await self._get_pool()
        sets: list[str] = []
        params: list[Any] = []
        idx = 1

        for field in ("name", "slug", "entity_type", "primary_space_id",
                       "resource_id", "manifest_resource_id",
                       "mention_count", "last_mentioned_at"):
            if field in updates:
                sets.append(f"{field} = ${idx}")
                params.append(updates[field])
                idx += 1
        if "properties" in updates:
            sets.append(f"properties = ${idx}")
            params.append(json.dumps(updates["properties"]))
            idx += 1
        if "tags" in updates:
            sets.append(f"tags = ${idx}")
            params.append(updates["tags"])
            idx += 1

        sets.append(f"updated_at = ${idx}")
        params.append(datetime.now(tz=UTC))
        idx += 1
        params.append(node_id)

        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE qp_vault.graph_nodes SET {', '.join(sets)} WHERE id = ${idx}",  # nosec B608
                *params,
            )

        result = await self.get_node(node_id)
        if result is None:
            raise StorageError(f"Graph node {node_id} not found after update")
        return result

    async def delete_node(self, node_id: str) -> None:
        """Delete a graph node (cascades edges, mentions, spaces)."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM qp_vault.graph_nodes WHERE id = $1", node_id,
            )

    async def store_edge(self, edge: dict[str, Any]) -> str:
        """Persist a graph edge."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO qp_vault.graph_edges (
                    id, tenant_id, source_node_id, target_node_id,
                    relation_type, properties, weight, bidirectional,
                    source_resource_id, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (source_node_id, target_node_id, relation_type) DO UPDATE
                SET properties = EXCLUDED.properties,
                    weight = EXCLUDED.weight,
                    updated_at = EXCLUDED.updated_at""",
                edge["id"], edge["tenant_id"], edge["source_node_id"],
                edge["target_node_id"], edge["relation_type"],
                json.dumps(edge.get("properties", {})),
                edge.get("weight", 0.5), edge.get("bidirectional", False),
                edge.get("source_resource_id"),
                edge.get("created_at", datetime.now(tz=UTC)),
                edge.get("updated_at", datetime.now(tz=UTC)),
            )
        return str(edge["id"])

    async def get_edges(
        self, node_id: str, direction: str,
    ) -> list[dict[str, Any]]:
        """Get edges connected to a node."""
        pool = await self._get_pool()
        if direction == "outgoing":
            sql = "SELECT * FROM qp_vault.graph_edges WHERE source_node_id = $1"
        elif direction == "incoming":
            sql = "SELECT * FROM qp_vault.graph_edges WHERE target_node_id = $1"
        else:
            sql = "SELECT * FROM qp_vault.graph_edges WHERE source_node_id = $1 OR target_node_id = $1"

        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, node_id)
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("properties"), str):
                    d["properties"] = json.loads(d["properties"])
                results.append(d)
            return results

    async def update_edge(
        self, edge_id: str, updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply partial updates to a graph edge."""
        pool = await self._get_pool()
        sets: list[str] = []
        params: list[Any] = []
        idx = 1

        for field in ("relation_type", "weight", "bidirectional"):
            if field in updates:
                sets.append(f"{field} = ${idx}")
                params.append(updates[field])
                idx += 1
        if "properties" in updates:
            sets.append(f"properties = ${idx}")
            params.append(json.dumps(updates["properties"]))
            idx += 1

        sets.append(f"updated_at = ${idx}")
        params.append(datetime.now(tz=UTC))
        idx += 1
        params.append(edge_id)

        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE qp_vault.graph_edges SET {', '.join(sets)} WHERE id = ${idx}",  # nosec B608
                *params,
            )
            row = await conn.fetchrow(
                "SELECT * FROM qp_vault.graph_edges WHERE id = $1", edge_id,
            )
            if row is None:
                raise StorageError(f"Graph edge {edge_id} not found after update")
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            return d

    async def delete_edge(self, edge_id: str) -> None:
        """Delete a graph edge."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM qp_vault.graph_edges WHERE id = $1", edge_id,
            )

    async def neighbors(
        self, node_id: str, depth: int,
        relation_types: list[str] | None, space_id: str | None,
    ) -> list[dict[str, Any]]:
        """N-hop neighbor traversal via recursive CTE function."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT node_id, node_name, entity_type, depth,
                          path, relation_type, edge_weight
                   FROM qp_vault.graph_neighbors($1, $2, $3, $4)""",
                node_id, depth, relation_types, space_id,
            )
            return [dict(row) for row in rows]

    async def upsert_mention(
        self, node_id: str, resource_id: str,
        space_id: str | None, context_snippet: str,
    ) -> None:
        """Track entity mention in a resource (upsert)."""
        pool = await self._get_pool()
        now = datetime.now(tz=UTC)
        snippet = context_snippet[:500]

        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM qp_vault.graph_mentions "
                "WHERE node_id = $1 AND resource_id = $2",
                node_id, resource_id,
            )
            is_new = (existing or 0) == 0

            await conn.execute(
                """INSERT INTO qp_vault.graph_mentions
                       (node_id, resource_id, space_id, context_snippet, mentioned_at)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (node_id, resource_id) DO UPDATE
                   SET context_snippet = EXCLUDED.context_snippet,
                       mentioned_at = EXCLUDED.mentioned_at""",
                node_id, resource_id, space_id, snippet, now,
            )

            if is_new:
                await conn.execute(
                    "UPDATE qp_vault.graph_nodes SET mention_count = mention_count + 1, "
                    "last_mentioned_at = $1 WHERE id = $2",
                    now, node_id,
                )
            else:
                await conn.execute(
                    "UPDATE qp_vault.graph_nodes SET last_mentioned_at = $1 WHERE id = $2",
                    now, node_id,
                )

    async def get_backlinks(
        self, node_id: str, limit: int, offset: int,
    ) -> list[dict[str, Any]]:
        """Get all resources that mention an entity."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM qp_vault.graph_mentions WHERE node_id = $1 "
                "ORDER BY mentioned_at DESC LIMIT $2 OFFSET $3",
                node_id, limit, offset,
            )
            return [dict(row) for row in rows]

    async def get_entities_for_resource(
        self, resource_id: str,
    ) -> list[dict[str, Any]]:
        """Get all entities mentioned in a vault resource."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT n.* FROM qp_vault.graph_nodes n "
                "JOIN qp_vault.graph_mentions m ON m.node_id = n.id "
                "WHERE m.resource_id = $1 ORDER BY n.name",
                resource_id,
            )
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("properties"), str):
                    d["properties"] = json.loads(d["properties"])
                results.append(d)
            return results

    async def add_node_to_space(self, node_id: str, space_id: str) -> None:
        """Add cross-space membership."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO qp_vault.graph_node_spaces (node_id, space_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                node_id, space_id,
            )

    async def remove_node_from_space(self, node_id: str, space_id: str) -> None:
        """Remove cross-space membership."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM qp_vault.graph_node_spaces WHERE node_id = $1 AND space_id = $2",
                node_id, space_id,
            )

    async def merge_nodes(
        self, keep_id: str, merge_id: str,
    ) -> dict[str, Any]:
        """Merge two nodes: re-point edges, mentions, spaces; delete merge_id."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                keep = await conn.fetchrow(
                    "SELECT * FROM qp_vault.graph_nodes WHERE id = $1", keep_id,
                )
                merge = await conn.fetchrow(
                    "SELECT * FROM qp_vault.graph_nodes WHERE id = $1", merge_id,
                )
                if keep is None or merge is None:
                    raise StorageError("Both nodes must exist for merge")

                await conn.execute(
                    """UPDATE qp_vault.graph_edges SET source_node_id = $1
                       WHERE source_node_id = $2
                       AND NOT EXISTS (
                           SELECT 1 FROM qp_vault.graph_edges e2
                           WHERE e2.source_node_id = $1
                           AND e2.target_node_id = qp_vault.graph_edges.target_node_id
                           AND e2.relation_type = qp_vault.graph_edges.relation_type
                       )""",
                    keep_id, merge_id,
                )
                await conn.execute(
                    """UPDATE qp_vault.graph_edges SET target_node_id = $1
                       WHERE target_node_id = $2
                       AND NOT EXISTS (
                           SELECT 1 FROM qp_vault.graph_edges e2
                           WHERE e2.source_node_id = qp_vault.graph_edges.source_node_id
                           AND e2.target_node_id = $1
                           AND e2.relation_type = qp_vault.graph_edges.relation_type
                       )""",
                    keep_id, merge_id,
                )
                await conn.execute(
                    """UPDATE qp_vault.graph_mentions SET node_id = $1
                       WHERE node_id = $2
                       AND NOT EXISTS (
                           SELECT 1 FROM qp_vault.graph_mentions m2
                           WHERE m2.node_id = $1
                           AND m2.resource_id = qp_vault.graph_mentions.resource_id
                       )""",
                    keep_id, merge_id,
                )
                await conn.execute(
                    """INSERT INTO qp_vault.graph_node_spaces (node_id, space_id)
                       SELECT $1, space_id FROM qp_vault.graph_node_spaces
                       WHERE node_id = $2
                       ON CONFLICT DO NOTHING""",
                    keep_id, merge_id,
                )

                keep_props = json.loads(keep["properties"]) if isinstance(keep["properties"], str) else (keep["properties"] or {})
                merge_props = json.loads(merge["properties"]) if isinstance(merge["properties"], str) else (merge["properties"] or {})
                merged_props = {**merge_props, **keep_props}
                keep_tags = list(keep.get("tags") or [])
                merge_tags = list(merge.get("tags") or [])
                merged_tags = list(set(keep_tags + merge_tags))
                merged_count = (keep["mention_count"] or 0) + (merge["mention_count"] or 0)

                await conn.execute(
                    "UPDATE qp_vault.graph_nodes SET properties = $1, tags = $2, "
                    "mention_count = $3, updated_at = $4 WHERE id = $5",
                    json.dumps(merged_props), merged_tags, merged_count,
                    datetime.now(tz=UTC), keep_id,
                )
                await conn.execute(
                    "DELETE FROM qp_vault.graph_nodes WHERE id = $1", merge_id,
                )

        result = await self.get_node(keep_id)
        if result is None:
            raise StorageError(f"Graph node {keep_id} not found after merge")
        return result

    async def store_scan_job(self, job: dict[str, Any]) -> str:
        """Persist a scan job record."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO qp_vault.graph_scan_jobs
                       (id, tenant_id, space_id, status, started_at, finished_at, summary_json, error)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                job["id"], job["tenant_id"], job["space_id"],
                job.get("status", "running"),
                job.get("started_at", datetime.now(tz=UTC)),
                job.get("finished_at"),
                json.dumps(job["summary"]) if job.get("summary") else None,
                job.get("error"),
            )
        return str(job["id"])

    async def get_scan_job(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve a scan job by ID."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM qp_vault.graph_scan_jobs WHERE id = $1", job_id,
            )
            if row is None:
                return None
            d = dict(row)
            if isinstance(d.get("summary_json"), str):
                d["summary"] = json.loads(d["summary_json"])
            elif d.get("summary_json") is not None:
                d["summary"] = d["summary_json"]
            else:
                d["summary"] = None
            return d

    async def list_scan_jobs(
        self, filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """List scan jobs with optional filtering."""
        pool = await self._get_pool()
        conditions: list[str] = []
        params: list[Any] = []
        idx = 1

        if filters.get("space_id"):
            conditions.append(f"space_id = ${idx}")
            params.append(filters["space_id"])
            idx += 1
        if filters.get("status"):
            conditions.append(f"status = ${idx}")
            params.append(filters["status"])
            idx += 1

        where = " AND ".join(conditions) if conditions else "TRUE"
        limit = filters.get("limit", 50)
        offset = filters.get("offset", 0)

        async with pool.acquire() as conn:
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM qp_vault.graph_scan_jobs WHERE {where}",  # nosec B608
                *params,
            )
            rows = await conn.fetch(
                f"SELECT * FROM qp_vault.graph_scan_jobs WHERE {where} "  # nosec B608
                f"ORDER BY started_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
                *params, limit, offset,
            )
            results = []
            for row in rows:
                d = dict(row)
                if isinstance(d.get("summary_json"), str):
                    d["summary"] = json.loads(d["summary_json"])
                elif d.get("summary_json") is not None:
                    d["summary"] = d["summary_json"]
                else:
                    d["summary"] = None
                results.append(d)
            return results, int(total) if total else 0

    async def update_scan_job(
        self, job_id: str, updates: dict[str, Any],
    ) -> None:
        """Update a scan job's fields."""
        pool = await self._get_pool()
        sets: list[str] = []
        params: list[Any] = []
        idx = 1

        for field in ("status", "finished_at", "error"):
            if field in updates:
                sets.append(f"{field} = ${idx}")
                params.append(updates[field])
                idx += 1
        if "summary" in updates:
            sets.append(f"summary_json = ${idx}")
            params.append(json.dumps(updates["summary"]) if updates["summary"] else None)
            idx += 1

        if not sets:
            return

        params.append(job_id)
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE qp_vault.graph_scan_jobs SET {', '.join(sets)} WHERE id = ${idx}",  # nosec B608
                *params,
            )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

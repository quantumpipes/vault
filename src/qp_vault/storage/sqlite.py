"""SQLite storage backend for qp-vault.

Zero-config embedded storage with FTS5 full-text search.
This is the default backend when no PostgreSQL DSN is provided.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from qp_vault.enums import ResourceStatus, TrustTier
from qp_vault.exceptions import StorageError
from qp_vault.models import Chunk, Resource, SearchResult

if TYPE_CHECKING:
    from pathlib import Path

    from qp_vault.protocols import ResourceFilter, ResourceUpdate, SearchQuery

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
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
    valid_from TEXT,
    valid_until TEXT,
    supersedes TEXT,
    superseded_by TEXT,
    tenant_id TEXT,
    collection_id TEXT,
    layer TEXT,
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}',
    mime_type TEXT,
    size_bytes INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    indexed_at TEXT,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    content TEXT NOT NULL,
    cid TEXT NOT NULL,
    embedding TEXT,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    section_title TEXT,
    token_count INTEGER DEFAULT 0,
    speaker TEXT,
    FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_public INTEGER DEFAULT 0,
    resource_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_collections (
    resource_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    PRIMARY KEY (resource_id, collection_id),
    FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vault_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resources_status ON resources(status);
CREATE INDEX IF NOT EXISTS idx_resources_trust ON resources(trust_tier);
CREATE INDEX IF NOT EXISTS idx_resources_lifecycle ON resources(lifecycle);
CREATE INDEX IF NOT EXISTS idx_resources_collection ON resources(collection_id);
CREATE INDEX IF NOT EXISTS idx_resources_layer ON resources(layer);
CREATE INDEX IF NOT EXISTS idx_resources_hash ON resources(content_hash);
CREATE TABLE IF NOT EXISTS provenance (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    uploader_id TEXT,
    upload_method TEXT,
    source_description TEXT DEFAULT '',
    original_hash TEXT NOT NULL,
    provenance_signature TEXT,
    signature_verified INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chunks_resource ON chunks(resource_id);
CREATE INDEX IF NOT EXISTS idx_chunks_cid ON chunks(cid);
CREATE INDEX IF NOT EXISTS idx_provenance_resource ON provenance(resource_id);
CREATE INDEX IF NOT EXISTS idx_resources_adversarial ON resources(adversarial_status);
CREATE INDEX IF NOT EXISTS idx_resources_tenant ON resources(tenant_id);
CREATE INDEX IF NOT EXISTS idx_resources_classification ON resources(data_classification);
CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(resource_type);
"""

_GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    entity_type TEXT NOT NULL,
    properties TEXT DEFAULT '{}',
    tags TEXT DEFAULT '[]',
    primary_space_id TEXT,
    resource_id TEXT REFERENCES resources(id) ON DELETE SET NULL,
    manifest_resource_id TEXT REFERENCES resources(id) ON DELETE SET NULL,
    mention_count INTEGER DEFAULT 0,
    last_mentioned_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_edges (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_node_id TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    properties TEXT DEFAULT '{}',
    weight REAL DEFAULT 0.5,
    bidirectional INTEGER DEFAULT 0,
    source_resource_id TEXT REFERENCES resources(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (source_node_id, target_node_id, relation_type)
);

CREATE TABLE IF NOT EXISTS graph_node_spaces (
    node_id TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    space_id TEXT NOT NULL,
    PRIMARY KEY (node_id, space_id)
);

CREATE TABLE IF NOT EXISTS graph_mentions (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    space_id TEXT,
    context_snippet TEXT DEFAULT '',
    mentioned_at TEXT NOT NULL,
    UNIQUE (node_id, resource_id)
);

CREATE TABLE IF NOT EXISTS graph_scan_jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    space_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    summary_json TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_tenant ON graph_nodes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_space ON graph_nodes(primary_space_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(entity_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_slug ON graph_nodes(slug);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_mentions_node ON graph_mentions(node_id);
CREATE INDEX IF NOT EXISTS idx_graph_mentions_resource ON graph_mentions(resource_id);
CREATE INDEX IF NOT EXISTS idx_graph_scan_jobs_space ON graph_scan_jobs(space_id);
"""

_GRAPH_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS graph_nodes_fts USING fts5(
    name,
    content='graph_nodes',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS graph_nodes_ai AFTER INSERT ON graph_nodes BEGIN
    INSERT INTO graph_nodes_fts(rowid, name) VALUES (new.rowid, new.name);
END;

CREATE TRIGGER IF NOT EXISTS graph_nodes_ad AFTER DELETE ON graph_nodes BEGIN
    INSERT INTO graph_nodes_fts(graph_nodes_fts, rowid, name) VALUES('delete', old.rowid, old.name);
END;

CREATE TRIGGER IF NOT EXISTS graph_nodes_au AFTER UPDATE ON graph_nodes BEGIN
    INSERT INTO graph_nodes_fts(graph_nodes_fts, rowid, name) VALUES('delete', old.rowid, old.name);
    INSERT INTO graph_nodes_fts(rowid, name) VALUES (new.rowid, new.name);
END;
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.rowid, new.content);
END;
"""


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH.

    FTS5 has its own query syntax where characters like *, ", (, )
    have special meaning. We strip them to prevent OperationalError.
    """
    import re
    # Remove FTS5 special operators and syntax characters
    cleaned = re.sub(r'[*"()\-{}[\]^~:+]', " ", query)
    # Collapse whitespace
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _enum_val(v: Any) -> str:
    """Extract .value from enum, or return str directly."""
    return v.value if hasattr(v, "value") else str(v)


def _resource_from_row(row: dict[str, Any]) -> Resource:
    """Convert a SQLite row dict to a Resource model."""
    data = dict(row)
    data["tags"] = json.loads(data.get("tags") or "[]")
    data["metadata"] = json.loads(data.get("metadata") or "{}")
    return Resource(**data)


class SQLiteBackend:
    """SQLite storage backend with FTS5 full-text search.

    Uses WAL mode for concurrent read/write safety.
    Embeddings stored as JSON arrays; cosine similarity computed in Python.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    @staticmethod
    def _restrict_file_permissions(path: Path) -> None:
        """Set file to owner-only read/write (0600)."""
        import os
        import stat
        if path.exists():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)

    async def initialize(self) -> None:
        """Create tables and indexes."""
        import contextlib

        created = not self.db_path.exists()
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        with contextlib.suppress(sqlite3.OperationalError):
            conn.executescript(_FTS_SCHEMA)
        conn.executescript(_GRAPH_SCHEMA)
        with contextlib.suppress(sqlite3.OperationalError):
            conn.executescript(_GRAPH_FTS_SCHEMA)
        conn.commit()

        # Restrict file permissions on new databases (owner-only rw)
        if created:
            self._restrict_file_permissions(self.db_path)
            for suffix in ("-wal", "-shm"):
                wal_path = self.db_path.with_name(self.db_path.name + suffix)
                self._restrict_file_permissions(wal_path)

    async def store_resource(self, resource: Resource) -> str:
        """Store a resource. Returns resource ID."""
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO resources (
                    id, name, content_hash, cid, merkle_root,
                    trust_tier, data_classification, resource_type,
                    status, lifecycle, adversarial_status, valid_from, valid_until,
                    supersedes, superseded_by, tenant_id, collection_id, layer,
                    tags, metadata, mime_type, size_bytes, chunk_count,
                    created_at, updated_at, indexed_at, deleted_at
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )""",
                (
                    resource.id,
                    resource.name,
                    resource.content_hash,
                    resource.cid,
                    resource.merkle_root,
                    resource.trust_tier.value if hasattr(resource.trust_tier, "value") else resource.trust_tier,
                    resource.data_classification.value if hasattr(resource.data_classification, "value") else resource.data_classification,
                    resource.resource_type.value if hasattr(resource.resource_type, "value") else resource.resource_type,
                    resource.status.value if hasattr(resource.status, "value") else resource.status,
                    resource.lifecycle.value if hasattr(resource.lifecycle, "value") else resource.lifecycle,
                    _enum_val(getattr(resource, "adversarial_status", "unverified")),
                    str(resource.valid_from) if resource.valid_from else None,
                    str(resource.valid_until) if resource.valid_until else None,
                    resource.supersedes,
                    resource.superseded_by,
                    resource.tenant_id,
                    resource.collection_id,
                    resource.layer.value if resource.layer and hasattr(resource.layer, "value") else resource.layer,
                    json.dumps(resource.tags),
                    json.dumps(resource.metadata),
                    resource.mime_type,
                    resource.size_bytes,
                    resource.chunk_count,
                    resource.created_at.isoformat(),
                    resource.updated_at.isoformat(),
                    resource.indexed_at.isoformat() if resource.indexed_at else None,
                    resource.deleted_at.isoformat() if resource.deleted_at else None,
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise StorageError(f"Failed to store resource {resource.id}: {e}") from e
        return resource.id

    async def get_resource(self, resource_id: str) -> Resource | None:
        """Retrieve a resource by ID."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
        if row is None:
            return None
        return _resource_from_row(dict(row))

    async def get_resources(self, resource_ids: list[str]) -> list[Resource]:
        """Retrieve multiple resources by ID (batch)."""
        if not resource_ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in resource_ids)
        rows = conn.execute(
            f"SELECT * FROM resources WHERE id IN ({placeholders})",  # noqa: S608
            resource_ids,
        ).fetchall()
        return [_resource_from_row(dict(r)) for r in rows]

    async def list_resources(self, filters: ResourceFilter) -> list[Resource]:
        """List resources matching filters."""
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        if filters.tenant_id:
            conditions.append("tenant_id = ?")
            params.append(filters.tenant_id)
        if filters.trust_tier:
            conditions.append("trust_tier = ?")
            params.append(filters.trust_tier)
        if filters.data_classification:
            conditions.append("data_classification = ?")
            params.append(filters.data_classification)
        if filters.resource_type:
            conditions.append("resource_type = ?")
            params.append(filters.resource_type)
        if filters.status:
            conditions.append("status = ?")
            params.append(filters.status)
        else:
            # Exclude deleted by default
            conditions.append("status != 'deleted'")
        if filters.lifecycle:
            conditions.append("lifecycle = ?")
            params.append(filters.lifecycle)
        if filters.layer:
            conditions.append("layer = ?")
            params.append(filters.layer)
        if filters.collection_id:
            conditions.append("collection_id = ?")
            params.append(filters.collection_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM resources WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"  # nosec B608 — conditions use ? params; column names from code, not user input
        params.extend([filters.limit, filters.offset])

        rows = conn.execute(sql, params).fetchall()
        return [_resource_from_row(dict(r)) for r in rows]

    async def update_resource(self, resource_id: str, updates: ResourceUpdate) -> Resource:
        """Update resource fields."""
        conn = self._get_conn()
        sets: list[str] = []
        params: list[Any] = []

        for field_name in (
            "name", "trust_tier", "data_classification", "lifecycle",
            "adversarial_status", "valid_from", "valid_until", "supersedes", "superseded_by",
        ):
            val = getattr(updates, field_name, None)
            if val is not None:
                sets.append(f"{field_name} = ?")
                params.append(val)

        if updates.tags is not None:
            sets.append("tags = ?")
            params.append(json.dumps(updates.tags))
        if updates.metadata is not None:
            sets.append("metadata = ?")
            params.append(json.dumps(updates.metadata))

        if not sets:
            resource = await self.get_resource(resource_id)
            if resource is None:
                raise StorageError(f"Resource {resource_id} not found")
            return resource

        sets.append("updated_at = ?")
        params.append(datetime.now(tz=UTC).isoformat())
        params.append(resource_id)

        conn.execute(f"UPDATE resources SET {', '.join(sets)} WHERE id = ?", params)  # nosec B608 — sets built from hardcoded field tuple (L290-293)
        conn.commit()

        resource = await self.get_resource(resource_id)
        if resource is None:
            raise StorageError(f"Resource {resource_id} not found after update")
        return resource

    async def delete_resource(self, resource_id: str, *, hard: bool = False) -> None:
        """Soft or hard delete a resource."""
        conn = self._get_conn()
        if hard:
            conn.execute("DELETE FROM chunks WHERE resource_id = ?", (resource_id,))
            conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
        else:
            now = datetime.now(tz=UTC).isoformat()
            conn.execute(
                "UPDATE resources SET status = 'deleted', deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, resource_id),
            )
        conn.commit()

    async def store_chunks(self, resource_id: str, chunks: list[Chunk]) -> None:
        """Store chunks with optional embeddings."""
        conn = self._get_conn()
        # Delete existing chunks for this resource (re-indexing)
        conn.execute("DELETE FROM chunks WHERE resource_id = ?", (resource_id,))
        for chunk in chunks:
            embedding_json = json.dumps(chunk.embedding) if chunk.embedding else None
            conn.execute(
                """INSERT INTO chunks (
                    id, resource_id, content, cid, embedding,
                    chunk_index, page_number, section_title, token_count, speaker
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chunk.id,
                    chunk.resource_id,
                    chunk.content,
                    chunk.cid,
                    embedding_json,
                    chunk.chunk_index,
                    chunk.page_number,
                    chunk.section_title,
                    chunk.token_count,
                    chunk.speaker,
                ),
            )
        # Update resource chunk count and status
        conn.execute(
            "UPDATE resources SET chunk_count = ?, status = ?, indexed_at = ?, updated_at = ? WHERE id = ?",
            (len(chunks), ResourceStatus.INDEXED.value, datetime.now(tz=UTC).isoformat(), datetime.now(tz=UTC).isoformat(), resource_id),
        )
        conn.commit()

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        """Hybrid search: FTS5 text matching + optional vector cosine similarity."""
        conn = self._get_conn()
        results: list[SearchResult] = []

        # Build WHERE clause for resource-level filters
        where_parts = ["r.status = 'indexed'"]
        where_params: list[Any] = []

        filter_tenant = query.filters.tenant_id if query.filters else None
        filter_trust = query.filters.trust_tier if query.filters else None
        filter_layer = query.filters.layer if query.filters else None
        filter_collection = query.filters.collection_id if query.filters else None

        if filter_tenant:
            where_parts.append("r.tenant_id = ?")
            where_params.append(filter_tenant)
        if filter_trust:
            where_parts.append("r.trust_tier = ?")
            where_params.append(filter_trust)
        if filter_layer:
            where_parts.append("r.layer = ?")
            where_params.append(filter_layer)
        if filter_collection:
            where_parts.append("r.collection_id = ?")
            where_params.append(filter_collection)

        where_clause = " AND ".join(where_parts)

        # Get indexed chunks with resource info and rowid for FTS mapping
        # Column names and table names are all hardcoded; only where_clause has ? params
        search_sql = (
            f"SELECT c.rowid as chunk_rowid, c.id as chunk_id, c.resource_id,"  # nosec B608
            f" c.content, c.cid as chunk_cid, c.embedding,"
            f" c.page_number, c.section_title, c.chunk_index,"
            f" r.name as resource_name, r.trust_tier, r.lifecycle,"
            f" r.updated_at as resource_updated_at, r.resource_type, r.data_classification"
            f" FROM chunks c JOIN resources r ON c.resource_id = r.id"
            f" WHERE {where_clause} ORDER BY c.chunk_index"
        )
        rows = conn.execute(search_sql, where_params).fetchall()

        # FTS5 match scores (if available and query text provided)
        fts_scores: dict[int, float] = {}
        if query.query_text:
            try:
                # Sanitize FTS5 query: escape special characters, wrap terms in quotes
                safe_query = _sanitize_fts_query(query.query_text)
                if safe_query:
                    fts_rows = conn.execute(
                        """SELECT rowid, rank FROM chunks_fts
                           WHERE chunks_fts MATCH ?
                           ORDER BY rank LIMIT ?""",
                        (safe_query, query.top_k * 5),
                    ).fetchall()
                    for fr in fts_rows:
                        fts_scores[fr["rowid"]] = 1.0 / (1.0 + abs(fr["rank"]))
            except sqlite3.OperationalError:
                pass

        for row in rows:
            row_dict = dict(row)

            # Vector similarity
            vector_sim = 0.0
            if query.query_embedding and row_dict["embedding"]:
                chunk_embedding = json.loads(row_dict["embedding"])
                vector_sim = _cosine_similarity(query.query_embedding, chunk_embedding)

            # Text rank from FTS5 (use pre-fetched rowid, no extra query)
            text_rank = fts_scores.get(row_dict["chunk_rowid"], 0.0)

            # Skip if both scores are zero
            if vector_sim == 0.0 and text_rank == 0.0:
                continue

            # Raw score
            raw_score = query.vector_weight * vector_sim + query.text_weight * text_rank

            if raw_score < query.threshold:
                continue

            results.append(
                SearchResult(
                    chunk_id=row_dict["chunk_id"],
                    resource_id=row_dict["resource_id"],
                    resource_name=row_dict["resource_name"],
                    content=row_dict["content"],
                    page_number=row_dict["page_number"],
                    section_title=row_dict["section_title"],
                    vector_similarity=vector_sim,
                    text_rank=text_rank,
                    trust_tier=TrustTier(row_dict["trust_tier"]),
                    cid=row_dict["chunk_cid"],
                    lifecycle=row_dict["lifecycle"],
                    updated_at=row_dict.get("resource_updated_at"),
                    resource_type=row_dict.get("resource_type"),
                    data_classification=row_dict.get("data_classification"),
                    relevance=raw_score,
                )
            )

        results.sort(key=lambda r: r.relevance, reverse=True)
        return results[: query.top_k]

    async def grep(
        self,
        keywords: list[str],
        filters: ResourceFilter | None = None,
        top_k: int = 60,
    ) -> list[Any]:
        """Multi-keyword FTS5 OR search in a single query.

        Executes one FTS5 MATCH with OR-joined keywords, then computes
        per-keyword match flags and hit density in Python (on the small
        set of matched rows only).

        Args:
            keywords: Pre-sanitized keyword list.
            filters: Optional resource-level filters.
            top_k: Maximum results.

        Returns:
            List of GrepMatch dataclass instances.
        """
        from qp_vault.storage.grep_utils import (
            GrepMatch,
            build_fts_or_query,
            extract_matched_keywords,
        )

        if not keywords:
            return []

        conn = self._get_conn()

        # Build FTS5 OR expression
        fts_expr = build_fts_or_query(keywords)
        if not fts_expr:
            return []

        # Resource-level filters
        where_parts = ["r.status = 'indexed'"]
        where_params: list[Any] = []

        if filters:
            if filters.tenant_id:
                where_parts.append("r.tenant_id = ?")
                where_params.append(filters.tenant_id)
            if filters.trust_tier:
                where_parts.append("r.trust_tier = ?")
                where_params.append(filters.trust_tier)
            if filters.layer:
                where_parts.append("r.layer = ?")
                where_params.append(filters.layer)
            if filters.collection_id:
                where_parts.append("r.collection_id = ?")
                where_params.append(filters.collection_id)

        where_clause = " AND ".join(where_parts)

        # Single FTS5 query: match all keywords with OR, get rank
        try:
            fts_sql = (
                "SELECT fts.rowid, fts.rank"
                " FROM chunks_fts fts"
                " WHERE chunks_fts MATCH ?"
                " ORDER BY fts.rank"
                f" LIMIT {top_k * 3}"  # Over-fetch for post-filtering
            )
            fts_rows = conn.execute(fts_sql, (fts_expr,)).fetchall()
        except sqlite3.OperationalError:
            return []

        if not fts_rows:
            return []

        # Build rowid set and rank lookup
        fts_ranks: dict[int, float] = {}
        for fr in fts_rows:
            # Normalize FTS5 rank: lower (more negative) = better match
            fts_ranks[fr["rowid"]] = 1.0 / (1.0 + abs(fr["rank"]))

        rowid_list = ",".join(str(r) for r in fts_ranks)

        # Fetch chunk + resource data for matched rowids
        # Column/table names hardcoded; only where_clause uses ? params
        data_sql = (
            f"SELECT c.rowid AS chunk_rowid, c.id AS chunk_id,"  # nosec B608
            f" c.resource_id, c.content, c.cid,"
            f" c.page_number, c.section_title,"
            f" r.name AS resource_name, r.trust_tier,"
            f" r.adversarial_status, r.lifecycle,"
            f" r.updated_at, r.resource_type, r.data_classification"
            f" FROM chunks c JOIN resources r ON c.resource_id = r.id"
            f" WHERE c.rowid IN ({rowid_list}) AND {where_clause}"
        )
        rows = conn.execute(data_sql, where_params).fetchall()

        total_kw = len(keywords)
        results: list[GrepMatch] = []

        for row in rows:
            row_dict = dict(row)
            content = row_dict["content"]
            matched = extract_matched_keywords(content, keywords)
            if not matched:
                continue

            results.append(GrepMatch(
                chunk_id=row_dict["chunk_id"],
                resource_id=row_dict["resource_id"],
                resource_name=row_dict["resource_name"],
                content=content,
                matched_keywords=matched,
                hit_density=len(matched) / total_kw,
                text_rank=fts_ranks.get(row_dict["chunk_rowid"], 0.0),
                trust_tier=row_dict["trust_tier"],
                adversarial_status=row_dict.get("adversarial_status", "unverified"),
                lifecycle=row_dict.get("lifecycle", "active"),
                updated_at=row_dict.get("updated_at"),
                page_number=row_dict["page_number"],
                section_title=row_dict["section_title"],
                resource_type=row_dict.get("resource_type"),
                data_classification=row_dict.get("data_classification"),
                cid=row_dict.get("cid"),
            ))

        # Sort by density first, then text_rank
        results.sort(key=lambda r: (r.hit_density, r.text_rank), reverse=True)
        return results[:top_k]

    async def get_all_hashes(self) -> list[tuple[str, str]]:
        """Return (resource_id, content_hash) for all non-deleted resources."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, content_hash FROM resources WHERE status != 'deleted' ORDER BY id"
        ).fetchall()
        return [(row["id"], row["content_hash"]) for row in rows]

    async def restore_resource(self, resource_id: str) -> Resource:
        """Restore a soft-deleted resource back to indexed status."""
        conn = self._get_conn()
        now = datetime.now(tz=UTC).isoformat()
        conn.execute(
            "UPDATE resources SET status = 'indexed', deleted_at = NULL, updated_at = ? WHERE id = ?",
            (now, resource_id),
        )
        conn.commit()
        resource = await self.get_resource(resource_id)
        if resource is None:
            raise StorageError(f"Resource {resource_id} not found after restore")
        return resource

    async def get_chunks_for_resource(self, resource_id: str) -> list[Chunk]:
        """Get all chunks for a resource."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM chunks WHERE resource_id = ? ORDER BY chunk_index",
            (resource_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["embedding"] = json.loads(d["embedding"]) if d["embedding"] else None
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
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO provenance (
                id, resource_id, uploader_id, upload_method,
                source_description, original_hash, provenance_signature,
                signature_verified, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                provenance_id, resource_id, uploader_id, upload_method,
                source_description, original_hash, signature,
                1 if verified else 0, created_at,
            ),
        )
        conn.commit()

    async def get_provenance(self, resource_id: str) -> list[dict[str, Any]]:
        """Get all provenance records for a resource."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM provenance WHERE resource_id = ? ORDER BY created_at",
            (resource_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def store_collection(
        self, collection_id: str, name: str, description: str, created_at: str
    ) -> None:
        """Store a new collection."""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO collections (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (collection_id, name, description, created_at, created_at),
        )
        conn.commit()

    async def list_collections(self) -> list[dict[str, Any]]:
        """List all collections."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM collections ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    async def count_resources(self, tenant_id: str) -> int:
        """Count resources for a tenant (atomic, single query)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM resources WHERE tenant_id = ? AND status != 'deleted'",
            (tenant_id,),
        ).fetchone()
        return row[0] if row else 0

    async def find_by_cid(self, cid: str, tenant_id: str | None = None) -> Resource | None:
        """Find a resource by content ID (for deduplication)."""
        conn = self._get_conn()
        if tenant_id:
            row = conn.execute(
                "SELECT * FROM resources WHERE cid = ? AND tenant_id = ? AND status != 'deleted' LIMIT 1",
                (cid, tenant_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM resources WHERE cid = ? AND status != 'deleted' LIMIT 1",
                (cid,),
            ).fetchone()
        return _resource_from_row(dict(row)) if row else None

    async def get_embedding_dimension(self) -> int | None:
        """Return embedding dimension from first chunk with embeddings, or None."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT embedding FROM chunks WHERE embedding IS NOT NULL AND embedding != '[]' LIMIT 1"
        ).fetchone()
        if row and row["embedding"]:
            import json
            emb = json.loads(row["embedding"])
            return len(emb) if isinstance(emb, list) else None
        return None

    # --- GraphStorageBackend methods ---

    async def store_node(self, node: dict[str, Any]) -> str:
        """Persist a graph node."""
        conn = self._get_conn()
        now = datetime.now(tz=UTC).isoformat()
        conn.execute(
            """INSERT INTO graph_nodes (
                id, tenant_id, name, slug, entity_type,
                properties, tags, primary_space_id,
                resource_id, manifest_resource_id,
                mention_count, last_mentioned_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(node["id"]), str(node["tenant_id"]), node["name"],
                node["slug"], node["entity_type"],
                json.dumps(node.get("properties", {})),
                json.dumps(node.get("tags", [])),
                str(node["primary_space_id"]) if node.get("primary_space_id") else None,
                str(node["resource_id"]) if node.get("resource_id") else None,
                str(node["manifest_resource_id"]) if node.get("manifest_resource_id") else None,
                node.get("mention_count", 0),
                node["last_mentioned_at"].isoformat() if node.get("last_mentioned_at") else None,
                node.get("created_at", now) if isinstance(node.get("created_at"), str) else (node["created_at"].isoformat() if node.get("created_at") else now),
                node.get("updated_at", now) if isinstance(node.get("updated_at"), str) else (node["updated_at"].isoformat() if node.get("updated_at") else now),
            ),
        )
        conn.commit()
        return str(node["id"])

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a graph node by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM graph_nodes WHERE id = ?", (str(node_id),),
        ).fetchone()
        if row is None:
            return None
        return self._graph_node_from_row(dict(row))

    def _graph_node_from_row(self, d: dict[str, Any]) -> dict[str, Any]:
        """Convert SQLite row to dict with proper JSON parsing."""
        if isinstance(d.get("properties"), str):
            d["properties"] = json.loads(d["properties"])
        if isinstance(d.get("tags"), str):
            d["tags"] = json.loads(d["tags"])
        return d

    async def list_nodes(
        self, filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """List graph nodes with optional filtering."""
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        if filters.get("tenant_id"):
            conditions.append("n.tenant_id = ?")
            params.append(str(filters["tenant_id"]))
        if filters.get("entity_type"):
            conditions.append("n.entity_type = ?")
            params.append(filters["entity_type"])
        if filters.get("space_id"):
            sid = str(filters["space_id"])
            conditions.append(
                "(n.primary_space_id = ? OR EXISTS "
                "(SELECT 1 FROM graph_node_spaces ns WHERE ns.node_id = n.id AND ns.space_id = ?))"
            )
            params.extend([sid, sid])

        where = " AND ".join(conditions) if conditions else "1=1"
        limit = filters.get("limit", 50)
        offset = filters.get("offset", 0)

        count_row = conn.execute(
            f"SELECT COUNT(*) FROM graph_nodes n WHERE {where}",  # nosec B608
            params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            f"SELECT * FROM graph_nodes n WHERE {where} "  # nosec B608
            f"ORDER BY n.updated_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        return [self._graph_node_from_row(dict(r)) for r in rows], total

    async def search_nodes(
        self, query: str, space_id: str | None, limit: int,
    ) -> list[dict[str, Any]]:
        """Search graph nodes using FTS5 on name."""
        conn = self._get_conn()
        safe_query = _sanitize_fts_query(query)
        if not safe_query:
            return []

        try:
            fts_rows = conn.execute(
                "SELECT rowid, rank FROM graph_nodes_fts "
                "WHERE graph_nodes_fts MATCH ? ORDER BY rank LIMIT ?",
                (safe_query, limit * 3),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        if not fts_rows:
            return []

        rowid_ranks = {r["rowid"]: 1.0 / (1.0 + abs(r["rank"])) for r in fts_rows}
        rowid_list = ",".join(str(r) for r in rowid_ranks)

        where_parts = [f"n.rowid IN ({rowid_list})"]
        params: list[Any] = []
        if space_id:
            where_parts.append("n.primary_space_id = ?")
            params.append(str(space_id))

        where = " AND ".join(where_parts)
        rows = conn.execute(
            f"SELECT n.*, n.rowid AS node_rowid FROM graph_nodes n "  # nosec B608
            f"WHERE {where} LIMIT ?",
            [*params, limit],
        ).fetchall()

        results = []
        for row in rows:
            d = self._graph_node_from_row(dict(row))
            d["_score"] = rowid_ranks.get(d.get("node_rowid", 0), 0)
            results.append(d)

        results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        return results

    async def update_node(
        self, node_id: str, updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply partial updates to a graph node."""
        conn = self._get_conn()
        sets: list[str] = []
        params: list[Any] = []

        for field in ("name", "slug", "entity_type", "primary_space_id",
                       "resource_id", "manifest_resource_id",
                       "mention_count", "last_mentioned_at"):
            if field in updates:
                sets.append(f"{field} = ?")
                val = updates[field]
                if field in ("primary_space_id", "resource_id", "manifest_resource_id") and val is not None:
                    val = str(val)
                elif field == "last_mentioned_at" and val is not None and not isinstance(val, str):
                    val = val.isoformat()
                params.append(val)
        if "properties" in updates:
            sets.append("properties = ?")
            params.append(json.dumps(updates["properties"]))
        if "tags" in updates:
            sets.append("tags = ?")
            params.append(json.dumps(updates["tags"]))

        sets.append("updated_at = ?")
        params.append(datetime.now(tz=UTC).isoformat())
        params.append(str(node_id))

        conn.execute(
            f"UPDATE graph_nodes SET {', '.join(sets)} WHERE id = ?",  # nosec B608
            params,
        )
        conn.commit()

        result = await self.get_node(str(node_id))
        if result is None:
            raise StorageError(f"Graph node {node_id} not found after update")
        return result

    async def delete_node(self, node_id: str) -> None:
        """Delete a graph node (cascades edges, mentions, spaces)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (str(node_id),))
        conn.commit()

    async def store_edge(self, edge: dict[str, Any]) -> str:
        """Persist a graph edge."""
        conn = self._get_conn()
        now = datetime.now(tz=UTC).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO graph_edges (
                id, tenant_id, source_node_id, target_node_id,
                relation_type, properties, weight, bidirectional,
                source_resource_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(edge["id"]), str(edge["tenant_id"]),
                str(edge["source_node_id"]), str(edge["target_node_id"]),
                edge["relation_type"], json.dumps(edge.get("properties", {})),
                edge.get("weight", 0.5), 1 if edge.get("bidirectional") else 0,
                str(edge["source_resource_id"]) if edge.get("source_resource_id") else None,
                edge.get("created_at", now) if isinstance(edge.get("created_at"), str) else (edge["created_at"].isoformat() if edge.get("created_at") else now),
                edge.get("updated_at", now) if isinstance(edge.get("updated_at"), str) else (edge["updated_at"].isoformat() if edge.get("updated_at") else now),
            ),
        )
        conn.commit()
        return str(edge["id"])

    async def get_edges(
        self, node_id: str, direction: str,
    ) -> list[dict[str, Any]]:
        """Get edges connected to a node."""
        conn = self._get_conn()
        nid = str(node_id)
        if direction == "outgoing":
            rows = conn.execute(
                "SELECT * FROM graph_edges WHERE source_node_id = ?", (nid,),
            ).fetchall()
        elif direction == "incoming":
            rows = conn.execute(
                "SELECT * FROM graph_edges WHERE target_node_id = ?", (nid,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM graph_edges WHERE source_node_id = ? OR target_node_id = ?",
                (nid, nid),
            ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("properties"), str):
                d["properties"] = json.loads(d["properties"])
            d["bidirectional"] = bool(d.get("bidirectional", 0))
            results.append(d)
        return results

    async def update_edge(
        self, edge_id: str, updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply partial updates to a graph edge."""
        conn = self._get_conn()
        sets: list[str] = []
        params: list[Any] = []

        if "relation_type" in updates:
            sets.append("relation_type = ?")
            params.append(updates["relation_type"])
        if "weight" in updates:
            sets.append("weight = ?")
            params.append(updates["weight"])
        if "bidirectional" in updates:
            sets.append("bidirectional = ?")
            params.append(1 if updates["bidirectional"] else 0)
        if "properties" in updates:
            sets.append("properties = ?")
            params.append(json.dumps(updates["properties"]))

        sets.append("updated_at = ?")
        params.append(datetime.now(tz=UTC).isoformat())
        params.append(str(edge_id))

        conn.execute(
            f"UPDATE graph_edges SET {', '.join(sets)} WHERE id = ?",  # nosec B608
            params,
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM graph_edges WHERE id = ?", (str(edge_id),),
        ).fetchone()
        if row is None:
            raise StorageError(f"Graph edge {edge_id} not found after update")
        d = dict(row)
        if isinstance(d.get("properties"), str):
            d["properties"] = json.loads(d["properties"])
        d["bidirectional"] = bool(d.get("bidirectional", 0))
        return d

    async def delete_edge(self, edge_id: str) -> None:
        """Delete a graph edge."""
        conn = self._get_conn()
        conn.execute("DELETE FROM graph_edges WHERE id = ?", (str(edge_id),))
        conn.commit()

    async def neighbors(
        self, node_id: str, depth: int,
        relation_types: list[str] | None, space_id: str | None,
    ) -> list[dict[str, Any]]:
        """N-hop neighbor traversal via Python BFS."""
        conn = self._get_conn()
        nid = str(node_id)
        visited: set[str] = {nid}
        results: list[dict[str, Any]] = []
        frontier = [nid]

        for current_depth in range(1, depth + 1):
            next_frontier: list[str] = []
            for fnode in frontier:
                conditions = ["source_node_id = ?"]
                params: list[Any] = [fnode]
                if relation_types:
                    placeholders = ",".join("?" for _ in relation_types)
                    conditions.append(f"relation_type IN ({placeholders})")
                    params.extend(relation_types)

                where = " AND ".join(conditions)
                edges = conn.execute(
                    f"SELECT * FROM graph_edges WHERE {where}",  # nosec B608
                    params,
                ).fetchall()

                for edge in edges:
                    target = edge["target_node_id"]
                    if target in visited:
                        continue

                    node_row = conn.execute(
                        "SELECT * FROM graph_nodes WHERE id = ?", (target,),
                    ).fetchone()
                    if node_row is None:
                        continue

                    if space_id:
                        in_space = (
                            node_row["primary_space_id"] == str(space_id)
                            or conn.execute(
                                "SELECT 1 FROM graph_node_spaces WHERE node_id = ? AND space_id = ?",
                                (target, str(space_id)),
                            ).fetchone() is not None
                        )
                        if not in_space:
                            continue

                    visited.add(target)
                    next_frontier.append(target)
                    results.append({
                        "node_id": target,
                        "node_name": node_row["name"],
                        "entity_type": node_row["entity_type"],
                        "depth": current_depth,
                        "path": [],
                        "relation_type": edge["relation_type"],
                        "edge_weight": edge["weight"],
                    })
            frontier = next_frontier

        return results

    async def upsert_mention(
        self, node_id: str, resource_id: str,
        space_id: str | None, context_snippet: str,
    ) -> None:
        """Track entity mention in a resource (upsert)."""
        import uuid
        conn = self._get_conn()
        nid = str(node_id)
        rid = str(resource_id)
        now = datetime.now(tz=UTC).isoformat()
        snippet = context_snippet[:500]

        existing = conn.execute(
            "SELECT id FROM graph_mentions WHERE node_id = ? AND resource_id = ?",
            (nid, rid),
        ).fetchone()
        is_new = existing is None

        conn.execute(
            """INSERT OR REPLACE INTO graph_mentions
                   (id, node_id, resource_id, space_id, context_snippet, mentioned_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                existing["id"] if existing else str(uuid.uuid4()),
                nid, rid, str(space_id) if space_id else None, snippet, now,
            ),
        )

        if is_new:
            conn.execute(
                "UPDATE graph_nodes SET mention_count = mention_count + 1, "
                "last_mentioned_at = ? WHERE id = ?",
                (now, nid),
            )
        else:
            conn.execute(
                "UPDATE graph_nodes SET last_mentioned_at = ? WHERE id = ?",
                (now, nid),
            )
        conn.commit()

    async def get_backlinks(
        self, node_id: str, limit: int, offset: int,
    ) -> list[dict[str, Any]]:
        """Get all resources that mention an entity."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM graph_mentions WHERE node_id = ? "
            "ORDER BY mentioned_at DESC LIMIT ? OFFSET ?",
            (str(node_id), limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    async def get_entities_for_resource(
        self, resource_id: str,
    ) -> list[dict[str, Any]]:
        """Get all entities mentioned in a vault resource."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT n.* FROM graph_nodes n "
            "JOIN graph_mentions m ON m.node_id = n.id "
            "WHERE m.resource_id = ? ORDER BY n.name",
            (str(resource_id),),
        ).fetchall()
        return [self._graph_node_from_row(dict(r)) for r in rows]

    async def add_node_to_space(self, node_id: str, space_id: str) -> None:
        """Add cross-space membership."""
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO graph_node_spaces (node_id, space_id) VALUES (?, ?)",
                (str(node_id), str(space_id)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass

    async def remove_node_from_space(self, node_id: str, space_id: str) -> None:
        """Remove cross-space membership."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM graph_node_spaces WHERE node_id = ? AND space_id = ?",
            (str(node_id), str(space_id)),
        )
        conn.commit()

    async def merge_nodes(
        self, keep_id: str, merge_id: str,
    ) -> dict[str, Any]:
        """Merge two nodes: re-point edges, mentions, spaces; delete merge_id."""
        conn = self._get_conn()
        kid = str(keep_id)
        mid = str(merge_id)

        keep = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (kid,)).fetchone()
        merge = conn.execute("SELECT * FROM graph_nodes WHERE id = ?", (mid,)).fetchone()
        if keep is None or merge is None:
            raise StorageError("Both nodes must exist for merge")

        edges_to_repoint = conn.execute(
            "SELECT * FROM graph_edges WHERE source_node_id = ?", (mid,),
        ).fetchall()
        for e in edges_to_repoint:
            conflict = conn.execute(
                "SELECT 1 FROM graph_edges WHERE source_node_id = ? AND target_node_id = ? AND relation_type = ?",
                (kid, e["target_node_id"], e["relation_type"]),
            ).fetchone()
            if not conflict:
                conn.execute(
                    "UPDATE graph_edges SET source_node_id = ? WHERE id = ?",
                    (kid, e["id"]),
                )

        edges_to_repoint = conn.execute(
            "SELECT * FROM graph_edges WHERE target_node_id = ?", (mid,),
        ).fetchall()
        for e in edges_to_repoint:
            conflict = conn.execute(
                "SELECT 1 FROM graph_edges WHERE source_node_id = ? AND target_node_id = ? AND relation_type = ?",
                (e["source_node_id"], kid, e["relation_type"]),
            ).fetchone()
            if not conflict:
                conn.execute(
                    "UPDATE graph_edges SET target_node_id = ? WHERE id = ?",
                    (kid, e["id"]),
                )

        mentions_to_repoint = conn.execute(
            "SELECT * FROM graph_mentions WHERE node_id = ?", (mid,),
        ).fetchall()
        for m in mentions_to_repoint:
            conflict = conn.execute(
                "SELECT 1 FROM graph_mentions WHERE node_id = ? AND resource_id = ?",
                (kid, m["resource_id"]),
            ).fetchone()
            if not conflict:
                conn.execute(
                    "UPDATE graph_mentions SET node_id = ? WHERE id = ?",
                    (kid, m["id"]),
                )

        spaces = conn.execute(
            "SELECT space_id FROM graph_node_spaces WHERE node_id = ?", (mid,),
        ).fetchall()
        for s in spaces:
            try:
                conn.execute(
                    "INSERT INTO graph_node_spaces (node_id, space_id) VALUES (?, ?)",
                    (kid, s["space_id"]),
                )
            except sqlite3.IntegrityError:
                pass

        keep_props = json.loads(keep["properties"]) if isinstance(keep["properties"], str) else (keep["properties"] or {})
        merge_props = json.loads(merge["properties"]) if isinstance(merge["properties"], str) else (merge["properties"] or {})
        merged_props = {**merge_props, **keep_props}
        keep_tags = json.loads(keep["tags"]) if isinstance(keep["tags"], str) else (keep["tags"] or [])
        merge_tags = json.loads(merge["tags"]) if isinstance(merge["tags"], str) else (merge["tags"] or [])
        merged_tags = list(set(keep_tags + merge_tags))
        merged_count = (keep["mention_count"] or 0) + (merge["mention_count"] or 0)

        conn.execute(
            "UPDATE graph_nodes SET properties = ?, tags = ?, "
            "mention_count = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged_props), json.dumps(merged_tags),
             merged_count, datetime.now(tz=UTC).isoformat(), kid),
        )
        conn.execute("DELETE FROM graph_nodes WHERE id = ?", (mid,))
        conn.commit()

        result = await self.get_node(kid)
        if result is None:
            raise StorageError(f"Graph node {keep_id} not found after merge")
        return result

    async def store_scan_job(self, job: dict[str, Any]) -> str:
        """Persist a scan job record."""
        conn = self._get_conn()
        now = datetime.now(tz=UTC).isoformat()
        started = job.get("started_at", now)
        if not isinstance(started, str):
            started = started.isoformat()
        finished = job.get("finished_at")
        if finished and not isinstance(finished, str):
            finished = finished.isoformat()

        conn.execute(
            """INSERT INTO graph_scan_jobs
                   (id, tenant_id, space_id, status, started_at, finished_at, summary_json, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(job["id"]), str(job["tenant_id"]), str(job["space_id"]),
                job.get("status", "running"), started, finished,
                json.dumps(job["summary"]) if job.get("summary") else None,
                job.get("error"),
            ),
        )
        conn.commit()
        return str(job["id"])

    async def get_scan_job(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve a scan job by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM graph_scan_jobs WHERE id = ?", (str(job_id),),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if isinstance(d.get("summary_json"), str):
            d["summary"] = json.loads(d["summary_json"])
        else:
            d["summary"] = None
        return d

    async def list_scan_jobs(
        self, filters: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int]:
        """List scan jobs with optional filtering."""
        conn = self._get_conn()
        conditions: list[str] = []
        params: list[Any] = []

        if filters.get("space_id"):
            conditions.append("space_id = ?")
            params.append(str(filters["space_id"]))
        if filters.get("status"):
            conditions.append("status = ?")
            params.append(filters["status"])

        where = " AND ".join(conditions) if conditions else "1=1"
        limit = filters.get("limit", 50)
        offset = filters.get("offset", 0)

        total_row = conn.execute(
            f"SELECT COUNT(*) FROM graph_scan_jobs WHERE {where}",  # nosec B608
            params,
        ).fetchone()
        total = total_row[0] if total_row else 0

        rows = conn.execute(
            f"SELECT * FROM graph_scan_jobs WHERE {where} "  # nosec B608
            f"ORDER BY started_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("summary_json"), str):
                d["summary"] = json.loads(d["summary_json"])
            else:
                d["summary"] = None
            results.append(d)
        return results, total

    async def update_scan_job(
        self, job_id: str, updates: dict[str, Any],
    ) -> None:
        """Update a scan job's fields."""
        conn = self._get_conn()
        sets: list[str] = []
        params: list[Any] = []

        for field in ("status", "error"):
            if field in updates:
                sets.append(f"{field} = ?")
                params.append(updates[field])
        if "finished_at" in updates:
            sets.append("finished_at = ?")
            val = updates["finished_at"]
            params.append(val.isoformat() if val and not isinstance(val, str) else val)
        if "summary" in updates:
            sets.append("summary_json = ?")
            params.append(json.dumps(updates["summary"]) if updates["summary"] else None)

        if not sets:
            return

        params.append(str(job_id))
        conn.execute(
            f"UPDATE graph_scan_jobs SET {', '.join(sets)} WHERE id = ?",  # nosec B608
            params,
        )
        conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

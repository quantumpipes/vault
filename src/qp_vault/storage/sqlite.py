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

    async def initialize(self) -> None:
        """Create tables and indexes."""
        import contextlib

        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        with contextlib.suppress(sqlite3.OperationalError):
            conn.executescript(_FTS_SCHEMA)
        conn.commit()

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

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

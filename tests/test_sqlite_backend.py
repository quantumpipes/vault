"""Tests for SQLite storage backend."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qp_vault.enums import ResourceStatus, TrustTier
from qp_vault.models import Chunk, Resource
from qp_vault.protocols import ResourceFilter, ResourceUpdate, SearchQuery
from qp_vault.storage.sqlite import SQLiteBackend


@pytest.fixture
def backend(tmp_path):
    return SQLiteBackend(tmp_path / "test.db")


def _make_resource(id: str = "r-1", name: str = "test.md", trust: str = "working") -> Resource:
    now = datetime.now(tz=UTC)
    return Resource(
        id=id,
        name=name,
        content_hash="abc123",
        cid=f"vault://sha3-256/abc123_{id}",
        trust_tier=TrustTier(trust),
        status=ResourceStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


def _make_chunk(
    id: str = "c-1",
    resource_id: str = "r-1",
    content: str = "test content",
    embedding: list[float] | None = None,
) -> Chunk:
    return Chunk(
        id=id,
        resource_id=resource_id,
        content=content,
        cid=f"vault://sha3-256/chunk_{id}",
        embedding=embedding,
        chunk_index=0,
        token_count=2,
    )


class TestSQLiteInit:
    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, backend):
        await backend.initialize()
        conn = backend._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "resources" in table_names
        assert "chunks" in table_names
        assert "collections" in table_names
        assert "vault_meta" in table_names

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, backend):
        await backend.initialize()
        await backend.initialize()  # Should not raise


class TestSQLiteResourceCRUD:
    @pytest.mark.asyncio
    async def test_store_and_get(self, backend):
        await backend.initialize()
        r = _make_resource()
        await backend.store_resource(r)
        fetched = await backend.get_resource("r-1")
        assert fetched is not None
        assert fetched.id == "r-1"
        assert fetched.name == "test.md"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, backend):
        await backend.initialize()
        result = await backend.get_resource("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_resources(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource("r-1"))
        await backend.store_resource(_make_resource("r-2", "other.md"))
        resources = await backend.list_resources(ResourceFilter())
        assert len(resources) == 2

    @pytest.mark.asyncio
    async def test_list_with_trust_filter(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource("r-1", trust="canonical"))
        await backend.store_resource(_make_resource("r-2", trust="working"))
        resources = await backend.list_resources(ResourceFilter(trust_tier="canonical"))
        assert len(resources) == 1
        assert resources[0].trust_tier == TrustTier.CANONICAL

    @pytest.mark.asyncio
    async def test_update_resource(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource())
        updated = await backend.update_resource("r-1", ResourceUpdate(name="renamed.md"))
        assert updated.name == "renamed.md"

    @pytest.mark.asyncio
    async def test_soft_delete(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource())
        await backend.delete_resource("r-1")
        # Should still exist in DB with deleted status
        r = await backend.get_resource("r-1")
        assert r is not None
        assert r.status == ResourceStatus.DELETED

    @pytest.mark.asyncio
    async def test_hard_delete(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource())
        await backend.delete_resource("r-1", hard=True)
        r = await backend.get_resource("r-1")
        assert r is None


class TestSQLiteChunks:
    @pytest.mark.asyncio
    async def test_store_and_retrieve_chunks(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource())
        chunks = [
            _make_chunk("c-1", "r-1", "first chunk"),
            _make_chunk("c-2", "r-1", "second chunk"),
        ]
        await backend.store_chunks("r-1", chunks)
        retrieved = await backend.get_chunks_for_resource("r-1")
        assert len(retrieved) == 2

    @pytest.mark.asyncio
    async def test_store_chunks_updates_resource_status(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource())
        await backend.store_chunks("r-1", [_make_chunk()])
        r = await backend.get_resource("r-1")
        assert r.status == ResourceStatus.INDEXED

    @pytest.mark.asyncio
    async def test_store_chunks_with_embedding(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource())
        chunk = _make_chunk(embedding=[0.1, 0.2, 0.3])
        await backend.store_chunks("r-1", [chunk])
        retrieved = await backend.get_chunks_for_resource("r-1")
        assert retrieved[0].embedding == [0.1, 0.2, 0.3]


class TestSQLiteSearch:
    @pytest.mark.asyncio
    async def test_fts_search(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource("r-1", "incident.md"))
        await backend.store_chunks("r-1", [
            _make_chunk("c-1", "r-1", "Incident response procedure for critical outages"),
        ])
        results = await backend.search(SearchQuery(query_text="incident response"))
        assert len(results) > 0
        assert "incident" in results[0].content.lower()

    @pytest.mark.asyncio
    async def test_vector_search(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource("r-1", "doc.md"))
        await backend.store_chunks("r-1", [
            _make_chunk("c-1", "r-1", "some content", embedding=[1.0, 0.0, 0.0]),
        ])
        results = await backend.search(SearchQuery(
            query_embedding=[1.0, 0.0, 0.0],
            query_text="",
            top_k=10,
        ))
        assert len(results) > 0
        assert results[0].vector_similarity > 0.99


class TestSQLiteHashes:
    @pytest.mark.asyncio
    async def test_get_all_hashes(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource("r-1"))
        await backend.store_resource(_make_resource("r-2", "other.md"))
        hashes = await backend.get_all_hashes()
        assert len(hashes) == 2
        assert all(isinstance(h, tuple) and len(h) == 2 for h in hashes)

    @pytest.mark.asyncio
    async def test_hashes_exclude_deleted(self, backend):
        await backend.initialize()
        await backend.store_resource(_make_resource("r-1"))
        await backend.delete_resource("r-1")
        hashes = await backend.get_all_hashes()
        assert len(hashes) == 0

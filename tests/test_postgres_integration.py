"""PostgreSQL integration tests. Requires running PostgreSQL with pgvector.

Run with: VAULT_TEST_POSTGRES_DSN=postgresql://... pytest tests/test_postgres_integration.py

Skipped automatically if DSN env var is not set (local dev without Docker).
"""

from __future__ import annotations

import os

import pytest

DSN = os.environ.get("VAULT_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="VAULT_TEST_POSTGRES_DSN not set")



@pytest.fixture
async def backend():
    """Create a fresh PostgreSQL backend for each test."""
    from qp_vault.storage.postgres import PostgresBackend

    # Use sslmode=disable for local Docker testing
    dsn = DSN if "sslmode" in DSN else f"{DSN}?sslmode=disable"
    b = PostgresBackend(dsn, ssl=False)
    await b.initialize()

    # Clean tables before each test
    pool = await b._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qp_vault.chunks")
        await conn.execute("DELETE FROM qp_vault.provenance")
        await conn.execute("DELETE FROM qp_vault.collections")
        await conn.execute("DELETE FROM qp_vault.resources")

    yield b
    await b.close()


def _make_resource(
    resource_id: str = "r-1",
    name: str = "test.md",
    trust_tier: str = "working",
    tenant_id: str | None = None,
):
    """Create a Resource for testing."""
    from datetime import UTC, datetime

    from qp_vault.models import Resource

    return Resource(
        id=resource_id,
        name=name,
        content_hash="abc123",
        cid="vault://sha3-256/abc123",
        trust_tier=trust_tier,
        data_classification="internal",
        resource_type="document",
        status="indexed",
        lifecycle="active",
        chunk_count=1,
        size_bytes=100,
        tenant_id=tenant_id,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


def _make_chunk(resource_id: str = "r-1", index: int = 0):
    """Create a Chunk for testing."""
    from qp_vault.models import Chunk

    return Chunk(
        id=f"c-{resource_id}-{index}",
        resource_id=resource_id,
        content=f"Test chunk content {index}",
        cid=f"vault://sha3-256/chunk{index}",
        chunk_index=index,
        token_count=10,
    )


class TestPostgresStoreAndGet:
    @pytest.mark.asyncio
    async def test_store_and_get_resource(self, backend) -> None:
        r = _make_resource("r-1", "doc.md")
        rid = await backend.store_resource(r)
        assert rid == "r-1"

        fetched = await backend.get_resource("r-1")
        assert fetched is not None
        assert fetched.name == "doc.md"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, backend) -> None:
        result = await backend.get_resource("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_resources_batch(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1", "a.md"))
        await backend.store_resource(_make_resource("r-2", "b.md"))
        results = await backend.get_resources(["r-1", "r-2", "r-3"])
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_resources_empty(self, backend) -> None:
        results = await backend.get_resources([])
        assert results == []


class TestPostgresList:
    @pytest.mark.asyncio
    async def test_list_all(self, backend) -> None:
        from qp_vault.protocols import ResourceFilter

        await backend.store_resource(_make_resource("r-1"))
        await backend.store_resource(_make_resource("r-2", "b.md"))
        results = await backend.list_resources(ResourceFilter())
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_by_trust(self, backend) -> None:
        from qp_vault.protocols import ResourceFilter

        await backend.store_resource(_make_resource("r-1", trust_tier="canonical"))
        await backend.store_resource(_make_resource("r-2", trust_tier="working"))
        results = await backend.list_resources(ResourceFilter(trust_tier="canonical"))
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, backend) -> None:
        from qp_vault.protocols import ResourceFilter

        await backend.store_resource(_make_resource("r-1", tenant_id="t1"))
        await backend.store_resource(_make_resource("r-2", tenant_id="t2"))
        results = await backend.list_resources(ResourceFilter(tenant_id="t1"))
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, backend) -> None:
        from qp_vault.protocols import ResourceFilter

        for i in range(5):
            await backend.store_resource(_make_resource(f"r-{i}", f"d{i}.md"))
        results = await backend.list_resources(ResourceFilter(limit=2, offset=0))
        assert len(results) == 2


class TestPostgresUpdate:
    @pytest.mark.asyncio
    async def test_update_trust(self, backend) -> None:
        from qp_vault.protocols import ResourceUpdate

        await backend.store_resource(_make_resource("r-1", trust_tier="working"))
        updated = await backend.update_resource("r-1", ResourceUpdate(trust_tier="canonical"))
        assert updated.trust_tier.value == "canonical"

    @pytest.mark.asyncio
    async def test_update_name(self, backend) -> None:
        from qp_vault.protocols import ResourceUpdate

        await backend.store_resource(_make_resource("r-1", "old.md"))
        updated = await backend.update_resource("r-1", ResourceUpdate(name="new.md"))
        assert updated.name == "new.md"


class TestPostgresDelete:
    @pytest.mark.asyncio
    async def test_soft_delete(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1"))
        await backend.delete_resource("r-1", hard=False)
        fetched = await backend.get_resource("r-1")
        assert fetched is not None
        assert fetched.status.value == "deleted"

    @pytest.mark.asyncio
    async def test_hard_delete(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1"))
        await backend.delete_resource("r-1", hard=True)
        fetched = await backend.get_resource("r-1")
        assert fetched is None

    @pytest.mark.asyncio
    async def test_restore(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1"))
        await backend.delete_resource("r-1", hard=False)
        restored = await backend.restore_resource("r-1")
        assert restored.status.value == "indexed"


class TestPostgresChunks:
    @pytest.mark.asyncio
    async def test_store_and_get_chunks(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1"))
        chunks = [_make_chunk("r-1", 0), _make_chunk("r-1", 1)]
        await backend.store_chunks("r-1", chunks)
        fetched = await backend.get_chunks_for_resource("r-1")
        assert len(fetched) == 2

    @pytest.mark.asyncio
    async def test_get_all_hashes(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1"))
        hashes = await backend.get_all_hashes()
        assert len(hashes) >= 1
        assert hashes[0][0] == "r-1"


class TestPostgresSearch:
    @pytest.mark.asyncio
    async def test_text_search(self, backend) -> None:
        from qp_vault.protocols import SearchQuery

        await backend.store_resource(_make_resource("r-1", "searchable.md"))
        chunks = [_make_chunk("r-1", 0)]
        chunks[0].content = "PostgreSQL integration test content"
        await backend.store_chunks("r-1", chunks)

        results = await backend.search(SearchQuery(query_text="integration"))
        assert isinstance(results, list)


class TestPostgresProvenance:
    @pytest.mark.asyncio
    async def test_store_and_get_provenance(self, backend) -> None:
        from datetime import UTC, datetime

        await backend.store_resource(_make_resource("r-1"))
        await backend.store_provenance(
            provenance_id="p-1",
            resource_id="r-1",
            uploader_id="user-1",
            upload_method="api",
            source_description="test upload",
            original_hash="abc123",
            signature=None,
            verified=False,
            created_at=datetime.now(tz=UTC).isoformat(),
        )
        records = await backend.get_provenance("r-1")
        assert len(records) == 1
        assert records[0]["uploader_id"] == "user-1"


class TestPostgresCollections:
    @pytest.mark.asyncio
    async def test_store_and_list_collections(self, backend) -> None:
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC).isoformat()
        await backend.store_collection("c-1", "Engineering", "Eng docs", now)
        await backend.store_collection("c-2", "Legal", "Legal docs", now)
        colls = await backend.list_collections()
        assert len(colls) == 2
        names = [c["name"] for c in colls]
        assert "Engineering" in names


class TestPostgresCount:
    @pytest.mark.asyncio
    async def test_count_resources(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1", tenant_id="t1"))
        await backend.store_resource(_make_resource("r-2", "b.md", tenant_id="t1"))
        count = await backend.count_resources("t1")
        assert count == 2

    @pytest.mark.asyncio
    async def test_count_excludes_deleted(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1", tenant_id="t1"))
        await backend.delete_resource("r-1", hard=False)
        count = await backend.count_resources("t1")
        assert count == 0


class TestPostgresFindByCid:
    @pytest.mark.asyncio
    async def test_find_existing(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1"))
        result = await backend.find_by_cid("vault://sha3-256/abc123")
        assert result is not None
        assert result.id == "r-1"

    @pytest.mark.asyncio
    async def test_find_nonexistent(self, backend) -> None:
        result = await backend.find_by_cid("vault://sha3-256/nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_scoped_by_tenant(self, backend) -> None:
        await backend.store_resource(_make_resource("r-1", tenant_id="t1"))
        result = await backend.find_by_cid("vault://sha3-256/abc123", tenant_id="t2")
        assert result is None  # Wrong tenant

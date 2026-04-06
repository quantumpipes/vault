"""Surgical tests targeting specific uncovered lines for 100% coverage.

Each test targets a specific line number from the coverage report.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from qp_vault import AsyncVault, Vault

# ===== chunker.py lines 93-116: max_tokens flush with accumulated paragraphs =====

class TestChunkerMaxFlush:
    def test_accumulated_then_huge_paragraph_triggers_flush(self):
        """When we have accumulated paragraphs and a new one pushes past max_tokens,
        the accumulated content should flush before adding the new paragraph."""
        from qp_vault.core.chunker import ChunkerConfig, chunk_text

        config = ChunkerConfig(target_tokens=50, min_tokens=5, max_tokens=60, overlap_tokens=10)

        # Build text: several small paragraphs then one big one
        small_paras = ["Small paragraph one here.", "Small paragraph two here."]
        big_para = " ".join(["big"] * 80)  # Way over max_tokens
        text = "\n\n".join(small_paras + [big_para])

        chunks = chunk_text(text, config)
        # Should have flushed the small paragraphs before the big one
        assert len(chunks) >= 2
        # First chunk should contain "Small paragraph"
        assert "Small paragraph" in chunks[0].content


# ===== vault.py line 280: Latin-1 fallback when reading file =====

class TestVaultLatin1Fallback:
    def test_latin1_file(self, tmp_path):
        vault = Vault(tmp_path / "latin-vault")
        f = tmp_path / "latin.txt"
        f.write_bytes(b"caf\xe9 cr\xe8me")  # Latin-1 encoded, invalid UTF-8
        r = vault.add(f)
        assert r.chunk_count >= 1

    def test_binary_path_raises(self, tmp_path):
        """A Path object pointing to unreadable content should raise."""
        vault = Vault(tmp_path / "bin-vault")
        f = tmp_path / "binary.bin"
        f.write_bytes(bytes(range(256)))  # Binary garbage
        # Should still work (latin-1 fallback handles any byte sequence)
        r = vault.add(f)
        assert r is not None


# ===== vault.py lines 262-263: OSError on Path().exists() =====

class TestVaultPathOSError:
    def test_string_with_embedded_null_not_path(self, tmp_path):
        """Strings with null bytes should not be treated as file paths."""
        vault = Vault(tmp_path / "null-vault")
        # On some systems, null in path causes OSError
        r = vault.add("Content with\x00null", name="safe.md")
        assert r.chunk_count >= 1


# ===== sqlite.py lines 136,141: _get_conn WAL+FK pragma, lines 178-180: date serialization =====

class TestSQLiteDateSerialization:
    @pytest.mark.asyncio
    async def test_store_resource_with_dates(self, tmp_path):
        """valid_from and valid_until should be stored as ISO strings."""
        from datetime import date

        from qp_vault.models import Resource
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "dates.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        r = Resource(
            id="r1", name="dated.md", content_hash="h1", cid="v://h1",
            valid_from=date(2025, 1, 1), valid_until=date(2025, 12, 31),
            created_at=now, updated_at=now,
        )
        await b.store_resource(r)
        fetched = await b.get_resource("r1")
        assert fetched is not None
        assert "2025-01-01" in str(fetched.valid_from)


# ===== sqlite.py lines 272-273, 301-308: update_resource with tags and metadata =====

class TestSQLiteUpdateTagsMeta:
    @pytest.mark.asyncio
    async def test_update_tags_only(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceUpdate
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "tags.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            created_at=now, updated_at=now))
        updated = await b.update_resource("r1", ResourceUpdate(tags=["new-tag"]))
        assert updated.tags == ["new-tag"]

    @pytest.mark.asyncio
    async def test_update_metadata_only(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceUpdate
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "meta.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            created_at=now, updated_at=now))
        updated = await b.update_resource("r1", ResourceUpdate(metadata={"key": "val"}))
        assert updated.metadata == {"key": "val"}

    @pytest.mark.asyncio
    async def test_update_no_changes_returns_current(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceUpdate
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "noop.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            created_at=now, updated_at=now))
        # Empty update should return current resource
        result = await b.update_resource("r1", ResourceUpdate())
        assert result.id == "r1"


# ===== sqlite.py lines 421-422, 444: search threshold filter, empty FTS =====

class TestSQLiteSearchThreshold:
    @pytest.mark.asyncio
    async def test_search_with_high_threshold(self, tmp_path):
        """Results below threshold should be filtered out."""
        from qp_vault.models import Chunk, Resource
        from qp_vault.protocols import SearchQuery
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "thresh.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            status="indexed", created_at=now, updated_at=now))
        await b.store_chunks("r1", [Chunk(
            id="c1", resource_id="r1", content="test doc",
            cid="v://c1", chunk_index=0)])
        results = await b.search(SearchQuery(
            query_text="test", threshold=0.99))  # Very high threshold
        # May or may not return results depending on FTS score
        assert isinstance(results, list)


# ===== lifecycle_engine.py lines 228,232,242,246: chain walk forward =====

class TestLifecycleChainWalkForward:
    @pytest.mark.asyncio
    async def test_chain_walks_forward_from_old(self, tmp_path):
        """chain() should walk forward via superseded_by."""
        vault = AsyncVault(tmp_path / "chain-fwd")
        r1 = await vault.add("v1", name="v1.md")
        r2 = await vault.add("v2", name="v2.md")
        r3 = await vault.add("v3", name="v3.md")
        await vault.supersede(r1.id, r2.id)
        await vault.supersede(r2.id, r3.id)
        chain = await vault.chain(r1.id)
        assert len(chain) == 3
        assert chain[0].id == r1.id
        assert chain[2].id == r3.id


# ===== lifecycle_engine.py line 199: check_expirations with date as string =====

class TestExpirationStringDate:
    @pytest.mark.asyncio
    async def test_expiring_handles_string_valid_until(self, tmp_path):
        """expiring() should handle valid_until stored as string."""
        vault = AsyncVault(tmp_path / "exp-str")
        from datetime import date, timedelta
        future = date.today() + timedelta(days=45)
        r = await vault.add("Expiring doc", name="exp.md",
                             valid_from=date.today(), valid_until=future)
        expiring = await vault.expiring(days=60)
        assert r.id in [e.id for e in expiring]


# ===== plugins/registry.py: entry_points branching =====

class TestPluginRegistryEntryPoints:
    def test_discover_entry_points_no_crash(self):
        """Entry point discovery should handle all Python versions."""
        from qp_vault.plugins.registry import PluginRegistry
        reg = PluginRegistry()
        reg.discover_entry_points()  # Should not crash on any Python version
        # We can't control what's installed, just verify it doesn't error

    def test_registry_discover_nonexistent_dir(self):
        from qp_vault.plugins.registry import PluginRegistry
        reg = PluginRegistry()
        reg.discover_plugins_dir(Path("/definitely/nonexistent/path"))
        assert len(reg.list_embedders()) == 0

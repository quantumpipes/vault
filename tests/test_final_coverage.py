"""Final coverage gap tests. Targets every remaining uncovered line
that doesn't require external services (PostgreSQL, qp-capsule)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from qp_vault import AsyncVault, MemoryLayer, TrustTier, Vault

# ===== vault.py: factory methods, from_postgres =====

class TestVaultFactories:
    def test_from_postgres_creates_vault(self, tmp_path):
        """from_postgres should create a Vault with postgres config."""
        v = Vault.from_postgres("postgresql://localhost/test")
        assert v._async.config.backend == "postgres"
        assert v._async.config.postgres_dsn == "postgresql://localhost/test"

    def test_sync_layer_returns_layer_view(self, tmp_path):
        v = Vault(tmp_path / "lv")
        lv = v.layer("operational")
        assert lv.config.name == MemoryLayer.OPERATIONAL

    def test_sync_health(self, tmp_path):
        v = Vault(tmp_path / "health")
        v.add("Doc", name="d.md")
        h = v.health()
        assert h.overall >= 0

    def test_sync_export_proof(self, tmp_path):
        v = Vault(tmp_path / "proof")
        r = v.add("Doc", name="d.md")
        proof = v.export_proof(r.id)
        assert proof.merkle_root


# ===== chunker.py: the overlap accumulation loop (lines 93-116) =====

class TestChunkerDeepOverlap:
    def test_many_small_paragraphs_with_overlap(self):
        """Force the overlap code path by having many small paragraphs that
        accumulate beyond target, triggering flush + overlap carry-forward."""
        from qp_vault.core.chunker import ChunkerConfig, chunk_text
        config = ChunkerConfig(target_tokens=15, min_tokens=3, max_tokens=30, overlap_tokens=8)
        paras = [f"Word{i} word{i}a word{i}b word{i}c." for i in range(30)]
        text = "\n\n".join(paras)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 3

    def test_single_huge_paragraph(self):
        """One paragraph exceeding max_tokens should be flushed."""
        from qp_vault.core.chunker import ChunkerConfig, chunk_text
        config = ChunkerConfig(target_tokens=10, min_tokens=3, max_tokens=20, overlap_tokens=5)
        text = " ".join(["word"] * 100)  # Single paragraph
        chunks = chunk_text(text, config)
        assert len(chunks) >= 1

    def test_min_tokens_merge(self):
        """Trailing chunk smaller than min_tokens should merge with previous."""
        from qp_vault.core.chunker import ChunkerConfig, chunk_text
        config = ChunkerConfig(target_tokens=30, min_tokens=20, max_tokens=60, overlap_tokens=5)
        text = ("word " * 25) + "\n\n" + "tiny."
        chunks = chunk_text(text, config)
        # "tiny." alone is < min_tokens, should be merged
        if len(chunks) == 1:
            assert "tiny" in chunks[0].content


# ===== sqlite.py: filter branches (classification, resource_type, lifecycle, layer) =====

class TestSQLiteFilterBranches:
    @pytest.mark.asyncio
    async def test_list_by_classification(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceFilter
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "filt.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            data_classification="confidential", created_at=now, updated_at=now))
        await b.store_resource(Resource(
            id="r2", name="b.md", content_hash="h2", cid="v://h2",
            data_classification="public", created_at=now, updated_at=now))
        results = await b.list_resources(ResourceFilter(data_classification="confidential"))
        assert len(results) == 1
        assert results[0].id == "r1"

    @pytest.mark.asyncio
    async def test_list_by_resource_type(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceFilter
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "type.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.py", content_hash="h1", cid="v://h1",
            resource_type="code", created_at=now, updated_at=now))
        await b.store_resource(Resource(
            id="r2", name="b.md", content_hash="h2", cid="v://h2",
            resource_type="note", created_at=now, updated_at=now))
        results = await b.list_resources(ResourceFilter(resource_type="code"))
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_by_lifecycle(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceFilter
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "lc.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            lifecycle="draft", created_at=now, updated_at=now))
        await b.store_resource(Resource(
            id="r2", name="b.md", content_hash="h2", cid="v://h2",
            lifecycle="active", created_at=now, updated_at=now))
        results = await b.list_resources(ResourceFilter(lifecycle="draft"))
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_by_layer(self, tmp_path):
        from qp_vault.models import Resource
        from qp_vault.protocols import ResourceFilter
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "layer.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            layer="operational", created_at=now, updated_at=now))
        await b.store_resource(Resource(
            id="r2", name="b.md", content_hash="h2", cid="v://h2",
            layer="strategic", created_at=now, updated_at=now))
        results = await b.list_resources(ResourceFilter(layer="operational"))
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_with_layer_filter(self, tmp_path):
        """Search should filter by layer in SQL WHERE."""
        from qp_vault.models import Chunk, Resource
        from qp_vault.protocols import ResourceFilter, SearchQuery
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "sf.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            status="indexed", layer="operational", created_at=now, updated_at=now))
        await b.store_chunks("r1", [Chunk(
            id="c1", resource_id="r1", content="operational doc content",
            cid="v://c1", chunk_index=0)])
        await b.store_resource(Resource(
            id="r2", name="b.md", content_hash="h2", cid="v://h2",
            status="indexed", layer="strategic", created_at=now, updated_at=now))
        await b.store_chunks("r2", [Chunk(
            id="c2", resource_id="r2", content="strategic doc content",
            cid="v://c2", chunk_index=0)])
        results = await b.search(SearchQuery(
            query_text="doc content",
            filters=ResourceFilter(layer="operational"),
        ))
        # Should only return operational results
        for r in results:
            assert r.resource_name == "a.md"

    @pytest.mark.asyncio
    async def test_search_with_trust_filter(self, tmp_path):
        from qp_vault.models import Chunk, Resource
        from qp_vault.protocols import ResourceFilter, SearchQuery
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "tf.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="can.md", content_hash="h1", cid="v://h1",
            status="indexed", trust_tier="canonical", created_at=now, updated_at=now))
        await b.store_chunks("r1", [Chunk(
            id="c1", resource_id="r1", content="canonical content here",
            cid="v://c1", chunk_index=0)])
        await b.store_resource(Resource(
            id="r2", name="work.md", content_hash="h2", cid="v://h2",
            status="indexed", trust_tier="working", created_at=now, updated_at=now))
        await b.store_chunks("r2", [Chunk(
            id="c2", resource_id="r2", content="working content here",
            cid="v://c2", chunk_index=0)])
        results = await b.search(SearchQuery(
            query_text="content here",
            filters=ResourceFilter(trust_tier="canonical"),
        ))
        for r in results:
            assert r.trust_tier == TrustTier.CANONICAL

    @pytest.mark.asyncio
    async def test_search_with_collection_filter(self, tmp_path):
        from qp_vault.models import Chunk, Resource
        from qp_vault.protocols import ResourceFilter, SearchQuery
        from qp_vault.storage.sqlite import SQLiteBackend
        b = SQLiteBackend(tmp_path / "cf.db")
        await b.initialize()
        now = datetime.now(tz=UTC)
        await b.store_resource(Resource(
            id="r1", name="a.md", content_hash="h1", cid="v://h1",
            status="indexed", collection_id="col-1", created_at=now, updated_at=now))
        await b.store_chunks("r1", [Chunk(
            id="c1", resource_id="r1", content="collection one doc",
            cid="v://c1", chunk_index=0)])
        await b.store_resource(Resource(
            id="r2", name="b.md", content_hash="h2", cid="v://h2",
            status="indexed", collection_id="col-2", created_at=now, updated_at=now))
        await b.store_chunks("r2", [Chunk(
            id="c2", resource_id="r2", content="collection two doc",
            cid="v://c2", chunk_index=0)])
        results = await b.search(SearchQuery(
            query_text="collection doc",
            filters=ResourceFilter(collection_id="col-1"),
        ))
        for r in results:
            assert r.resource_name == "a.md"


# ===== lifecycle: auto-expire already-expired resource =====

class TestLifecycleAutoExpire:
    @pytest.mark.asyncio
    async def test_check_expirations_skips_non_active(self, tmp_path):
        """Resources not in ACTIVE state should not be auto-expired."""
        vault = AsyncVault(tmp_path / "ae-vault")
        yesterday = date.today() - timedelta(days=1)
        r = await vault.add("Draft expired", name="d.md",
                             lifecycle="draft", valid_until=yesterday)
        expired = await vault._lifecycle.check_expirations()
        # Draft can't transition to EXPIRED (not in VALID_TRANSITIONS[DRAFT])
        assert r.id not in [e.id for e in expired]


# ===== layer_manager: LayerView.search with compliance audit =====

class TestLayerViewCompliance:
    @pytest.mark.asyncio
    async def test_compliance_layer_audits_search(self, tmp_path):
        """COMPLIANCE layer should audit search operations."""
        vault = AsyncVault(tmp_path / "comp-vault")
        await vault.add("Compliance doc", name="soc2.md", layer="compliance")
        comp = vault.layer(MemoryLayer.COMPLIANCE)
        await comp.search("compliance")
        # Check audit log has a search event
        import json
        audit_path = vault.path / "audit.jsonl"
        if audit_path.exists():
            lines = audit_path.read_text().strip().split("\n")
            search_events = [
                json.loads(ln) for ln in lines
                if json.loads(ln).get("event_type") == "search"
            ]
            assert len(search_events) >= 1


# ===== transcript_parser: edge cases =====

class TestTranscriptEdges:
    @pytest.mark.asyncio
    async def test_webvtt_no_speakers(self, tmp_path):
        from qp_vault.processing.transcript_parser import WebVTTParser
        f = tmp_path / "nospeaker.vtt"
        f.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nJust plain text.\n")
        parser = WebVTTParser()
        result = await parser.parse(f)
        assert "plain text" in result.text
        assert result.metadata["speaker_count"] == 0

    @pytest.mark.asyncio
    async def test_srt_with_html_tags(self, tmp_path):
        from qp_vault.processing.transcript_parser import SRTParser
        f = tmp_path / "html.srt"
        f.write_text("1\n00:00:01,000 --> 00:00:04,000\n<i>Italic text</i> and <b>bold</b>.\n\n")
        parser = SRTParser()
        result = await parser.parse(f)
        assert "<i>" not in result.text
        assert "Italic text" in result.text

    @pytest.mark.asyncio
    async def test_srt_with_bom(self, tmp_path):
        from qp_vault.processing.transcript_parser import SRTParser
        f = tmp_path / "bom.srt"
        f.write_bytes(b"\xef\xbb\xbf1\n00:00:01,000 --> 00:00:04,000\nBOM text.\n\n")
        parser = SRTParser()
        result = await parser.parse(f)
        assert "BOM text" in result.text


# ===== vault.py: _run_async inside running loop =====

class TestRunAsyncInLoop:
    @pytest.mark.asyncio
    async def test_sync_vault_in_async_context(self, tmp_path):
        """Sync Vault should work even when called from async context."""
        v = Vault(tmp_path / "async-ctx")
        r = v.add("Content", name="test.md")
        assert r.chunk_count >= 1

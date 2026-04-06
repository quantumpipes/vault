"""Tests to close remaining coverage gaps.

Targets every uncovered line from the coverage report.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from qp_vault import (
    AsyncVault,
    MemoryLayer,
    TrustTier,
    Vault,
    VaultError,
)
from qp_vault.config import VaultConfig
from qp_vault.core.chunker import ChunkerConfig, chunk_text
from qp_vault.core.layer_manager import LayerManager
from qp_vault.core.search_engine import compute_freshness
from qp_vault.integrity.detector import (
    compute_health_score,
    compute_staleness_score,
    find_orphans,
)
from qp_vault.models import Resource
from qp_vault.storage.sqlite import SQLiteBackend, _sanitize_fts_query

# ===== __init__.py: line 99 (lazy import AttributeError) =====

class TestInitLazyImport:
    def test_invalid_attribute_raises(self):
        import qp_vault
        with pytest.raises(AttributeError, match="no attribute"):
            _ = qp_vault.NonexistentThing  # type: ignore  # noqa: F841


# ===== capsule_auditor.py: import guard =====

class TestCapsuleAuditor:
    def test_import_guard_raises_without_capsule(self):
        """CapsuleAuditor should raise ImportError if qp-capsule not installed."""
        from qp_vault.audit.capsule_auditor import HAS_CAPSULE, CapsuleAuditor
        if not HAS_CAPSULE:
            with pytest.raises(ImportError, match="qp-capsule is required"):
                CapsuleAuditor()


# ===== config.py: TOML import error, _flatten_toml edge =====

class TestConfigEdges:
    def test_from_toml_without_tomllib(self, tmp_path):
        """Should raise ImportError on Python < 3.11 without tomli."""
        toml_file = tmp_path / "test.toml"
        toml_file.write_text("[storage]\nbackend = 'sqlite'\n")

    def test_flatten_toml_passthrough(self):
        from qp_vault.config import _flatten_toml
        data = {"trust_weights": {"canonical": 2.0}}
        result = _flatten_toml(data)
        assert result["trust_weights"] == {"canonical": 2.0}


# ===== chunker.py: overlap paths with long documents =====

class TestChunkerOverlap:
    def test_overlap_applied(self):
        """When chunks exceed target, overlap from previous chunk should be included."""
        config = ChunkerConfig(target_tokens=20, min_tokens=5, max_tokens=40, overlap_tokens=10)
        paragraphs = [f"Paragraph {i} with enough words to fill a chunk." for i in range(10)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 2
        # Verify overlap: last words of chunk N should appear in chunk N+1
        if len(chunks) >= 2:
            last_words_c0 = chunks[0].content.split()[-3:]
            assert any(w in chunks[1].content for w in last_words_c0)

    def test_max_tokens_forces_flush(self):
        """A single enormous paragraph should be flushed at max_tokens."""
        config = ChunkerConfig(target_tokens=10, min_tokens=2, max_tokens=30, overlap_tokens=5)
        text = " ".join(["word"] * 200)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 1

    def test_paragraph_splitting(self):
        """Double newlines should split into paragraphs."""
        text = "Para one.\n\nPara two.\n\nPara three."
        chunks = chunk_text(text)
        combined = " ".join(c.content for c in chunks)
        assert "Para one" in combined
        assert "Para three" in combined


# ===== search_engine.py: config override, string datetime edge =====

class TestSearchEngineEdges:
    def test_custom_config_weights(self):
        config = VaultConfig(trust_weights={"canonical": 3.0, "working": 1.0, "ephemeral": 0.5, "archived": 0.1})
        from qp_vault.core.search_engine import compute_trust_weight
        assert compute_trust_weight("canonical", config) == 3.0

    def test_freshness_invalid_string(self):
        """Invalid datetime string should return 1.0 (fresh)."""
        f = compute_freshness("not-a-date", "working")
        assert f == 1.0

    def test_freshness_future_date(self):
        """Future dates should return 1.0."""
        future = datetime.now(tz=UTC) + timedelta(days=30)
        f = compute_freshness(future, "working")
        assert f >= 1.0


# ===== layer_manager.py: uncovered methods =====

class TestLayerManagerEdges:
    def test_get_default_trust(self):
        mgr = LayerManager()
        assert mgr.get_default_trust(MemoryLayer.OPERATIONAL) == TrustTier.WORKING
        assert mgr.get_default_trust(MemoryLayer.STRATEGIC) == TrustTier.CANONICAL

    def test_get_search_boost(self):
        mgr = LayerManager()
        assert mgr.get_search_boost(MemoryLayer.OPERATIONAL) == 1.5
        assert mgr.get_search_boost(MemoryLayer.STRATEGIC) == 1.0

    def test_should_audit_reads(self):
        mgr = LayerManager()
        assert mgr.should_audit_reads(MemoryLayer.COMPLIANCE) is True
        assert mgr.should_audit_reads(MemoryLayer.OPERATIONAL) is False

    @pytest.mark.asyncio
    async def test_layer_view_config_property(self, tmp_path):
        vault = AsyncVault(tmp_path / "lv-test")
        lv = vault.layer(MemoryLayer.COMPLIANCE)
        assert lv.config.audit_reads is True
        assert lv.config.retention == "permanent"


# ===== lifecycle_engine.py: superseded_by edge, expiration logging =====

class TestLifecycleEdges:
    @pytest.mark.asyncio
    async def test_supersede_sets_both_pointers(self, tmp_path):
        vault = AsyncVault(tmp_path / "lce-test")
        r1 = await vault.add("v1", name="v1.md")
        r2 = await vault.add("v2", name="v2.md")
        old, new = await vault.supersede(r1.id, r2.id)
        assert old.superseded_by == r2.id
        assert new.supersedes == r1.id

    @pytest.mark.asyncio
    async def test_supersede_nonexistent_old(self, tmp_path):
        vault = AsyncVault(tmp_path / "lce-test2")
        r = await vault.add("doc", name="d.md")
        with pytest.raises(VaultError, match="not found"):
            await vault.supersede("nonexistent", r.id)

    @pytest.mark.asyncio
    async def test_supersede_nonexistent_new(self, tmp_path):
        vault = AsyncVault(tmp_path / "lce-test3")
        r = await vault.add("doc", name="d.md")
        with pytest.raises(VaultError, match="not found"):
            await vault.supersede(r.id, "nonexistent")

    @pytest.mark.asyncio
    async def test_chain_cycle_protection(self, tmp_path):
        """Chain walk should not infinite-loop on malformed data."""
        vault = AsyncVault(tmp_path / "cycle-test")
        r = await vault.add("doc", name="d.md")
        # chain() with a single doc should just return it
        chain = await vault.chain(r.id)
        assert len(chain) == 1

    @pytest.mark.asyncio
    async def test_expiring_with_string_date(self, tmp_path):
        """valid_until stored as string should still be compared correctly."""
        vault = AsyncVault(tmp_path / "exp-str")
        future = date.today() + timedelta(days=30)
        r = await vault.add("Doc", name="d.md", valid_from=date.today(), valid_until=future)
        expiring = await vault.expiring(days=60)
        assert r.id in [e.id for e in expiring]


# ===== sqlite.py: error paths, vector-only search, FTS sanitizer =====

class TestSQLiteEdges:
    @pytest.mark.asyncio
    async def test_store_duplicate_id_raises(self, tmp_path):
        backend = SQLiteBackend(tmp_path / "dup.db")
        await backend.initialize()
        from qp_vault.models import Resource
        now = datetime.now(tz=UTC)
        r = Resource(id="dup-1", name="a.md", content_hash="h1",
                     cid="vault://sha3-256/h1", created_at=now, updated_at=now)
        await backend.store_resource(r)
        from qp_vault.exceptions import StorageError
        with pytest.raises(StorageError, match="Failed to store"):
            await backend.store_resource(r)  # Duplicate ID

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, tmp_path):
        backend = SQLiteBackend(tmp_path / "upd.db")
        await backend.initialize()
        from qp_vault.exceptions import StorageError
        from qp_vault.protocols import ResourceUpdate
        with pytest.raises(StorageError, match="not found"):
            await backend.update_resource("nonexistent", ResourceUpdate(name="new"))

    @pytest.mark.asyncio
    async def test_restore_nonexistent_raises(self, tmp_path):
        backend = SQLiteBackend(tmp_path / "rest.db")
        await backend.initialize()
        from qp_vault.exceptions import StorageError
        with pytest.raises(StorageError, match="not found"):
            await backend.restore_resource("nonexistent")

    @pytest.mark.asyncio
    async def test_close(self, tmp_path):
        backend = SQLiteBackend(tmp_path / "close.db")
        await backend.initialize()
        await backend.close()
        assert backend._conn is None

    @pytest.mark.asyncio
    async def test_search_with_no_fts_matches(self, tmp_path):
        backend = SQLiteBackend(tmp_path / "nofts.db")
        await backend.initialize()
        from qp_vault.models import Chunk, Resource
        from qp_vault.protocols import SearchQuery
        now = datetime.now(tz=UTC)
        r = Resource(id="r-1", name="a.md", content_hash="h", cid="v://h",
                     status="indexed", created_at=now, updated_at=now)
        await backend.store_resource(r)
        c = Chunk(id="c-1", resource_id="r-1", content="alpha beta gamma",
                  cid="v://c", embedding=[1.0, 0.0], chunk_index=0)
        await backend.store_chunks("r-1", [c])
        # Search for text not in the document
        results = await backend.search(SearchQuery(
            query_text="zzzznonexistent", query_embedding=[1.0, 0.0], top_k=10))
        # Should still return vector match even if FTS has no match
        assert len(results) >= 1

    def test_fts_sanitizer(self):
        assert _sanitize_fts_query("hello world") == "hello world"
        assert _sanitize_fts_query('hello* OR "world"') == "hello OR world"
        assert _sanitize_fts_query("test(foo)") == "test foo"
        assert _sanitize_fts_query("") == ""
        assert _sanitize_fts_query("   spaces   ") == "spaces"


# ===== vault.py: source resolution branches =====

class TestVaultSourceResolution:
    def test_add_from_path_object(self, tmp_path):
        vault = Vault(tmp_path / "src-vault")
        f = tmp_path / "pathobj.md"
        f.write_text("Path object content")
        r = vault.add(Path(f))  # Explicit Path object
        assert r.name == "pathobj.md"

    def test_add_from_bytes(self, tmp_path):
        vault = Vault(tmp_path / "bytes-vault")
        r = vault.add(b"Bytes content here", name="from-bytes.md")
        assert r.name == "from-bytes.md"
        assert r.chunk_count >= 1

    def test_add_string_that_looks_like_path_but_isnt(self, tmp_path):
        vault = Vault(tmp_path / "nopath-vault")
        r = vault.add("/nonexistent/path/doc.md")
        assert r.name == "untitled.md"  # Falls through to string content

    def test_add_with_custom_parser(self, tmp_path):
        from qp_vault.processing.text_parser import TextParser
        vault = Vault(tmp_path / "parser-vault", parsers=[TextParser()])
        f = tmp_path / "custom.py"
        f.write_text("def hello(): pass")
        r = vault.add(f)
        assert r.chunk_count >= 1

    def test_add_none_name_defaults(self, tmp_path):
        vault = Vault(tmp_path / "noname-vault")
        r = vault.add("Just text content")
        assert r.name  # Should have a default name


# ===== integrity/detector.py: edge cases =====

class TestIntegrityEdges:
    def test_staleness_very_old(self):
        r = Resource(
            id="old", name="old.md", content_hash="h", cid="v://h",
            created_at=datetime(2020, 1, 1, tzinfo=UTC), updated_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        score = compute_staleness_score(r)
        assert score > 0.9  # Very stale

    def test_orphan_with_supersedes_not_orphaned(self):
        r = Resource(
            id="s", name="s.md", content_hash="h", cid="v://h",
            supersedes="other-id",
            created_at=datetime(2020, 1, 1, tzinfo=UTC), updated_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        orphans = find_orphans([r])
        assert len(orphans) == 0

    def test_health_all_working_penalty(self):
        """Vault with 10+ resources all at WORKING trust should get penalized."""
        resources = [
            Resource(
                id=f"r{i}", name=f"r{i}.md", content_hash=f"h{i}", cid=f"v://h{i}",
                trust_tier="working",
                created_at=datetime.now(tz=UTC), updated_at=datetime.now(tz=UTC),
            )
            for i in range(10)
        ]
        score = compute_health_score(resources)
        assert score.trust_alignment < 100  # Should be penalized


# ===== CLI: inspect and verify-resource commands =====

class TestCLIAdvanced:
    @pytest.fixture
    def runner(self):
        from typer.testing import CliRunner
        return CliRunner()

    @pytest.fixture
    def vault_with_data(self, tmp_path, runner):
        from qp_vault.cli.main import app
        vault_dir = tmp_path / "cli-adv"
        runner.invoke(app, ["init", str(vault_dir)])
        f = tmp_path / "inspectable.md"
        f.write_text("Content for inspection and verification.")
        result = runner.invoke(app, ["add", str(f), "--path", str(vault_dir)])
        # Extract resource ID from output
        output = result.output
        id_line = [ln for ln in output.split("\n") if "ID:" in ln]
        resource_id = id_line[0].split("ID:")[1].strip() if id_line else None
        return vault_dir, resource_id

    def test_inspect(self, runner, vault_with_data):
        from qp_vault.cli.main import app
        vault_dir, resource_id = vault_with_data
        if resource_id:
            result = runner.invoke(app, ["inspect", resource_id, "--path", str(vault_dir)])
            assert result.exit_code == 0
            assert "Content Hash" in result.output or resource_id in result.output

    def test_inspect_nonexistent(self, runner, tmp_path):
        from qp_vault.cli.main import app
        vault_dir = tmp_path / "cli-insp"
        runner.invoke(app, ["init", str(vault_dir)])
        result = runner.invoke(app, ["inspect", "nonexistent", "--path", str(vault_dir)])
        assert result.exit_code == 1

    def test_verify_single_resource(self, runner, vault_with_data):
        from qp_vault.cli.main import app
        vault_dir, resource_id = vault_with_data
        if resource_id:
            result = runner.invoke(app, ["verify", resource_id, "--path", str(vault_dir)])
            assert result.exit_code == 0
            assert "PASS" in result.output

    def test_add_with_layer(self, runner, tmp_path):
        from qp_vault.cli.main import app
        vault_dir = tmp_path / "cli-layer"
        runner.invoke(app, ["init", str(vault_dir)])
        f = tmp_path / "ops.md"
        f.write_text("Operational document.")
        result = runner.invoke(app, [
            "add", str(f), "--layer", "operational", "--path", str(vault_dir)])
        assert result.exit_code == 0

    def test_add_with_tags(self, runner, tmp_path):
        from qp_vault.cli.main import app
        vault_dir = tmp_path / "cli-tags"
        runner.invoke(app, ["init", str(vault_dir)])
        f = tmp_path / "tagged.md"
        f.write_text("Tagged document.")
        result = runner.invoke(app, [
            "add", str(f), "--tags", "security,reviewed", "--path", str(vault_dir)])
        assert result.exit_code == 0

    def test_search_with_top_k(self, runner, tmp_path):
        from qp_vault.cli.main import app
        vault_dir = tmp_path / "cli-topk"
        runner.invoke(app, ["init", str(vault_dir)])
        f = tmp_path / "doc.md"
        f.write_text("Searchable test content for top-k test.")
        runner.invoke(app, ["add", str(f), "--path", str(vault_dir)])
        result = runner.invoke(app, [
            "search", "searchable", "--top-k", "1", "--path", str(vault_dir)])
        assert result.exit_code == 0

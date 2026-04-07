"""Tests to close remaining coverage gaps in testable modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault import AsyncVault, Vault
from qp_vault.config import VaultConfig
from qp_vault.enums import Lifecycle, MemoryLayer, TrustTier

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# vault.py branches (93% -> higher)
# =============================================================================


class TestVaultEdgeBranches:
    def test_add_with_layer(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "lyr")
        r = vault.add("Doc", name="d.md", layer="operational")
        assert r.layer == MemoryLayer.OPERATIONAL

    def test_add_with_valid_dates(self, tmp_path: Path) -> None:
        from datetime import date

        vault = Vault(tmp_path / "dates")
        r = vault.add(
            "Temporal doc",
            name="t.md",
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
        )
        assert r.id

    def test_add_with_collection(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "col")
        c = vault.create_collection("Eng")
        r = vault.add("Doc", name="d.md", collection=c["id"])
        assert r.collection_id == c["id"]

    def test_search_with_collection_filter(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "sf")
        c = vault.create_collection("Test")
        vault.add("Content in collection", name="c.md", collection=c["id"])
        vault.add("Content outside", name="o.md")
        results = vault.search("content", collection=c["id"])
        assert isinstance(results, list)

    def test_search_with_layer_filter(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "lf")
        vault.add("Op content", name="o.md", layer="operational")
        results = vault.search("content", layer="operational")
        assert isinstance(results, list)

    def test_search_as_of(self, tmp_path: Path) -> None:
        from datetime import date

        vault = Vault(tmp_path / "asof")
        vault.add("Temporal doc", name="t.md")
        results = vault.search("temporal", as_of=date(2026, 6, 1))
        assert isinstance(results, list)

    def test_search_no_deduplicate(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "nodd")
        vault.add("Duplicate check content", name="d.md")
        results = vault.search("duplicate", deduplicate=False)
        assert isinstance(results, list)

    def test_layer_view_add(self, tmp_path: Path) -> None:
        vault = AsyncVault(tmp_path / "lva")
        view = vault.layer(MemoryLayer.OPERATIONAL)
        assert view is not None

    def test_status_includes_layers(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "sl")
        vault.add("Doc", name="d.md", layer="operational")
        status = vault.status()
        assert "by_layer" in status

    def test_import_vault_sync(self, tmp_path: Path) -> None:
        v1 = Vault(tmp_path / "ie1")
        v1.add("Export test content", name="e.md")
        v1.export_vault(str(tmp_path / "exp.json"))
        v2 = Vault(tmp_path / "ie2")
        imported = v2.import_vault(str(tmp_path / "exp.json"))
        assert len(imported) >= 1

    def test_upsert_sync(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "ups")
        r1 = vault.upsert("Content v1", name="doc.md")
        r2 = vault.upsert("Content v2", name="doc.md")
        assert r2.id != r1.id  # Replaced

    def test_get_multiple_sync(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "gm")
        r1 = vault.add("A", name="a.md")
        r2 = vault.add("B", name="b.md")
        results = vault.get_multiple([r1.id, r2.id])
        assert len(results) == 2

    def test_verify_empty_vault(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "ve")
        result = vault.verify()
        assert result is not None


# =============================================================================
# Layer Manager (95% -> higher)
# =============================================================================


class TestLayerManagerEdges:
    def test_get_default_trust(self, tmp_path: Path) -> None:
        vault = AsyncVault(tmp_path / "lm1")
        trust = vault._layer_manager.get_default_trust(MemoryLayer.OPERATIONAL)
        assert trust == TrustTier.WORKING

    def test_get_default_trust_strategic(self, tmp_path: Path) -> None:
        vault = AsyncVault(tmp_path / "lm2")
        trust = vault._layer_manager.get_default_trust(MemoryLayer.STRATEGIC)
        assert trust == TrustTier.CANONICAL

    def test_get_stats_empty(self, tmp_path: Path) -> None:
        vault = AsyncVault(tmp_path / "lm3")
        stats = vault._layer_manager.get_stats([])
        assert isinstance(stats, dict)


# =============================================================================
# Provenance (93% -> higher)
# =============================================================================


class TestProvenanceChain:
    @pytest.mark.asyncio
    async def test_get_chain_empty(self) -> None:
        from qp_vault.provenance import ContentProvenanceService

        service = ContentProvenanceService()
        chain = await service.get_chain("nonexistent-resource")
        assert chain == []

    @pytest.mark.asyncio
    async def test_get_by_uploader(self) -> None:
        from qp_vault.enums import UploadMethod
        from qp_vault.provenance import ContentProvenanceService

        service = ContentProvenanceService()
        await service.create_attestation(
            resource_id="r1",
            uploader_id="u1",
            method=UploadMethod.API,
            original_hash="abc",
        )
        records = await service.get_by_uploader("u1")
        assert len(records) >= 1

    @pytest.mark.asyncio
    async def test_get_by_method(self) -> None:
        from qp_vault.enums import UploadMethod
        from qp_vault.provenance import ContentProvenanceService

        service = ContentProvenanceService()
        await service.create_attestation(
            resource_id="r2",
            uploader_id="u2",
            method=UploadMethod.CLI,
            original_hash="def",
        )
        records = await service.get_by_method(UploadMethod.CLI)
        assert len(records) >= 1


# =============================================================================
# Lifecycle Engine (91% -> higher)
# =============================================================================


class TestLifecycleEdges:
    def test_transition_draft_to_review(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "le1")
        r = vault.add("Doc", name="d.md", lifecycle="draft")
        r = vault.transition(r.id, "review")
        assert r.lifecycle == Lifecycle.REVIEW

    def test_transition_review_to_active(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "le2")
        r = vault.add("Doc", name="d.md", lifecycle="draft")
        r = vault.transition(r.id, "review")
        r = vault.transition(r.id, "active")
        assert r.lifecycle == Lifecycle.ACTIVE

    def test_supersede_chain(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "le3")
        v1 = vault.add("V1", name="v1.md", trust_tier="canonical")
        v2 = vault.add("V2", name="v2.md", trust_tier="canonical")
        old, new = vault.supersede(v1.id, v2.id)
        chain = vault.chain(v1.id)
        assert len(chain) >= 2


# =============================================================================
# Search Engine (94% -> higher)
# =============================================================================


class TestSearchEngineEdges:
    def test_weighting_with_empty_results(self) -> None:
        from qp_vault.core.search_engine import apply_trust_weighting

        config = VaultConfig()
        results = apply_trust_weighting([], config)
        assert results == []

    def test_weighting_sorts_by_relevance(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "se1")
        vault.add("First document about testing", name="a.md", trust_tier="canonical")
        vault.add("Second document about testing", name="b.md", trust_tier="ephemeral")
        results = vault.search("testing")
        if len(results) >= 2:
            assert results[0].relevance >= results[1].relevance


# =============================================================================
# FastAPI Routes (78% -> higher)
# =============================================================================


class TestFastAPIGaps:
    def test_create_router(self, tmp_path: Path) -> None:
        from qp_vault.integrations.fastapi_routes import HAS_FASTAPI

        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")
        from qp_vault.integrations.fastapi_routes import create_vault_router

        vault = AsyncVault(tmp_path / "api")
        router = create_vault_router(vault)
        assert router is not None

    def test_search_request_model(self) -> None:
        from qp_vault.integrations.fastapi_routes import HAS_FASTAPI

        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")
        from qp_vault.integrations.fastapi_routes import SearchRequest

        req = SearchRequest(query="test", top_k=5, threshold=0.5)
        assert req.query == "test"
        assert req.top_k == 5

    def test_add_resource_request_model(self) -> None:
        from qp_vault.integrations.fastapi_routes import HAS_FASTAPI

        if not HAS_FASTAPI:
            pytest.skip("FastAPI not installed")
        from qp_vault.integrations.fastapi_routes import AddResourceRequest

        req = AddResourceRequest(content="test content", trust_tier="canonical")
        assert req.trust_tier == "canonical"


# =============================================================================
# Encryption (zeroize remaining line)
# =============================================================================


class TestZeroizeEdge:
    def test_zeroize_1_byte(self) -> None:
        from qp_vault.encryption.zeroize import zeroize

        data = bytearray(b"\xff")
        zeroize(data)
        assert data[0] == 0


# =============================================================================
# Noop Embedder (is_local property)
# =============================================================================


class TestNoopEdge:
    @pytest.mark.asyncio
    async def test_noop_is_local(self) -> None:
        from qp_vault.embeddings.noop import NoopEmbedder

        e = NoopEmbedder()
        assert e.is_local is True
        vecs = await e.embed(["test"])
        assert vecs == [[]]


# =============================================================================
# Config edge
# =============================================================================


class TestConfigEdge:
    def test_toml_flatten_unknown_section(self, tmp_path: Path) -> None:
        p = tmp_path / "c.toml"
        p.write_text('[search]\nvector_weight = 0.9\n')
        config = VaultConfig.from_toml(p)
        assert config.vector_weight == 0.9


# =============================================================================
# __init__.py lazy import
# =============================================================================


class TestLazyImport:
    def test_async_vault_import(self) -> None:
        from qp_vault import AsyncVault

        assert AsyncVault is not None

    def test_vault_import(self) -> None:
        from qp_vault import Vault

        assert Vault is not None

    def test_unknown_attr_raises(self) -> None:
        with pytest.raises(AttributeError):
            from qp_vault import __getattr__

            __getattr__("NonexistentClass")

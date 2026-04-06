"""Tests for memory layers, integrity detection, and health scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qp_vault import HealthScore, MemoryLayer, TrustTier, Vault
from qp_vault.core.layer_manager import LayerManager
from qp_vault.integrity.detector import (
    compute_health_score,
    compute_staleness_score,
    find_duplicates_by_hash,
    find_orphans,
)
from qp_vault.models import Resource


def _make_resource(
    name: str = "test.md",
    trust: str = "working",
    age_days: int = 0,
    content_hash: str | None = None,
    collection_id: str | None = None,
    tags: list[str] | None = None,
    layer: str | None = None,
) -> Resource:
    now = datetime.now(tz=UTC) - timedelta(days=age_days)
    return Resource(
        id=f"r-{name}",
        name=name,
        content_hash=content_hash or f"hash-{name}",
        cid=f"vault://sha3-256/hash-{name}",
        trust_tier=trust,
        collection_id=collection_id,
        tags=tags or [],
        layer=layer,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "layer-vault")


# --- Layer Manager ---

class TestLayerManager:
    def test_default_configs_exist(self):
        mgr = LayerManager()
        for layer in MemoryLayer:
            config = mgr.get_config(layer)
            assert config.name == layer

    def test_operational_defaults(self):
        mgr = LayerManager()
        cfg = mgr.get_config(MemoryLayer.OPERATIONAL)
        assert cfg.default_trust == TrustTier.WORKING
        assert cfg.search_boost == 1.5
        assert cfg.audit_reads is False

    def test_strategic_defaults(self):
        mgr = LayerManager()
        cfg = mgr.get_config(MemoryLayer.STRATEGIC)
        assert cfg.default_trust == TrustTier.CANONICAL
        assert cfg.search_boost == 1.0

    def test_compliance_defaults(self):
        mgr = LayerManager()
        cfg = mgr.get_config(MemoryLayer.COMPLIANCE)
        assert cfg.default_trust == TrustTier.CANONICAL
        assert cfg.retention == "permanent"
        assert cfg.audit_reads is True

    def test_layer_stats(self):
        mgr = LayerManager()
        resources = [
            _make_resource("a.md", layer="operational"),
            _make_resource("b.md", layer="operational"),
            _make_resource("c.md", layer="strategic"),
        ]
        stats = mgr.get_stats(resources)
        assert stats["operational"]["resource_count"] == 2
        assert stats["strategic"]["resource_count"] == 1
        assert stats["compliance"]["resource_count"] == 0


# --- Layer View Integration ---

class TestLayerView:
    @pytest.mark.asyncio
    async def test_layer_add_applies_defaults(self, tmp_path):
        from qp_vault import AsyncVault
        vault = AsyncVault(tmp_path / "layer-test")

        ops = vault.layer(MemoryLayer.OPERATIONAL)
        r = await ops.add("Runbook content", name="runbook.md")
        assert r.layer == MemoryLayer.OPERATIONAL

    @pytest.mark.asyncio
    async def test_layer_search_scoped(self, tmp_path):
        from qp_vault import AsyncVault
        vault = AsyncVault(tmp_path / "layer-search")

        await vault.add("Operational content about deploys", name="deploy.md", layer="operational")
        await vault.add("Strategic content about architecture", name="adr.md", layer="strategic")

        ops = vault.layer("operational")
        results = await ops.list()
        assert all(
            (r.layer.value if hasattr(r.layer, "value") else r.layer) == "operational"
            for r in results
        )


# --- Staleness ---

class TestStaleness:
    def test_fresh_document(self):
        r = _make_resource(age_days=0)
        score = compute_staleness_score(r)
        assert score < 0.1

    def test_old_document(self):
        r = _make_resource(age_days=365)
        score = compute_staleness_score(r)
        assert score > 0.5

    def test_volatile_keyword_decays_faster(self):
        r_volatile = _make_resource("sop-deploy.md", age_days=90)
        r_normal = _make_resource("readme.md", age_days=90)
        assert compute_staleness_score(r_volatile) > compute_staleness_score(r_normal)

    def test_canonical_decays_slower(self):
        r_canonical = _make_resource(trust="canonical", age_days=180)
        r_ephemeral = _make_resource(trust="ephemeral", age_days=180)
        assert compute_staleness_score(r_canonical) < compute_staleness_score(r_ephemeral)


# --- Duplicates ---

class TestDuplicates:
    def test_finds_duplicate_hashes(self):
        resources = [
            _make_resource("a.md", content_hash="same"),
            _make_resource("b.md", content_hash="same"),
            _make_resource("c.md", content_hash="unique"),
        ]
        groups = find_duplicates_by_hash(resources)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_no_duplicates(self):
        resources = [
            _make_resource("a.md", content_hash="h1"),
            _make_resource("b.md", content_hash="h2"),
        ]
        groups = find_duplicates_by_hash(resources)
        assert len(groups) == 0


# --- Orphans ---

class TestOrphans:
    def test_finds_orphans(self):
        resources = [
            _make_resource("orphan.md", age_days=60),  # No collection, no tags
            _make_resource("connected.md", age_days=60, collection_id="c-1"),
        ]
        orphans = find_orphans(resources)
        assert len(orphans) == 1
        assert orphans[0].name == "orphan.md"

    def test_young_docs_not_orphaned(self):
        resources = [_make_resource("new.md", age_days=5)]
        orphans = find_orphans(resources)
        assert len(orphans) == 0

    def test_tagged_not_orphaned(self):
        resources = [_make_resource("tagged.md", age_days=60, tags=["important"])]
        orphans = find_orphans(resources)
        assert len(orphans) == 0


# --- Health Score ---

class TestHealthScore:
    def test_empty_vault_perfect_health(self):
        score = compute_health_score([])
        assert score.overall == 100.0
        assert score.resource_count == 0

    def test_fresh_unique_vault_high_health(self):
        resources = [
            _make_resource("a.md", age_days=0, collection_id="c-1", tags=["tagged"], trust="canonical"),
            _make_resource("b.md", age_days=0, collection_id="c-1", tags=["tagged"], trust="working"),
        ]
        score = compute_health_score(resources)
        assert score.overall > 70
        assert score.freshness > 90
        assert score.uniqueness == 100.0

    def test_duplicate_heavy_vault_low_coherence(self):
        resources = [
            _make_resource("a.md", content_hash="same"),
            _make_resource("b.md", content_hash="same"),
            _make_resource("c.md", content_hash="same"),
        ]
        score = compute_health_score(resources)
        assert score.coherence < 50

    def test_health_returns_health_score(self):
        score = compute_health_score([_make_resource("a.md")])
        assert isinstance(score, HealthScore)
        assert 0 <= score.overall <= 100


# --- Vault.health() Integration ---

class TestVaultHealth:
    def test_vault_health(self, vault):
        vault.add("Resource 1", name="r1.md", trust="canonical")
        vault.add("Resource 2", name="r2.md", trust="working")
        score = vault.health()
        assert isinstance(score, HealthScore)
        assert score.resource_count == 2
        assert score.overall > 0

    def test_vault_status_includes_layer_details(self, vault):
        vault.add("Ops doc", name="ops.md", layer="operational")
        s = vault.status()
        assert "layer_details" in s
        assert "operational" in s["layer_details"]
        assert s["layer_details"]["operational"]["resource_count"] == 1

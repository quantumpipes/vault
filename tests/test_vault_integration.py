"""Integration tests for the full Vault pipeline.

Tests the complete flow: add -> search -> verify -> update -> delete.
Uses SQLite backend (default, zero config).
"""


import pytest

from qp_vault import (
    AsyncVault,
    DataClassification,
    Lifecycle,
    MemoryLayer,
    ResourceStatus,
    SearchResult,
    TrustTier,
    Vault,
    VaultError,
    VaultVerificationResult,
    VerificationResult,
)


@pytest.fixture
def vault(tmp_path):
    """Fresh SQLite vault for each test."""
    return Vault(tmp_path / "test-vault")


@pytest.fixture
def populated_vault(vault):
    """Vault with 3 resources at different trust tiers."""
    vault.add(
        "Standard operating procedure for incident response. "
        "When an incident is detected, the on-call engineer must "
        "acknowledge within 15 minutes. Severity is classified as "
        "P0 (critical), P1 (high), P2 (medium), or P3 (low).",
        name="sop-incident.md",
        trust="canonical",
    )
    vault.add(
        "Draft proposal for new employee onboarding process. "
        "The current onboarding takes 3 weeks. We propose reducing "
        "to 2 weeks by parallelizing equipment setup and access provisioning.",
        name="draft-onboarding.md",
        trust="working",
    )
    vault.add(
        "Meeting notes from engineering standup 2026-03-15. "
        "Discussed migration to new auth service. Blocker: legacy "
        "API clients need updated tokens.",
        name="standup-notes.md",
        trust="ephemeral",
    )
    return vault


class TestVaultAdd:
    def test_add_text_resource(self, vault):
        r = vault.add("Hello world", name="hello.txt")
        assert r.name == "hello.txt"
        assert r.status == ResourceStatus.INDEXED
        assert r.trust_tier == TrustTier.WORKING
        assert r.chunk_count >= 1
        assert r.content_hash
        assert r.cid.startswith("vault://sha3-256/")

    def test_add_with_trust_tier(self, vault):
        r = vault.add("Canonical document", trust="canonical", name="canon.md")
        assert r.trust_tier == TrustTier.CANONICAL

    def test_add_with_classification(self, vault):
        r = vault.add("Secret stuff", classification="confidential", name="secret.md")
        assert r.data_classification == DataClassification.CONFIDENTIAL

    def test_add_with_layer(self, vault):
        r = vault.add("Runbook content", layer="operational", name="runbook.md")
        assert r.layer == MemoryLayer.OPERATIONAL

    def test_add_with_tags(self, vault):
        r = vault.add("Tagged doc", tags=["important", "reviewed"], name="tagged.md")
        assert r.tags == ["important", "reviewed"]

    def test_add_with_metadata(self, vault):
        r = vault.add("Meta doc", metadata={"author": "alice"}, name="meta.md")
        assert r.metadata == {"author": "alice"}

    def test_add_with_lifecycle(self, vault):
        r = vault.add("Draft doc", lifecycle="draft", name="draft.md")
        assert r.lifecycle == Lifecycle.DRAFT

    def test_add_generates_unique_ids(self, vault):
        r1 = vault.add("Doc 1", name="a.md")
        r2 = vault.add("Doc 2", name="b.md")
        assert r1.id != r2.id

    def test_add_computes_content_hash(self, vault):
        r1 = vault.add("Same content", name="a.md")
        r2 = vault.add("Same content", name="b.md")
        assert r1.content_hash == r2.content_hash

    def test_add_different_content_different_hash(self, vault):
        r1 = vault.add("Content A", name="a.md")
        r2 = vault.add("Content B", name="b.md")
        assert r1.content_hash != r2.content_hash


class TestVaultGet:
    def test_get_existing(self, vault):
        r = vault.add("Test doc", name="test.md")
        fetched = vault.get(r.id)
        assert fetched.id == r.id
        assert fetched.name == r.name

    def test_get_nonexistent_raises(self, vault):
        with pytest.raises(VaultError):
            vault.get("nonexistent-id")


class TestVaultList:
    def test_list_all(self, populated_vault):
        resources = populated_vault.list()
        assert len(resources) == 3

    def test_list_by_trust(self, populated_vault):
        canonical = populated_vault.list(trust=TrustTier.CANONICAL)
        assert len(canonical) == 1
        assert canonical[0].trust_tier == TrustTier.CANONICAL

    def test_list_with_limit(self, populated_vault):
        resources = populated_vault.list(limit=2)
        assert len(resources) == 2

    def test_list_excludes_deleted(self, populated_vault):
        resources = populated_vault.list()
        r_id = resources[0].id
        populated_vault.delete(r_id)
        after = populated_vault.list()
        assert len(after) == 2


class TestVaultSearch:
    def test_search_finds_relevant(self, populated_vault):
        results = populated_vault.search("incident response")
        assert len(results) > 0
        assert "incident" in results[0].content.lower()

    def test_search_returns_search_results(self, populated_vault):
        results = populated_vault.search("onboarding")
        assert len(results) > 0
        assert isinstance(results[0], SearchResult)

    def test_search_trust_weighting(self, populated_vault):
        """CANONICAL should get 1.5x weight, EPHEMERAL 0.7x."""
        results = populated_vault.search("incident response")
        for r in results:
            if r.trust_tier == TrustTier.CANONICAL:
                assert r.trust_weight == 1.5
            elif r.trust_tier == TrustTier.EPHEMERAL:
                assert r.trust_weight == 0.7

    def test_search_empty_query(self, populated_vault):
        results = populated_vault.search("")
        # Empty query may return no FTS results
        assert isinstance(results, list)

    def test_search_no_results(self, populated_vault):
        results = populated_vault.search("quantum_nonexistent_topic_xyz")
        assert results == []

    def test_search_top_k(self, populated_vault):
        results = populated_vault.search("process", top_k=1)
        assert len(results) <= 1


class TestVaultUpdate:
    def test_update_trust_tier(self, vault):
        r = vault.add("Doc", name="doc.md", trust="working")
        updated = vault.update(r.id, trust="canonical")
        assert updated.trust_tier == "canonical"

    def test_update_tags(self, vault):
        r = vault.add("Doc", name="doc.md")
        updated = vault.update(r.id, tags=["new-tag"])
        assert updated.tags == ["new-tag"]


class TestVaultDelete:
    def test_soft_delete(self, vault):
        r = vault.add("Doc", name="doc.md")
        vault.delete(r.id)
        # Should still exist but marked deleted
        resources = vault.list(status=ResourceStatus.DELETED)
        assert len(resources) == 1

    def test_hard_delete(self, vault):
        r = vault.add("Doc", name="doc.md")
        vault.delete(r.id, hard=True)
        with pytest.raises(VaultError):
            vault.get(r.id)


class TestVaultVerify:
    def test_verify_single_resource(self, vault):
        r = vault.add("Verify this content", name="verify.md")
        result = vault.verify(r.id)
        assert isinstance(result, VerificationResult)
        assert result.passed is True
        assert result.stored_hash == result.computed_hash

    def test_verify_all(self, populated_vault):
        result = populated_vault.verify()
        assert isinstance(result, VaultVerificationResult)
        assert result.passed is True
        assert result.resource_count == 3
        assert result.merkle_root

    def test_verify_empty_vault(self, vault):
        result = vault.verify()
        assert isinstance(result, VaultVerificationResult)
        assert result.passed is True
        assert result.resource_count == 0


class TestVaultStatus:
    def test_status(self, populated_vault):
        s = populated_vault.status()
        assert s["total_resources"] == 3
        assert s["by_trust_tier"]["canonical"] == 1
        assert s["by_trust_tier"]["working"] == 1
        assert s["by_trust_tier"]["ephemeral"] == 1


class TestVaultAuditTrail:
    def test_audit_log_created(self, vault):
        vault.add("Audit test", name="audit.md")
        log_path = vault._async.path / "audit.jsonl"
        assert log_path.exists()

        import json
        with open(log_path) as f:
            lines = f.readlines()
        assert len(lines) >= 1

        event = json.loads(lines[0])
        assert event["event_type"] == "create"
        assert event["resource_name"] == "audit.md"
        assert event["resource_hash"]


class TestAsyncVault:
    @pytest.mark.asyncio
    async def test_async_add_and_search(self, tmp_path):
        vault = AsyncVault(tmp_path / "async-vault")
        r = await vault.add("Async test content for search", name="async.md")
        assert r.status == ResourceStatus.INDEXED

        results = await vault.search("async test")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_async_verify(self, tmp_path):
        vault = AsyncVault(tmp_path / "async-vault")
        r = await vault.add("Verify async", name="verify.md")
        result = await vault.verify(r.id)
        assert result.passed

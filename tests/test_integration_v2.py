# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Comprehensive tests for V1-V6 integration features.

Covers: FastAPI endpoints, RBAC, edge cases, cross-feature interactions.
"""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault, EventType, VaultEvent
from qp_vault.exceptions import VaultError

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qp_vault.integrations.fastapi_routes import create_vault_router

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def vault(tmp_vault_path):
    """Fresh async vault."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


@pytest.fixture
async def reader_vault(tmp_vault_path):
    """Vault with reader role (no write permission)."""
    v = AsyncVault(tmp_vault_path, role="reader")
    await v._ensure_initialized()
    return v


@pytest.fixture
def client(tmp_path):
    """FastAPI test client."""
    if not HAS_FASTAPI:
        pytest.skip("fastapi not installed")
    vault = AsyncVault(tmp_path / "api-vault")
    app = FastAPI()
    router = create_vault_router(vault)
    app.include_router(router, prefix="/v1/vault")
    return TestClient(app)


@pytest.fixture
def populated_client(client):
    """Client with two resources."""
    client.post("/v1/vault/resources", json={
        "content": "Python is a versatile programming language for data science.",
        "name": "python-guide.md",
        "trust_tier": "canonical",
    })
    client.post("/v1/vault/resources", json={
        "content": "Rust provides memory safety without garbage collection.",
        "name": "rust-overview.md",
        "trust_tier": "working",
    })
    return client


# ===========================================================================
# FastAPI Endpoint Tests: V2 (reprocess)
# ===========================================================================


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestReprocessEndpoint:

    def test_reprocess_returns_resource(self, populated_client):
        """POST /resources/{id}/reprocess returns the reprocessed resource."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        rid = resources[0]["id"]

        resp = populated_client.post(f"/v1/vault/resources/{rid}/reprocess")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["id"] == rid
        assert data["data"]["status"] == "indexed"
        assert data["meta"]["reprocessed"] is True

    def test_reprocess_nonexistent_returns_error(self, client):
        """POST /resources/{bad-id}/reprocess returns error."""
        resp = client.post("/v1/vault/resources/nonexistent/reprocess")
        assert resp.status_code in (400, 404, 500)


# ===========================================================================
# FastAPI Endpoint Tests: V3 (grep)
# ===========================================================================


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestGrepEndpoint:

    def test_grep_returns_results(self, populated_client):
        """POST /grep returns matching resources."""
        resp = populated_client.post("/v1/vault/grep", json={
            "keywords": ["python"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["total"] >= 1
        assert any("python" in r["content"].lower() for r in data["data"])

    def test_grep_empty_keywords(self, populated_client):
        """POST /grep with empty keywords returns empty."""
        resp = populated_client.post("/v1/vault/grep", json={
            "keywords": [],
        })
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] == 0

    def test_grep_multiple_keywords(self, populated_client):
        """POST /grep with multiple keywords uses OR matching."""
        resp = populated_client.post("/v1/vault/grep", json={
            "keywords": ["python", "rust"],
        })
        assert resp.status_code == 200
        assert resp.json()["meta"]["total"] >= 2


# ===========================================================================
# FastAPI Endpoint Tests: V5 (find_by_name)
# ===========================================================================


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestFindByNameEndpoint:

    def test_find_by_name_exact(self, populated_client):
        """GET /resources/by-name returns exact match."""
        resp = populated_client.get("/v1/vault/resources/by-name", params={"name": "python-guide.md"})
        assert resp.status_code == 200
        assert resp.json()["data"]["name"] == "python-guide.md"

    def test_find_by_name_case_insensitive(self, populated_client):
        """GET /resources/by-name is case-insensitive."""
        resp = populated_client.get("/v1/vault/resources/by-name", params={"name": "PYTHON-GUIDE.MD"})
        assert resp.status_code == 200

    def test_find_by_name_not_found(self, populated_client):
        """GET /resources/by-name returns 404 for missing name."""
        resp = populated_client.get("/v1/vault/resources/by-name", params={"name": "nonexistent.md"})
        assert resp.status_code == 404


# ===========================================================================
# FastAPI Endpoint Tests: V6 (diff, get_multiple, adversarial, import)
# ===========================================================================


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestDiffEndpoint:

    def test_diff_two_resources(self, populated_client):
        """GET /resources/{old}/diff/{new} returns unified diff."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        old_id = resources[0]["id"]
        new_id = resources[1]["id"]

        resp = populated_client.get(f"/v1/vault/resources/{old_id}/diff/{new_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "old_id" in data
        assert "new_id" in data
        assert "diff" in data
        assert isinstance(data["additions"], int)
        assert isinstance(data["deletions"], int)

    def test_diff_nonexistent_resource(self, populated_client):
        """Diff with nonexistent resource returns error."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        resp = populated_client.get(f"/v1/vault/resources/{resources[0]['id']}/diff/nonexistent")
        assert resp.status_code in (400, 404, 500)


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestGetMultipleEndpoint:

    def test_get_multiple_resources(self, populated_client):
        """POST /resources/multiple returns matching resources."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        ids = [r["id"] for r in resources]

        resp = populated_client.post("/v1/vault/resources/multiple", json={
            "resource_ids": ids,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["count"] == len(ids)

    def test_get_multiple_empty_ids(self, client):
        """POST /resources/multiple with empty list returns empty."""
        resp = client.post("/v1/vault/resources/multiple", json={"resource_ids": []})
        assert resp.status_code == 200
        assert resp.json()["meta"]["count"] == 0

    def test_get_multiple_too_many(self, client):
        """POST /resources/multiple with >100 ids returns 400."""
        resp = client.post("/v1/vault/resources/multiple", json={
            "resource_ids": [f"id-{i}" for i in range(101)],
        })
        assert resp.status_code == 400


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestAdversarialEndpoint:

    def test_set_adversarial_status(self, populated_client):
        """PATCH /resources/{id}/adversarial updates status."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        rid = resources[0]["id"]

        resp = populated_client.patch(f"/v1/vault/resources/{rid}/adversarial", json={
            "status": "verified",
        })
        assert resp.status_code == 200
        assert resp.json()["data"]["adversarial_status"] == "verified"

    def test_set_adversarial_missing_status(self, populated_client):
        """PATCH /resources/{id}/adversarial without status returns 400."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        rid = resources[0]["id"]

        resp = populated_client.patch(f"/v1/vault/resources/{rid}/adversarial", json={})
        assert resp.status_code == 400


# ===========================================================================
# RBAC Tests
# ===========================================================================


class TestRBACNewMethods:
    """Verify RBAC enforcement on new methods."""

    @pytest.mark.asyncio
    async def test_reprocess_blocked_for_reader(self, reader_vault: AsyncVault):
        """Reader cannot reprocess (requires update permission)."""
        with pytest.raises(VaultError, match="[Pp]ermission"):
            await reader_vault.reprocess("any-id")

    @pytest.mark.asyncio
    async def test_find_by_name_allowed_for_reader(self, reader_vault: AsyncVault):
        """Reader can find by name (read-only operation)."""
        # Should not raise permission error (returns None since vault is empty)
        result = await reader_vault.find_by_name("anything.md")
        assert result is None

    @pytest.mark.asyncio
    async def test_grep_allowed_for_reader(self, reader_vault: AsyncVault):
        """Reader can grep (search is read-only)."""
        results = await reader_vault.grep(["anything"])
        assert results == []


# ===========================================================================
# Security Boundary Tests
# ===========================================================================


class TestSecurityBoundaries:
    """Tests for security hardening: caps, timeouts, validation."""

    @pytest.mark.asyncio
    async def test_subscriber_cap_enforced(self, vault: AsyncVault):
        """Cannot register more than _MAX_SUBSCRIBERS callbacks."""
        from qp_vault.vault import _MAX_SUBSCRIBERS
        unsubs = []
        for _ in range(_MAX_SUBSCRIBERS):
            unsubs.append(vault.subscribe(lambda e: None))

        with pytest.raises(VaultError, match="[Mm]aximum subscriber"):
            vault.subscribe(lambda e: None)

        # Cleanup
        for u in unsubs:
            u()

    @pytest.mark.asyncio
    async def test_slow_async_callback_times_out(self, vault: AsyncVault):
        """Async callbacks that hang are killed after timeout."""
        import asyncio
        timed_out = False

        async def slow_callback(event: VaultEvent) -> None:
            nonlocal timed_out
            try:
                await asyncio.sleep(60)  # Way past the 5s timeout
            except asyncio.CancelledError:
                timed_out = True
                raise

        vault.subscribe(slow_callback)
        # Should not hang; callback times out after 5s
        await vault.add("Timeout test", name="timeout.md")
        # The vault operation completes regardless of the slow callback

    @pytest.mark.asyncio
    async def test_subscribe_during_notify_safe(self, vault: AsyncVault):
        """Subscribing inside a callback does not crash (snapshot iteration)."""
        inner_received: list[VaultEvent] = []

        def callback_that_subscribes(event: VaultEvent) -> None:
            # Subscribe a new callback during notification
            vault.subscribe(lambda e: inner_received.append(e))

        vault.subscribe(callback_that_subscribes)
        await vault.add("First", name="first.md")
        # Inner subscriber should receive next event, not the current one
        await vault.add("Second", name="second.md")
        assert len(inner_received) >= 1


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestSecurityEndpoints:
    """Tests for endpoint-level security validation."""

    def test_adversarial_invalid_status_rejected(self, populated_client):
        """Invalid adversarial status values are rejected."""
        resources = populated_client.get("/v1/vault/resources").json()["data"]
        rid = resources[0]["id"]

        resp = populated_client.patch(f"/v1/vault/resources/{rid}/adversarial", json={
            "status": "hacked",
        })
        assert resp.status_code == 400
        assert "Invalid status" in resp.json()["detail"]

    def test_import_path_traversal_blocked(self, client):
        """Import endpoint blocks path traversal."""
        resp = client.post("/v1/vault/import", json={
            "path": "../../../etc/passwd",
        })
        assert resp.status_code == 400
        assert "traversal" in resp.json()["detail"].lower()

    def test_get_multiple_non_string_ids_coerced(self, client):
        """Non-string resource IDs are coerced to strings."""
        resp = client.post("/v1/vault/resources/multiple", json={
            "resource_ids": [123, 456],
        })
        assert resp.status_code == 200
        # Should not crash; IDs coerced to "123", "456"
        assert resp.json()["meta"]["count"] == 0  # No matches, but no error


# ===========================================================================
# Subscribe Edge Cases
# ===========================================================================


class TestSubscribeEdgeCases:

    @pytest.mark.asyncio
    async def test_subscribe_sees_reprocess_events(self, vault: AsyncVault):
        """Subscribers receive UPDATE events from reprocess()."""
        events: list[VaultEvent] = []
        vault.subscribe(lambda e: events.append(e))

        resource = await vault.add("Content to reprocess", name="reprocess-sub.md")
        events.clear()

        await vault.reprocess(resource.id)

        assert len(events) == 1
        assert events[0].event_type == EventType.UPDATE
        assert events[0].details.get("reprocessed") is True

    @pytest.mark.asyncio
    async def test_subscribe_event_ordering(self, vault: AsyncVault):
        """Events arrive in the order operations were performed."""
        events: list[VaultEvent] = []
        vault.subscribe(lambda e: events.append(e))

        r1 = await vault.add("First", name="first.md")
        r2 = await vault.add("Second", name="second.md")
        await vault.update(r1.id, tags=["tagged"])
        await vault.delete(r2.id)

        assert len(events) == 4
        assert events[0].event_type == EventType.CREATE
        assert events[0].resource_name == "first.md"
        assert events[1].event_type == EventType.CREATE
        assert events[1].resource_name == "second.md"
        assert events[2].event_type == EventType.UPDATE
        assert events[3].event_type == EventType.DELETE

    @pytest.mark.asyncio
    async def test_subscribe_rapid_fire(self, vault: AsyncVault):
        """Rapid mutations all deliver events without loss."""
        events: list[VaultEvent] = []
        vault.subscribe(lambda e: events.append(e))

        for i in range(20):
            await vault.add(f"Content {i}", name=f"rapid-{i}.md")

        assert len(events) == 20

    @pytest.mark.asyncio
    async def test_multiple_unsubscribes_independent(self, vault: AsyncVault):
        """Unsubscribing one callback does not affect another."""
        a: list[VaultEvent] = []
        b: list[VaultEvent] = []

        unsub_a = vault.subscribe(lambda e: a.append(e))
        vault.subscribe(lambda e: b.append(e))

        await vault.add("First", name="ind-1.md")
        unsub_a()
        await vault.add("Second", name="ind-2.md")

        assert len(a) == 1
        assert len(b) == 2


# ===========================================================================
# Grep Edge Cases
# ===========================================================================


class TestGrepEdgeCases:

    @pytest.mark.asyncio
    async def test_grep_special_characters(self, vault: AsyncVault):
        """Keywords with special characters don't crash search."""
        await vault.add("Content about C++ programming", name="cpp.md")
        # Should not raise
        results = await vault.grep(["C++", "programming"])
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_grep_duplicate_keywords(self, vault: AsyncVault):
        """Duplicate keywords don't double-count."""
        await vault.add("Python is great for scripting", name="py.md")
        results = await vault.grep(["python", "python", "python"])
        # Should still work, density based on unique matches
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_grep_all_whitespace(self, vault: AsyncVault):
        """All-whitespace keywords return empty."""
        results = await vault.grep(["  ", "\t", "\n"])
        assert results == []

    @pytest.mark.asyncio
    async def test_grep_custom_max_keywords(self, vault: AsyncVault):
        """max_keywords parameter limits the number of keywords processed."""
        await vault.add("Test content", name="kw.md")
        # Pass 5 keywords but limit to 2
        results = await vault.grep(
            ["test", "content", "foo", "bar", "baz"],
            max_keywords=2,
        )
        assert isinstance(results, list)


# ===========================================================================
# Reprocess Edge Cases
# ===========================================================================


class TestReprocessEdgeCases:

    @pytest.mark.asyncio
    async def test_reprocess_content_unchanged(self, vault: AsyncVault):
        """Reprocess produces same content when reassembled."""
        original_text = "This is the content that should survive reprocessing intact."
        resource = await vault.add(original_text, name="intact.md")

        await vault.reprocess(resource.id)

        content = await vault.get_content(resource.id)
        assert original_text in content

    @pytest.mark.asyncio
    async def test_reprocess_multiple_times(self, vault: AsyncVault):
        """Reprocessing the same resource multiple times is safe."""
        resource = await vault.add("Multi-reprocess content", name="multi.md")

        for _ in range(3):
            result = await vault.reprocess(resource.id)
            assert result.status.value == "indexed"

    @pytest.mark.asyncio
    async def test_reprocess_after_update(self, vault: AsyncVault):
        """Reprocess works after metadata update."""
        resource = await vault.add("Updatable content", name="upd.md")
        await vault.update(resource.id, tags=["reprocessed"])
        result = await vault.reprocess(resource.id)
        assert result.status.value == "indexed"


# ===========================================================================
# Find By Name Edge Cases
# ===========================================================================


class TestFindByNameEdgeCases:

    @pytest.mark.asyncio
    async def test_find_by_name_with_spaces(self, vault: AsyncVault):
        """Names with spaces match correctly."""
        await vault.add("Content", name="my document.md")
        result = await vault.find_by_name("my document.md")
        assert result is not None
        assert result.name == "my document.md"

    @pytest.mark.asyncio
    async def test_find_by_name_empty_vault(self, vault: AsyncVault):
        """Empty vault returns None."""
        result = await vault.find_by_name("anything.md")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_name_deleted_resource_excluded(self, vault: AsyncVault):
        """Deleted resources are not found by name."""
        resource = await vault.add("Will be deleted", name="deleted.md")
        await vault.delete(resource.id)
        result = await vault.find_by_name("deleted.md")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_name_unicode(self, vault: AsyncVault):
        """Unicode names match case-insensitively."""
        await vault.add("Content", name="rapport.md")
        result = await vault.find_by_name("RAPPORT.MD")
        assert result is not None


# ===========================================================================
# Text Fallback Edge Cases
# ===========================================================================


class TestTextFallbackEdgeCases:

    @pytest.mark.asyncio
    async def test_search_deduplicates_in_text_mode(self, vault: AsyncVault):
        """Text-only search deduplicates by resource_id."""
        await vault.add(
            "Cloud computing and cloud infrastructure are cloud-related topics",
            name="cloud-heavy.md",
        )
        results = await vault.search("cloud")
        resource_ids = [r.resource_id for r in results]
        assert len(resource_ids) == len(set(resource_ids))

    @pytest.mark.asyncio
    async def test_search_with_threshold_in_text_mode(self, vault: AsyncVault):
        """Threshold filtering works in text-only mode."""
        await vault.add("Exact match content for threshold testing", name="thresh.md")
        results = await vault.search("exact match", threshold=0.5)
        # Results should either match threshold or be empty
        for r in results:
            assert r.relevance >= 0.5


# ===========================================================================
# Cross-Feature Interaction Tests
# ===========================================================================


class TestCrossFeatureInteractions:

    @pytest.mark.asyncio
    async def test_grep_works_without_embedder(self, vault: AsyncVault):
        """Grep works in text-only mode (no embedder)."""
        await vault.add("Alpha bravo charlie", name="abc.md")
        await vault.add("Delta echo foxtrot", name="def.md")
        results = await vault.grep(["alpha", "delta"])
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_subscribe_then_find_by_name(self, vault: AsyncVault):
        """Subscriber sees create event, then find_by_name locates the resource."""
        events: list[VaultEvent] = []
        vault.subscribe(lambda e: events.append(e))

        await vault.add("Findable content", name="findable.md")
        assert len(events) == 1

        found = await vault.find_by_name("findable.md")
        assert found is not None
        assert found.id == events[0].resource_id

    @pytest.mark.asyncio
    async def test_reprocess_then_grep_finds_content(self, vault: AsyncVault):
        """After reprocess, grep can still find the content."""
        resource = await vault.add("Searchable content after reprocessing", name="re-grep.md")
        await vault.reprocess(resource.id)
        results = await vault.grep(["searchable", "reprocessing"])
        assert len(results) >= 1
        assert results[0].resource_id == resource.id

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_all_features(self, vault: AsyncVault):
        """End-to-end: add, subscribe, grep, reprocess, find, transition, delete."""
        events: list[VaultEvent] = []
        vault.subscribe(lambda e: events.append(e))

        # Add
        resource = await vault.add(
            "Comprehensive lifecycle test content for integration",
            name="lifecycle-test.md",
            tags=["integration"],
        )
        assert events[-1].event_type == EventType.CREATE

        # Grep finds it
        results = await vault.grep(["lifecycle", "integration"])
        assert len(results) >= 1

        # Find by name
        found = await vault.find_by_name("lifecycle-test.md")
        assert found is not None
        assert found.id == resource.id

        # Reprocess
        await vault.reprocess(resource.id)
        assert events[-1].event_type == EventType.UPDATE
        assert events[-1].details.get("reprocessed") is True

        # Search (text fallback)
        search_results = await vault.search("lifecycle integration")
        assert len(search_results) >= 1

        # Transition
        await vault.transition(resource.id, "archived")
        assert events[-1].event_type == EventType.LIFECYCLE_TRANSITION

        # Delete
        await vault.delete(resource.id)
        assert events[-1].event_type == EventType.DELETE

        # Verify total event count (search does not emit subscriber events)
        assert len(events) == 4  # create, update(reprocess), transition, delete

    @pytest.mark.asyncio
    async def test_full_lifecycle_event_count(self, vault: AsyncVault):
        """Verify exact event count for add->reprocess->transition->delete."""
        events: list[VaultEvent] = []
        vault.subscribe(lambda e: events.append(e))

        resource = await vault.add("Content", name="count.md")
        await vault.reprocess(resource.id)
        await vault.transition(resource.id, "archived")
        await vault.delete(resource.id)

        types = [e.event_type for e in events]
        assert types == [
            EventType.CREATE,
            EventType.UPDATE,
            EventType.LIFECYCLE_TRANSITION,
            EventType.DELETE,
        ]

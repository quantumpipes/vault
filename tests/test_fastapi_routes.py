"""Tests for FastAPI routes integration."""

from __future__ import annotations

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qp_vault import AsyncVault
    from qp_vault.integrations.fastapi_routes import create_vault_router
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

pytestmark = pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")


@pytest.fixture
def client(tmp_path):
    vault = AsyncVault(tmp_path / "api-vault")
    app = FastAPI()
    router = create_vault_router(vault)
    app.include_router(router, prefix="/v1/vault")
    return TestClient(app)


@pytest.fixture
def populated_client(client):
    """Client with some resources added."""
    client.post("/v1/vault/resources", json={
        "content": "Incident response SOP for critical outages.",
        "name": "sop-incident.md",
        "trust": "canonical",
    })
    client.post("/v1/vault/resources", json={
        "content": "Draft onboarding process improvements.",
        "name": "draft-onboard.md",
        "trust": "working",
    })
    return client


class TestResourceEndpoints:
    def test_add_resource(self, client):
        resp = client.post("/v1/vault/resources", json={
            "content": "Hello world",
            "name": "hello.md",
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["name"] == "hello.md"
        assert data["status"] == "indexed"

    def test_list_resources(self, populated_client):
        resp = populated_client.get("/v1/vault/resources")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2

    def test_get_resource(self, client):
        add_resp = client.post("/v1/vault/resources", json={
            "content": "Test content",
            "name": "test.md",
        })
        resource_id = add_resp.json()["data"]["id"]

        resp = client.get(f"/v1/vault/resources/{resource_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == resource_id

    def test_get_nonexistent(self, client):
        resp = client.get("/v1/vault/resources/nonexistent")
        assert resp.status_code == 404

    def test_update_resource(self, client):
        add_resp = client.post("/v1/vault/resources", json={
            "content": "Original",
            "name": "orig.md",
        })
        resource_id = add_resp.json()["data"]["id"]

        resp = client.put(f"/v1/vault/resources/{resource_id}", json={
            "trust": "canonical",
            "tags": ["important"],
        })
        assert resp.status_code == 200

    def test_delete_resource(self, client):
        add_resp = client.post("/v1/vault/resources", json={
            "content": "To delete",
            "name": "delete.md",
        })
        resource_id = add_resp.json()["data"]["id"]

        resp = client.delete(f"/v1/vault/resources/{resource_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] is True


class TestSearchEndpoint:
    def test_search(self, populated_client):
        resp = populated_client.post("/v1/vault/search", json={
            "query": "incident response",
            "top_k": 5,
        })
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_search_empty(self, client):
        resp = client.post("/v1/vault/search", json={
            "query": "nonexistent_topic_xyz",
        })
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestVerifyEndpoints:
    def test_verify_all(self, populated_client):
        resp = populated_client.get("/v1/vault/verify")
        assert resp.status_code == 200
        assert resp.json()["data"]["passed"] is True

    def test_verify_resource(self, client):
        add_resp = client.post("/v1/vault/resources", json={
            "content": "Verify me",
            "name": "verify.md",
        })
        resource_id = add_resp.json()["data"]["id"]

        resp = client.get(f"/v1/vault/resources/{resource_id}/verify")
        assert resp.status_code == 200
        assert resp.json()["data"]["passed"] is True


class TestHealthAndStatus:
    def test_health(self, populated_client):
        resp = populated_client.get("/v1/vault/health")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "overall" in data
        assert 0 <= data["overall"] <= 100

    def test_status(self, populated_client):
        resp = populated_client.get("/v1/vault/status")
        assert resp.status_code == 200
        assert resp.json()["data"]["total_resources"] == 2


class TestLifecycleEndpoints:
    def test_transition(self, client):
        add_resp = client.post("/v1/vault/resources", json={
            "content": "Draft doc",
            "name": "draft.md",
            "lifecycle": "draft",
        })
        resource_id = add_resp.json()["data"]["id"]

        resp = client.post(f"/v1/vault/resources/{resource_id}/transition", json={
            "target": "review",
        })
        assert resp.status_code == 200

    def test_invalid_transition(self, client):
        add_resp = client.post("/v1/vault/resources", json={
            "content": "Active doc",
            "name": "active.md",
        })
        resource_id = add_resp.json()["data"]["id"]

        resp = client.post(f"/v1/vault/resources/{resource_id}/transition", json={
            "target": "draft",  # ACTIVE -> DRAFT not allowed
        })
        assert resp.status_code == 409  # Conflict: invalid lifecycle transition

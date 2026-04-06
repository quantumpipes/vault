"""Advanced FastAPI route tests: lifecycle, proof, chain, expiring."""

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
    vault = AsyncVault(tmp_path / "api-adv")
    app = FastAPI()
    router = create_vault_router(vault)
    app.include_router(router, prefix="/v1/vault")
    return TestClient(app)


class TestSupersessionEndpoint:
    def test_supersede(self, client):
        r1 = client.post("/v1/vault/resources", json={"content": "Policy v1", "name": "v1.md"})
        r2 = client.post("/v1/vault/resources", json={"content": "Policy v2", "name": "v2.md"})
        id1 = r1.json()["data"]["id"]
        id2 = r2.json()["data"]["id"]

        resp = client.post(f"/v1/vault/resources/{id1}/supersede", json={"new_id": id2})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["old"]["lifecycle"] == "superseded"

    def test_supersede_nonexistent(self, client):
        r1 = client.post("/v1/vault/resources", json={"content": "Doc", "name": "d.md"})
        id1 = r1.json()["data"]["id"]
        resp = client.post(f"/v1/vault/resources/{id1}/supersede", json={"new_id": "nonexistent"})
        assert resp.status_code == 404


class TestChainEndpoint:
    def test_chain(self, client):
        r1 = client.post("/v1/vault/resources", json={"content": "v1", "name": "v1.md"})
        r2 = client.post("/v1/vault/resources", json={"content": "v2", "name": "v2.md"})
        id1 = r1.json()["data"]["id"]
        id2 = r2.json()["data"]["id"]
        client.post(f"/v1/vault/resources/{id1}/supersede", json={"new_id": id2})

        resp = client.get(f"/v1/vault/resources/{id1}/chain")
        assert resp.status_code == 200
        assert resp.json()["meta"]["length"] == 2


class TestProofEndpoint:
    def test_export_proof(self, client):
        r = client.post("/v1/vault/resources", json={"content": "Provable", "name": "prove.md"})
        rid = r.json()["data"]["id"]

        resp = client.get(f"/v1/vault/resources/{rid}/proof")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["resource_id"] == rid
        assert data["merkle_root"]
        assert data["tree_size"] >= 1

    def test_proof_nonexistent(self, client):
        # Need at least one resource for vault to not be empty
        client.post("/v1/vault/resources", json={"content": "Exists", "name": "e.md"})
        resp = client.get("/v1/vault/resources/nonexistent/proof")
        assert resp.status_code == 404


class TestExpiringEndpoint:
    def test_expiring_empty(self, client):
        resp = client.get("/v1/vault/expiring?days=90")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestLifecycleTransitionChain:
    def test_full_lifecycle(self, client):
        r = client.post("/v1/vault/resources", json={
            "content": "Full lifecycle doc", "name": "full.md", "lifecycle": "draft",
        })
        rid = r.json()["data"]["id"]

        # DRAFT -> REVIEW
        resp = client.post(f"/v1/vault/resources/{rid}/transition", json={"target": "review"})
        assert resp.status_code == 200

        # REVIEW -> ACTIVE
        resp = client.post(f"/v1/vault/resources/{rid}/transition", json={"target": "active"})
        assert resp.status_code == 200

        # ACTIVE -> ARCHIVED
        resp = client.post(f"/v1/vault/resources/{rid}/transition", json={"target": "archived"})
        assert resp.status_code == 200

        # ARCHIVED -> anything (terminal)
        resp = client.post(f"/v1/vault/resources/{rid}/transition", json={"target": "active"})
        assert resp.status_code == 409


class TestErrorSanitization:
    def test_internal_errors_not_leaked(self, client):
        """Error responses should not expose internal details."""
        resp = client.get("/v1/vault/resources/nonexistent")
        assert resp.status_code == 404
        # Should NOT contain stack traces or internal paths
        detail = resp.json()["detail"]
        assert "Traceback" not in detail
        assert "/Users/" not in detail

"""Cross-tenant retrieval-leak (IDOR) regression tests for by-id accessors.

Direct-by-id methods (``get``, ``get_content``, ``chain``, ``export_proof`` ...)
do not carry a tenant filter. On a tenant-locked vault that previously let an
operator read, mutate, or prove the existence of *any* resource whose id they
could name, regardless of which tenant owned it. These tests pin the fix:
a tenant-locked vault treats a foreign resource exactly like a missing id.

The seed/read split (unlocked writer, locked reader, same storage path) models
the real deployment: one ingest vault writes many tenants, per-operator locked
vaults read the shared store.
"""

from __future__ import annotations

import pytest

from qp_vault import Vault, VaultError


@pytest.fixture
def shared_path(tmp_path):
    """Storage directory shared by an unlocked seeder and a locked reader."""
    return tmp_path / "shared-vault"


@pytest.fixture
def seeded(shared_path):
    """Seed two tenants' resources via an unlocked vault; return their ids."""
    seeder = Vault(shared_path)
    a = seeder.add("Tenant A restricted content", name="a.md", tenant_id="tenant-a")
    b = seeder.add("Tenant B restricted content", name="b.md", tenant_id="tenant-b")
    return {"a_id": a.id, "b_id": b.id}


@pytest.fixture
def locked_a(shared_path, seeded):
    """A vault locked to tenant-a over the same storage as the seeder."""
    return Vault(shared_path, tenant_id="tenant-a")


class TestByIdTenantIsolation:
    def test_get_own_tenant_resource_succeeds(self, locked_a, seeded):
        r = locked_a.get(seeded["a_id"])
        assert r.tenant_id == "tenant-a"

    def test_get_foreign_tenant_resource_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.get(seeded["b_id"])

    def test_get_content_foreign_tenant_blocked(self, locked_a, seeded):
        # The actual leak: reading another tenant's plaintext by id.
        with pytest.raises(VaultError):
            locked_a.get_content(seeded["b_id"])

    def test_get_content_own_tenant_succeeds(self, locked_a, seeded):
        assert "Tenant A restricted" in locked_a.get_content(seeded["a_id"])

    def test_get_multiple_drops_foreign_tenant(self, locked_a, seeded):
        results = locked_a.get_multiple([seeded["a_id"], seeded["b_id"]])
        ids = {r.id for r in results}
        assert seeded["a_id"] in ids
        assert seeded["b_id"] not in ids

    def test_update_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.update(seeded["b_id"], name="hijacked.md")

    def test_delete_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.delete(seeded["b_id"])

    def test_transition_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.transition(seeded["b_id"], "archived")

    def test_chain_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.chain(seeded["b_id"])

    def test_provenance_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.get_provenance(seeded["b_id"])

    def test_set_adversarial_status_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.set_adversarial_status(seeded["b_id"], "verified")

    def test_export_proof_foreign_tenant_blocked(self, locked_a, seeded):
        # A Merkle proof would both confirm existence and leak the leaf hash.
        with pytest.raises(VaultError):
            locked_a.export_proof(seeded["b_id"])

    def test_verify_foreign_tenant_blocked(self, locked_a, seeded):
        with pytest.raises(VaultError):
            locked_a.verify(seeded["b_id"])

    def test_export_vault_scoped_to_locked_tenant(self, locked_a, seeded, tmp_path):
        # A locked operator's export must not contain another tenant's data.
        out = tmp_path / "export.json"
        result = locked_a.export_vault(str(out))
        import json

        data = json.loads(out.read_text())
        names = {r.get("name") for r in data["resources"]}
        assert "a.md" in names
        assert "b.md" not in names
        assert result["resource_count"] == 1

    def test_export_vault_unlocked_includes_all_tenants(self, shared_path, seeded, tmp_path):
        admin = Vault(shared_path)
        out = tmp_path / "export-all.json"
        admin.export_vault(str(out))
        import json

        data = json.loads(out.read_text())
        names = {r.get("name") for r in data["resources"]}
        assert {"a.md", "b.md"} <= names

    def test_unlocked_vault_unaffected(self, shared_path, seeded):
        # No lock => existing cross-tenant admin behavior is preserved.
        admin = Vault(shared_path)
        assert admin.get(seeded["a_id"]).id == seeded["a_id"]
        assert admin.get(seeded["b_id"]).id == seeded["b_id"]
        both = admin.get_multiple([seeded["a_id"], seeded["b_id"]])
        assert len(both) == 2

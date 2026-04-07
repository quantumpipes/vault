"""Tests for knowledge lifecycle engine."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from qp_vault import LifecycleError, Vault, VaultError


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "lifecycle-vault")


class TestLifecycleTransitions:
    def test_draft_to_review(self, vault):
        r = vault.add("Draft doc", lifecycle="draft", name="draft.md")
        updated = vault.transition(r.id, "review")
        assert updated.lifecycle == "review"

    def test_draft_to_active(self, vault):
        r = vault.add("Draft doc", lifecycle="draft", name="draft.md")
        updated = vault.transition(r.id, "active")
        assert updated.lifecycle == "active"

    def test_review_to_active(self, vault):
        r = vault.add("Doc", lifecycle="review", name="review.md")
        updated = vault.transition(r.id, "active")
        assert updated.lifecycle == "active"

    def test_review_back_to_draft(self, vault):
        r = vault.add("Doc", lifecycle="review", name="review.md")
        updated = vault.transition(r.id, "draft")
        assert updated.lifecycle == "draft"

    def test_active_to_archived(self, vault):
        r = vault.add("Doc", lifecycle="active", name="active.md")
        updated = vault.transition(r.id, "archived")
        assert updated.lifecycle == "archived"

    def test_expired_to_active(self, vault):
        """Expired resources can be re-activated."""
        r = vault.add("Doc", lifecycle="active", name="doc.md")
        vault.transition(r.id, "expired")
        updated = vault.transition(r.id, "active")
        assert updated.lifecycle == "active"

    def test_archived_is_terminal(self, vault):
        r = vault.add("Doc", lifecycle="active", name="doc.md")
        vault.transition(r.id, "archived")
        with pytest.raises(LifecycleError, match="terminal"):
            vault.transition(r.id, "active")

    def test_invalid_transition_raises(self, vault):
        r = vault.add("Doc", lifecycle="active", name="doc.md")
        with pytest.raises(LifecycleError, match="Cannot transition"):
            vault.transition(r.id, "draft")  # ACTIVE -> DRAFT not allowed

    def test_invalid_transition_active_to_review(self, vault):
        r = vault.add("Doc", lifecycle="active", name="doc.md")
        with pytest.raises(LifecycleError):
            vault.transition(r.id, "review")

    def test_nonexistent_resource_raises(self, vault):
        with pytest.raises(VaultError, match="not found"):
            vault.transition("nonexistent", "active")

    def test_transition_with_reason(self, vault):
        r = vault.add("Doc", lifecycle="draft", name="doc.md")
        updated = vault.transition(r.id, "active", reason="Approved by lead")
        assert updated.lifecycle == "active"


class TestSupersession:
    def test_supersede(self, vault):
        v1 = vault.add("Policy v1", name="policy-v1.md", trust_tier="canonical")
        v2 = vault.add("Policy v2", name="policy-v2.md", trust_tier="canonical")

        old, new = vault.supersede(v1.id, v2.id)

        assert old.lifecycle == "superseded"
        assert old.superseded_by == v2.id
        assert new.supersedes == v1.id

    def test_chain_returns_ordered(self, vault):
        v1 = vault.add("Policy v1", name="v1.md")
        v2 = vault.add("Policy v2", name="v2.md")
        v3 = vault.add("Policy v3", name="v3.md")

        vault.supersede(v1.id, v2.id)
        vault.supersede(v2.id, v3.id)

        chain = vault.chain(v1.id)
        assert len(chain) == 3
        assert chain[0].id == v1.id
        assert chain[1].id == v2.id
        assert chain[2].id == v3.id

    def test_chain_from_middle(self, vault):
        v1 = vault.add("v1", name="v1.md")
        v2 = vault.add("v2", name="v2.md")
        v3 = vault.add("v3", name="v3.md")

        vault.supersede(v1.id, v2.id)
        vault.supersede(v2.id, v3.id)

        chain = vault.chain(v2.id)
        assert len(chain) == 3

    def test_chain_single_resource(self, vault):
        r = vault.add("Solo", name="solo.md")
        chain = vault.chain(r.id)
        assert len(chain) == 1
        assert chain[0].id == r.id


class TestExpiration:
    def test_expiring_within_window(self, vault):
        future = date.today() + timedelta(days=30)
        r = vault.add("Expiring doc", name="expiring.md",
                       valid_from=date.today(), valid_until=future)
        expiring = vault.expiring(days=90)
        ids = [e.id for e in expiring]
        assert r.id in ids

    def test_not_expiring_outside_window(self, vault):
        far_future = date.today() + timedelta(days=365)
        vault.add("Far doc", name="far.md",
                   valid_from=date.today(), valid_until=far_future)
        expiring = vault.expiring(days=90)
        assert len(expiring) == 0

    def test_no_valid_until_not_expiring(self, vault):
        vault.add("Forever doc", name="forever.md")
        expiring = vault.expiring(days=90)
        assert len(expiring) == 0


class TestExportProof:
    def test_export_proof(self, vault):
        r1 = vault.add("Resource 1", name="r1.md")
        vault.add("Resource 2", name="r2.md")

        proof = vault.export_proof(r1.id)
        assert proof.resource_id == r1.id
        assert proof.resource_hash
        assert proof.merkle_root
        assert proof.tree_size == 2
        assert len(proof.path) > 0

    def test_export_proof_verifiable(self, vault):
        """Exported proof should be verifiable against the Merkle root."""
        from qp_vault.core.hasher import verify_merkle_proof

        r1 = vault.add("Resource 1", name="r1.md")
        vault.add("Resource 2", name="r2.md")
        vault.add("Resource 3", name="r3.md")

        proof = vault.export_proof(r1.id)
        assert verify_merkle_proof(proof.resource_hash, proof.path, proof.merkle_root)

    def test_export_proof_nonexistent_raises(self, vault):
        vault.add("Resource", name="r.md")
        with pytest.raises(VaultError, match="not found"):
            vault.export_proof("nonexistent")

    def test_export_proof_empty_vault_raises(self, vault):
        with pytest.raises(VaultError, match="empty"):
            vault.export_proof("any-id")

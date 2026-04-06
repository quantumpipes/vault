"""Advanced Vault tests: file operations, embedder integration, edge cases."""

from __future__ import annotations

import hashlib

import pytest

from qp_vault import AsyncVault, Vault


class MockEmbedder:
    @property
    def dimensions(self) -> int:
        return 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [float(b) / 255 for b in hashlib.sha256(t.encode()).digest()[:4]]
            for t in texts
        ]


@pytest.fixture
def vault(tmp_path):
    return Vault(tmp_path / "adv-vault")


@pytest.fixture
def vault_with_embedder(tmp_path):
    return Vault(tmp_path / "embed-vault", embedder=MockEmbedder())


class TestFileAdd:
    def test_add_from_file_path(self, vault, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("# Hello\n\nContent from a file.")
        r = vault.add(f)
        assert r.name == "doc.md"
        assert r.chunk_count >= 1

    def test_add_from_string_path(self, vault, tmp_path):
        f = tmp_path / "doc.txt"
        f.write_text("Text file content.")
        r = vault.add(str(f))
        assert r.name == "doc.txt"

    def test_add_from_bytes(self, vault):
        r = vault.add(b"Bytes content", name="bytes.md")
        assert r.chunk_count >= 1

    def test_add_string_treated_as_content(self, vault):
        r = vault.add("This is just text, not a file path", name="text.md")
        assert r.chunk_count >= 1

    def test_auto_detect_name_from_path(self, vault, tmp_path):
        f = tmp_path / "auto-named.md"
        f.write_text("Content")
        r = vault.add(f)
        assert r.name == "auto-named.md"


class TestEmbedderIntegration:
    def test_search_with_embeddings(self, vault_with_embedder):
        vault_with_embedder.add("Incident response procedure for critical outages", name="sop.md")
        vault_with_embedder.add("Onboarding process for new employees", name="onboard.md")
        results = vault_with_embedder.search("incident response")
        assert len(results) > 0

    def test_embedder_registration(self, vault):
        vault.register_embedder(MockEmbedder())
        r = vault.add("Embedded content", name="embed.md")
        assert r.chunk_count >= 1


class TestVaultEdgeCases:
    def test_add_unicode_content(self, vault):
        r = vault.add("\u4e16\u754c\u4f60\u597d \u00e9\u00e8\u00ea \u2603\ufe0f", name="unicode.md")
        assert r.chunk_count >= 1

    def test_add_very_short_content(self, vault):
        r = vault.add("Hi", name="short.md")
        assert r.chunk_count >= 1

    def test_multiple_vaults_independent(self, tmp_path):
        v1 = Vault(tmp_path / "vault1")
        v2 = Vault(tmp_path / "vault2")
        v1.add("V1 content", name="v1.md")
        v2.add("V2 content", name="v2.md")
        assert len(v1.list()) == 1
        assert len(v2.list()) == 1

    def test_vault_creates_directory(self, tmp_path):
        path = tmp_path / "new" / "deep" / "vault"
        v = Vault(path)
        v.add("Content", name="doc.md")
        assert path.exists()

    def test_list_with_offset(self, vault):
        for i in range(10):
            vault.add(f"Resource {i}", name=f"r{i}.md")
        page1 = vault.list(limit=5, offset=0)
        page2 = vault.list(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert ids1.isdisjoint(ids2)  # No overlap


class TestVaultAutoExpiration:
    @pytest.mark.asyncio
    async def test_check_expirations(self, tmp_path):
        from datetime import date, timedelta
        vault = AsyncVault(tmp_path / "expire-vault")
        # Add a resource that expired yesterday
        yesterday = date.today() - timedelta(days=1)
        r = await vault.add(
            "Expired policy",
            name="expired.md",
            valid_from=date(2020, 1, 1),
            valid_until=yesterday,
        )

        # Run expiration check
        expired = await vault._lifecycle.check_expirations()
        expired_ids = [e.id for e in expired]
        assert r.id in expired_ids

    @pytest.mark.asyncio
    async def test_future_not_expired(self, tmp_path):
        from datetime import date, timedelta
        vault = AsyncVault(tmp_path / "future-vault")
        future = date.today() + timedelta(days=365)
        await vault.add("Future policy", name="future.md", valid_until=future)

        expired = await vault._lifecycle.check_expirations()
        assert len(expired) == 0


class TestVaultRestore:
    def test_restore_after_soft_delete(self, vault):
        r = vault.add("Restorable", name="restore.md")
        vault.delete(r.id)
        # Should be deleted
        deleted = vault.list(status="deleted")
        assert len(deleted) == 1

        # TODO: restore requires the Vault sync wrapper
        # which isn't implemented yet for restore
        # This documents the gap


class TestVaultConcurrency:
    def test_sequential_adds_no_conflict(self, vault):
        """Multiple sequential adds should not conflict."""
        for i in range(20):
            vault.add(f"Content {i}", name=f"doc{i}.md")
        assert len(vault.list(limit=100)) == 20

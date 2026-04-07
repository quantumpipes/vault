"""Tests to close coverage gaps across all testable modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault import Vault
from qp_vault.config import VaultConfig
from qp_vault.exceptions import LifecycleError, VaultError

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# Zeroize (encryption/zeroize.py)
# =============================================================================


class TestZeroize:
    def test_zeroize_clears_data(self) -> None:
        from qp_vault.encryption.zeroize import zeroize

        data = bytearray(b"secret key material 1234567890ab")
        zeroize(data)
        assert all(b == 0 for b in data)

    def test_zeroize_empty(self) -> None:
        from qp_vault.encryption.zeroize import zeroize

        data = bytearray(b"")
        zeroize(data)
        assert len(data) == 0

    def test_zeroize_large(self) -> None:
        from qp_vault.encryption.zeroize import zeroize

        data = bytearray(b"\xff" * 10000)
        zeroize(data)
        assert all(b == 0 for b in data)


# =============================================================================
# Capsule Auditor
# =============================================================================


class TestCapsuleAuditor:
    def test_capsule_available(self) -> None:
        from qp_vault.audit.capsule_auditor import HAS_CAPSULE

        if HAS_CAPSULE:
            from qp_vault.audit.capsule_auditor import CapsuleAuditor

            auditor = CapsuleAuditor()
            assert auditor is not None

    @pytest.mark.asyncio
    async def test_capsule_auditor_record(self) -> None:
        from qp_vault.audit.capsule_auditor import HAS_CAPSULE

        if not HAS_CAPSULE:
            pytest.skip("qp-capsule not installed")

        from datetime import UTC, datetime

        from qp_vault.audit.capsule_auditor import CapsuleAuditor
        from qp_vault.enums import EventType
        from qp_vault.models import VaultEvent

        auditor = CapsuleAuditor()
        event = VaultEvent(
            event_type=EventType.CREATE,
            resource_id="test-r1",
            resource_name="test.md",
            resource_hash="abc123",
            timestamp=datetime.now(tz=UTC),
        )
        result = await auditor.record(event)
        assert result


# =============================================================================
# Sentence Transformer Embedder
# =============================================================================


class TestSentenceEmbedder:
    def test_init(self) -> None:
        from qp_vault.embeddings.sentence import HAS_ST

        if not HAS_ST:
            pytest.skip("sentence-transformers not installed")
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()
        assert e.dimensions > 0

    @pytest.mark.asyncio
    async def test_embed(self) -> None:
        from qp_vault.embeddings.sentence import HAS_ST

        if not HAS_ST:
            pytest.skip("sentence-transformers not installed")
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()
        vecs = await e.embed(["hello world", "test"])
        assert len(vecs) == 2
        assert len(vecs[0]) == e.dimensions


# =============================================================================
# OpenAI Embedder (structure only)
# =============================================================================


class TestOpenAIEmbedder:
    def test_init(self) -> None:
        from qp_vault.embeddings.openai import HAS_OPENAI

        if not HAS_OPENAI:
            pytest.skip("openai not installed")
        from qp_vault.embeddings.openai import OpenAIEmbedder

        e = OpenAIEmbedder(api_key="test-key")
        assert e.dimensions == 1536

    def test_dimensions_large(self) -> None:
        from qp_vault.embeddings.openai import HAS_OPENAI

        if not HAS_OPENAI:
            pytest.skip("openai not installed")
        from qp_vault.embeddings.openai import OpenAIEmbedder

        e = OpenAIEmbedder(model="text-embedding-3-large", api_key="test-key")
        assert e.dimensions == 3072


# =============================================================================
# Docling Parser
# =============================================================================


class TestDoclingParser:
    def test_init(self) -> None:
        from qp_vault.processing.docling_parser import HAS_DOCLING

        if not HAS_DOCLING:
            pytest.skip("docling not installed")
        from qp_vault.processing.docling_parser import DOCLING_EXTENSIONS, DoclingParser

        p = DoclingParser()
        assert p.supported_extensions == DOCLING_EXTENSIONS


# =============================================================================
# Search Engine
# =============================================================================


class TestSearchEngineGaps:
    def test_adversarial_multiplier_verified(self) -> None:
        from qp_vault.core.search_engine import compute_adversarial_multiplier

        assert compute_adversarial_multiplier("verified") == 1.0

    def test_adversarial_multiplier_suspicious(self) -> None:
        from qp_vault.core.search_engine import compute_adversarial_multiplier

        assert compute_adversarial_multiplier("suspicious") == 0.3

    def test_adversarial_multiplier_unknown(self) -> None:
        from qp_vault.core.search_engine import compute_adversarial_multiplier

        assert compute_adversarial_multiplier("other") == 0.7


# =============================================================================
# Lifecycle
# =============================================================================


class TestLifecycleGaps:
    def test_transition_same_state(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "lc1")
        r = vault.add("Doc", name="d.md")
        with pytest.raises(LifecycleError):
            vault.transition(r.id, "active")

    def test_chain_single(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "lc2")
        r = vault.add("Doc", name="d.md")
        assert len(vault.chain(r.id)) == 1

    def test_expiring_empty(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "lc3")
        vault.add("Doc", name="d.md")
        assert len(vault.expiring(days=30)) == 0


# =============================================================================
# Vault Input Validation (remaining branches)
# =============================================================================


class TestVaultValidation:
    def test_bytes_source(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "b")
        r = vault.add(b"Binary", name="b.bin")
        assert r.name == "b.bin"

    def test_long_string_not_path(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "l")
        assert vault.add("x" * 5000).id

    def test_invalid_trust(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "t")
        with pytest.raises(VaultError):
            vault.add("Doc", trust_tier="bad")

    def test_invalid_lifecycle(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "t2")
        with pytest.raises(VaultError):
            vault.add("Doc", lifecycle="bad")

    def test_path_traversal_name(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "pt")
        r = vault.add("Content", name="../../etc/passwd")
        assert ".." not in r.name

    def test_null_byte_name(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "n")
        r = vault.add("Content", name="f\x00oo.md")
        assert "\x00" not in r.name

    def test_too_many_tags(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "tg")
        with pytest.raises(VaultError):
            vault.add("Doc", tags=["t"] * 100)

    def test_tag_too_long(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "tl")
        with pytest.raises(VaultError):
            vault.add("Doc", tags=["x" * 200])

    def test_metadata_key_long(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "mk")
        with pytest.raises(VaultError):
            vault.add("Doc", metadata={"x" * 200: "v"})

    def test_metadata_key_invalid(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "mi")
        with pytest.raises(VaultError):
            vault.add("Doc", metadata={"bad key": "v"})

    def test_metadata_value_large(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "mv")
        with pytest.raises(VaultError):
            vault.add("Doc", metadata={"k": "x" * 20000})

    def test_max_file_size(self, tmp_path: Path) -> None:
        config = VaultConfig(max_file_size_mb=0)
        vault = Vault(tmp_path / "fs", config=config)
        with pytest.raises(VaultError):
            vault.add("Content")


# =============================================================================
# Vault Operations (remaining branches)
# =============================================================================


class TestVaultOps:
    def test_verify_single(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "v")
        r = vault.add("Doc", name="d.md")
        result = vault.verify(r.id)
        assert result is not None

    def test_verify_vault(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "v2")
        vault.add("Doc", name="d.md")
        assert hasattr(vault.verify(), "merkle_root")

    def test_search_explain(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "e")
        vault.add("Explain test", name="e.md")
        assert isinstance(vault.search("explain", explain=True), list)

    def test_export_proof(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "ep")
        r = vault.add("Doc", name="d.md")
        proof = vault.export_proof(r.id)
        assert proof.resource_id == r.id

    def test_health_empty(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "he")
        assert vault.health().overall >= 0


# =============================================================================
# AES-GCM Edges
# =============================================================================


class TestAESEdges:
    def test_decrypt_short(self) -> None:
        from qp_vault.encryption.aes_gcm import AESGCMEncryptor

        with pytest.raises(ValueError, match="too short"):
            AESGCMEncryptor().decrypt(b"short")

    def test_decrypt_wrong_key(self) -> None:
        from qp_vault.encryption.aes_gcm import AESGCMEncryptor

        ct = AESGCMEncryptor().encrypt(b"secret")
        with pytest.raises(ValueError):
            AESGCMEncryptor().decrypt(ct)

    def test_aad_roundtrip(self) -> None:
        from qp_vault.encryption.aes_gcm import AESGCMEncryptor

        enc = AESGCMEncryptor()
        ct = enc.encrypt(b"data", associated_data=b"aad")
        assert enc.decrypt(ct, associated_data=b"aad") == b"data"


# =============================================================================
# Provenance
# =============================================================================


class TestProvenanceGaps:
    def test_validate_id_empty(self) -> None:
        from qp_vault.provenance import _validate_id

        with pytest.raises(ValueError):
            _validate_id("", "x")

    def test_validate_id_long(self) -> None:
        from qp_vault.provenance import _validate_id

        with pytest.raises(ValueError):
            _validate_id("x" * 200, "x")


# =============================================================================
# RBAC
# =============================================================================


class TestRBACGaps:
    def test_unknown_role(self) -> None:
        from qp_vault.rbac import check_permission

        with pytest.raises(ValueError):
            check_permission("bad_role", "add")


# =============================================================================
# Config
# =============================================================================


class TestConfigGaps:
    def test_from_toml(self, tmp_path: Path) -> None:
        p = tmp_path / "c.toml"
        p.write_text("[limits]\nmax_file_size_mb = 50\n")
        config = VaultConfig.from_toml(p)
        assert config.max_file_size_mb == 50


# =============================================================================
# Plugins
# =============================================================================


class TestPluginGaps:
    @pytest.mark.asyncio
    async def test_fire_hooks_empty(self) -> None:
        from qp_vault.plugins.registry import PluginRegistry

        await PluginRegistry().fire_hooks("pre_index")

    def test_entry_points_no_crash(self) -> None:
        from qp_vault.plugins.registry import PluginRegistry

        PluginRegistry().discover_entry_points()


# =============================================================================
# Ollama Screener Parse
# =============================================================================


class TestOllamaGaps:
    def test_parse_none(self) -> None:
        from qp_vault.membrane.screeners.ollama import OllamaScreener

        r = OllamaScreener._parse_response(None)  # type: ignore[arg-type]
        assert r.risk_score == 0.0

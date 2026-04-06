"""Tests for VaultConfig."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault.config import LayerDefaults, VaultConfig

if TYPE_CHECKING:
    from pathlib import Path


class TestVaultConfigDefaults:
    def test_default_backend(self):
        c = VaultConfig()
        assert c.backend == "sqlite"

    def test_default_chunk_settings(self):
        c = VaultConfig()
        assert c.chunk_target_tokens == 512
        assert c.chunk_min_tokens == 100
        assert c.chunk_max_tokens == 1024
        assert c.chunk_overlap_tokens == 50

    def test_default_search_weights(self):
        c = VaultConfig()
        assert c.vector_weight == 0.7
        assert c.text_weight == 0.3

    def test_default_trust_weights(self):
        c = VaultConfig()
        assert c.trust_weights["canonical"] == 1.5
        assert c.trust_weights["working"] == 1.0
        assert c.trust_weights["ephemeral"] == 0.7
        assert c.trust_weights["archived"] == 0.25

    def test_default_freshness_half_life(self):
        c = VaultConfig()
        assert c.freshness_half_life["canonical"] == 365
        assert c.freshness_half_life["ephemeral"] == 30

    def test_default_layer_defaults(self):
        c = VaultConfig()
        assert "operational" in c.layer_defaults
        assert "strategic" in c.layer_defaults
        assert "compliance" in c.layer_defaults
        assert c.layer_defaults["compliance"].audit_reads is True

    def test_default_max_file_size(self):
        c = VaultConfig()
        assert c.max_file_size_mb == 500


class TestVaultConfigCustom:
    def test_custom_backend(self):
        c = VaultConfig(backend="postgres", postgres_dsn="postgresql://localhost/test")
        assert c.backend == "postgres"
        assert c.postgres_dsn == "postgresql://localhost/test"

    def test_custom_chunk_settings(self):
        c = VaultConfig(chunk_target_tokens=256, chunk_overlap_tokens=25)
        assert c.chunk_target_tokens == 256
        assert c.chunk_overlap_tokens == 25

    def test_custom_trust_weights(self):
        c = VaultConfig(trust_weights={"canonical": 2.0, "working": 1.0, "ephemeral": 0.5, "archived": 0.1})
        assert c.trust_weights["canonical"] == 2.0


class TestVaultConfigToml:
    def test_load_from_toml(self, tmp_path: Path):
        import sys
        has_toml = sys.version_info >= (3, 11)
        if not has_toml:
            try:
                import tomli  # noqa: F401
                has_toml = True
            except ImportError:
                pass

        if not has_toml:
            pytest.skip("TOML loading requires Python 3.11+ or tomli package")

        toml_file = tmp_path / "vault.toml"
        toml_file.write_text("""
[storage]
backend = "postgres"
postgres_dsn = "postgresql://localhost/test"

[chunking]
chunk_target_tokens = 256

[search]
vector_weight = 0.8
text_weight = 0.2
""")
        c = VaultConfig.from_toml(toml_file)
        assert c.backend == "postgres"
        assert c.chunk_target_tokens == 256
        assert c.vector_weight == 0.8


class TestLayerDefaults:
    def test_defaults(self):
        ld = LayerDefaults()
        assert ld.trust == "working"
        assert ld.half_life_days == 180
        assert ld.audit_reads is False

    def test_custom(self):
        ld = LayerDefaults(trust="canonical", retention="permanent", audit_reads=True)
        assert ld.trust == "canonical"
        assert ld.retention == "permanent"

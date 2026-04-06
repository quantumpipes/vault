"""Tests for the plugin system."""

from __future__ import annotations

from pathlib import Path

from qp_vault.plugins import embedder, parser, policy
from qp_vault.plugins.registry import PluginRegistry


class TestDecorators:
    def test_embedder_decorator(self):
        @embedder("test-embed")
        class TestEmbedder:
            dimensions = 4
            async def embed(self, texts):
                return [[0.0] * 4] * len(texts)

        assert TestEmbedder._qp_vault_plugin_type == "embedder"
        assert TestEmbedder._qp_vault_plugin_name == "test-embed"

    def test_parser_decorator(self):
        @parser("test-format")
        class TestParser:
            supported_extensions = {".test"}
            async def parse(self, path):
                return None

        assert TestParser._qp_vault_plugin_type == "parser"
        assert TestParser._qp_vault_plugin_name == "test-format"

    def test_policy_decorator(self):
        @policy("test-policy")
        class TestPolicy:
            async def evaluate(self, resource, action, context):
                return None

        assert TestPolicy._qp_vault_plugin_type == "policy"
        assert TestPolicy._qp_vault_plugin_name == "test-policy"


class TestRegistry:
    def test_register_and_retrieve_embedder(self):
        reg = PluginRegistry()

        class FakeEmbedder:
            dimensions = 4

        reg.register_embedder("fake", FakeEmbedder())
        assert reg.get_embedder("fake") is not None
        assert "fake" in reg.list_embedders()

    def test_register_and_retrieve_parser(self):
        reg = PluginRegistry()

        class FakeParser:
            supported_extensions = {".fake"}

        reg.register_parser("fake", FakeParser())
        assert reg.get_parser_for_extension(".fake") is not None
        assert "fake" in reg.list_parsers()

    def test_parser_extension_lookup(self):
        reg = PluginRegistry()

        class MultiParser:
            supported_extensions = {".a", ".b", ".c"}

        reg.register_parser("multi", MultiParser())
        assert reg.get_parser_for_extension(".b") is not None
        assert reg.get_parser_for_extension(".z") is None

    def test_register_policy(self):
        reg = PluginRegistry()

        class FakePolicy:
            pass

        reg.register_policy("fake", FakePolicy())
        assert "fake" in reg.list_policies()
        assert len(reg.all_policies) == 1

    def test_register_hook(self):
        reg = PluginRegistry()
        called = []
        reg.register_hook("pre_index", lambda: called.append(True))
        assert len(reg._hooks["pre_index"]) == 1

    def test_get_nonexistent_returns_none(self):
        reg = PluginRegistry()
        assert reg.get_embedder("nonexistent") is None
        assert reg.get_parser_for_extension(".zzz") is None


class TestPluginsDir:
    def test_discover_from_dir(self, tmp_path: Path):
        """Test loading plugins from a directory."""
        plugin_file = tmp_path / "my_embedder.py"
        plugin_file.write_text("""
from qp_vault.plugins import embedder

@embedder("dir-embed")
class DirEmbedder:
    dimensions = 8
    async def embed(self, texts):
        return [[0.0] * 8] * len(texts)
""")

        reg = PluginRegistry()
        reg.discover_plugins_dir(tmp_path)
        assert "dir-embed" in reg.list_embedders()

    def test_discover_skips_underscore_files(self, tmp_path: Path):
        (tmp_path / "_private.py").write_text("x = 1")
        reg = PluginRegistry()
        reg.discover_plugins_dir(tmp_path)
        assert len(reg.list_embedders()) == 0

    def test_discover_skips_broken_files(self, tmp_path: Path):
        (tmp_path / "broken.py").write_text("raise RuntimeError('broken')")
        reg = PluginRegistry()
        reg.discover_plugins_dir(tmp_path)  # Should not raise

    def test_discover_nonexistent_dir(self):
        reg = PluginRegistry()
        reg.discover_plugins_dir(Path("/nonexistent"))  # Should not raise

    def test_discover_multiple_plugins(self, tmp_path: Path):
        (tmp_path / "embed1.py").write_text("""
from qp_vault.plugins import embedder
@embedder("e1")
class E1:
    dimensions = 4
    async def embed(self, texts): return [[0.0]*4]*len(texts)
""")
        (tmp_path / "parse1.py").write_text("""
from qp_vault.plugins import parser
@parser("p1")
class P1:
    supported_extensions = {".p1"}
    async def parse(self, path): return None
""")

        reg = PluginRegistry()
        reg.discover_plugins_dir(tmp_path)
        assert "e1" in reg.list_embedders()
        assert "p1" in reg.list_parsers()


class TestEntryPoints:
    def test_discover_entry_points_doesnt_crash(self):
        """Entry point discovery should work even with no plugins installed."""
        reg = PluginRegistry()
        reg.discover_entry_points()  # Should not raise

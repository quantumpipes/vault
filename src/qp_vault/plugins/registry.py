"""Plugin registry for qp-vault.

Manages discovery and registration of plugins from three sources:
1. Explicit registration: vault.register_embedder(MyEmbedder())
2. Entry points: [project.entry-points."qp_vault.embedders"]
3. Plugins directory: --plugins-dir (air-gap mode, drop .py files)

Plugin categories:
- embedders: EmbeddingProvider implementations
- parsers: ParserProvider implementations
- policies: PolicyProvider implementations
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("qp_vault.plugins")


class PluginRegistry:
    """Central registry for all vault plugins."""

    def __init__(self) -> None:
        self._embedders: dict[str, Any] = {}
        self._parsers: dict[str, Any] = {}
        self._policies: dict[str, Any] = {}
        self._hooks: dict[str, list[Any]] = {}

    # --- Registration ---

    def register_embedder(self, name: str, provider: Any) -> None:
        """Register an embedding provider by name."""
        self._embedders[name] = provider

    def register_parser(self, name: str, provider: Any) -> None:
        """Register a file parser by name."""
        self._parsers[name] = provider

    def register_policy(self, name: str, provider: Any) -> None:
        """Register a governance policy by name."""
        self._policies[name] = provider

    def register_hook(self, event: str, callback: Any) -> None:
        """Register a lifecycle hook callback."""
        self._hooks.setdefault(event, []).append(callback)

    async def fire_hooks(self, event: str, **kwargs: Any) -> None:
        """Invoke all registered hooks for an event."""
        for callback in self._hooks.get(event, []):
            try:
                import inspect
                if inspect.iscoroutinefunction(callback):
                    await callback(**kwargs)
                else:
                    callback(**kwargs)
            except Exception as e:
                logger.warning("Hook %s failed: %s", event, e)

    # --- Retrieval ---

    def get_embedder(self, name: str) -> Any | None:
        """Get a registered embedder by name."""
        return self._embedders.get(name)

    def get_parser_for_extension(self, ext: str) -> Any | None:
        """Find a parser that supports the given file extension."""
        for parser in self._parsers.values():
            if hasattr(parser, "supported_extensions") and ext.lower() in parser.supported_extensions:
                return parser
        return None

    def list_embedders(self) -> list[str]:
        """List registered embedder names."""
        return list(self._embedders.keys())

    def list_parsers(self) -> list[str]:
        """List registered parser names."""
        return list(self._parsers.keys())

    def list_policies(self) -> list[str]:
        """List registered policy names."""
        return list(self._policies.keys())

    @property
    def all_policies(self) -> list[Any]:
        """Get all registered policies."""
        return list(self._policies.values())

    # --- Discovery ---

    def discover_entry_points(self) -> None:
        """Load plugins from installed packages via entry_points.

        Looks for entry point groups:
        - qp_vault.embedders
        - qp_vault.parsers
        - qp_vault.policies
        """
        try:
            from importlib.metadata import entry_points
            eps = entry_points()
        except ImportError:
            return

        for group, register_fn in [
            ("qp_vault.embedders", self.register_embedder),
            ("qp_vault.parsers", self.register_parser),
            ("qp_vault.policies", self.register_policy),
        ]:
            try:
                group_eps = eps.select(group=group)

                for ep in group_eps:
                    try:
                        plugin_cls = ep.load()
                        instance = plugin_cls() if callable(plugin_cls) else plugin_cls
                        register_fn(ep.name, instance)
                    except Exception as e:
                        logger.warning("Failed to load entry_point plugin %s: %s", ep.name, e)
            except Exception as e:
                logger.debug("Entry point group %s unavailable: %s", group, e)

    def discover_plugins_dir(self, plugins_dir: Path, *, verify_hashes: bool = True) -> None:
        """Load plugins from a local directory (air-gap mode).

        Any .py file in the directory is imported. Classes decorated with
        @embedder, @parser, or @policy are auto-registered.

        When verify_hashes is True (default), a manifest.json MUST exist in the
        directory. Each plugin file's SHA3-256 hash is verified against the
        manifest before loading. Files not in the manifest are rejected.
        """
        if not plugins_dir.is_dir():
            return

        # Load manifest for hash verification
        manifest: dict[str, str] = {}
        manifest_path = plugins_dir / "manifest.json"
        if verify_hashes:
            if not manifest_path.exists():
                logger.warning(
                    "Plugin directory %s has no manifest.json. "
                    "Skipping plugin discovery (verify_hashes=True requires manifest).",
                    plugins_dir,
                )
                return
            import json
            manifest = json.loads(manifest_path.read_text())

        for py_file in sorted(plugins_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            # Hash verification: reject files not in manifest or with wrong hash
            if verify_hashes:
                import hashlib
                file_hash = hashlib.sha3_256(py_file.read_bytes()).hexdigest()
                expected = manifest.get(py_file.name)
                if not expected:
                    logger.warning(
                        "Plugin %s not in manifest. Skipping.", py_file.name,
                    )
                    continue
                if file_hash != expected:
                    logger.warning(
                        "Plugin %s hash mismatch (expected %s, got %s). Skipping.",
                        py_file.name, expected[:16], file_hash[:16],
                    )
                    continue

            try:
                module_name = f"qp_vault_plugin_{py_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    # Check for decorated classes
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if hasattr(attr, "_qp_vault_plugin_type"):
                            ptype = attr._qp_vault_plugin_type
                            pname = attr._qp_vault_plugin_name
                            instance = attr() if callable(attr) else attr
                            if ptype == "embedder":
                                self.register_embedder(pname, instance)
                            elif ptype == "parser":
                                self.register_parser(pname, instance)
                            elif ptype == "policy":
                                self.register_policy(pname, instance)
            except Exception as e:
                logger.warning("Failed to load plugin file %s: %s", py_file.name, e)


# Global registry instance
_registry = PluginRegistry()


def get_registry() -> PluginRegistry:
    """Get the global plugin registry."""
    return _registry

"""Tests for v1.2.0 gap fixes: plugin hooks, expiration, content deduplication."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault import Vault

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# GAP-4: Plugin Hooks
# =============================================================================


class TestPluginHooks:
    def test_post_add_hook_fires(self, tmp_path: Path) -> None:
        """post_add hook is called when a resource is added."""
        from qp_vault.plugins.registry import get_registry

        fired: list[str] = []

        def on_add(**kwargs: object) -> None:
            fired.append("add")

        reg = get_registry()
        reg.register_hook("post_add", on_add)

        try:
            vault = Vault(tmp_path / "hooks1")
            vault.add("Hook test", name="h.md")
            assert "add" in fired
        finally:
            reg._hooks.pop("post_add", None)

    def test_post_delete_hook_fires(self, tmp_path: Path) -> None:
        """post_delete hook is called when a resource is deleted."""
        from qp_vault.plugins.registry import get_registry

        fired: list[str] = []

        def on_delete(**kwargs: object) -> None:
            fired.append("delete")

        reg = get_registry()
        reg.register_hook("post_delete", on_delete)

        try:
            vault = Vault(tmp_path / "hooks2")
            r = vault.add("Doc", name="d.md")
            vault.delete(r.id)
            assert "delete" in fired
        finally:
            reg._hooks.pop("post_delete", None)

    def test_post_search_hook_fires(self, tmp_path: Path) -> None:
        """post_search hook is called after search."""
        from qp_vault.plugins.registry import get_registry

        fired: list[str] = []

        def on_search(**kwargs: object) -> None:
            fired.append("search")

        reg = get_registry()
        reg.register_hook("post_search", on_search)

        try:
            vault = Vault(tmp_path / "hooks3")
            vault.add("Content", name="c.md")
            vault.search("content")
            assert "search" in fired
        finally:
            reg._hooks.pop("post_search", None)

    def test_hook_failure_does_not_crash(self, tmp_path: Path) -> None:
        """A failing hook should not crash the vault operation."""
        from qp_vault.plugins.registry import get_registry

        def bad_hook(**kwargs: object) -> None:
            raise RuntimeError("Hook crashed")

        reg = get_registry()
        reg.register_hook("post_add", bad_hook)

        try:
            vault = Vault(tmp_path / "hooks4")
            r = vault.add("Doc", name="d.md")
            assert r.id  # Operation should succeed despite hook failure
        finally:
            reg._hooks.pop("post_add", None)


# =============================================================================
# GAP-6: Expiration
# =============================================================================


class TestExpiration:
    def test_search_count_tracked(self, tmp_path: Path) -> None:
        """Search count is tracked for lazy expiration."""
        vault = Vault(tmp_path / "exp1")
        vault.add("Doc", name="d.md")
        vault.search("doc")
        assert vault._async._search_count >= 1

    @pytest.mark.asyncio
    async def test_start_expiration_monitor(self, tmp_path: Path) -> None:
        """Expiration monitor can be started."""
        from qp_vault import AsyncVault

        vault = AsyncVault(tmp_path / "exp2")
        await vault._ensure_initialized()
        await vault.start_expiration_monitor(interval_seconds=999999)
        assert hasattr(vault, "_expiration_task")
        vault._expiration_task.cancel()


# =============================================================================
# GAP-9: Content Deduplication
# =============================================================================


class TestContentDedup:
    def test_duplicate_content_returns_existing(self, tmp_path: Path) -> None:
        """Adding same content twice returns the existing resource."""
        vault = Vault(tmp_path / "dedup1")
        r1 = vault.add("Exact same content", name="a.md")
        r2 = vault.add("Exact same content", name="b.md")
        assert r1.id == r2.id  # Same resource returned

    def test_different_content_creates_new(self, tmp_path: Path) -> None:
        """Different content creates a new resource."""
        vault = Vault(tmp_path / "dedup2")
        r1 = vault.add("Content A", name="a.md")
        r2 = vault.add("Content B", name="b.md")
        assert r1.id != r2.id

    def test_same_content_different_tenant(self, tmp_path: Path) -> None:
        """Same content in different tenants creates separate resources."""
        vault = Vault(tmp_path / "dedup3")
        r1 = vault.add("Same content", name="a.md", tenant_id="t1")
        r2 = vault.add("Same content", name="a.md", tenant_id="t2")
        assert r1.id != r2.id

    def test_dedup_preserves_list_count(self, tmp_path: Path) -> None:
        """Duplicate content doesn't create extra resources."""
        vault = Vault(tmp_path / "dedup4")
        vault.add("Unique content", name="a.md")
        vault.add("Unique content", name="b.md")  # Dedup: same resource
        vault.add("Different content", name="c.md")
        resources = vault.list()
        assert len(resources) == 2  # Only 2 unique resources

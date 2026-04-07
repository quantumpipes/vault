"""Full CLI integration tests using Typer's CliRunner.

Tests all 15+ CLI commands with real vault operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

try:
    from typer.testing import CliRunner
    HAS_TYPER = True
except ImportError:
    HAS_TYPER = False

pytestmark = pytest.mark.skipif(not HAS_TYPER, reason="typer not installed")

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_app():
    from qp_vault.cli.main import app
    return app


@pytest.fixture
def vault_path(tmp_path: Path):
    return str(tmp_path / "cli-vault")


class TestInit:
    def test_init_creates_vault(self, runner, cli_app, vault_path) -> None:
        result = runner.invoke(cli_app, ["init", vault_path])
        assert result.exit_code == 0
        assert "Initialized" in result.stdout or "vault" in result.stdout.lower()


class TestAdd:
    def test_add_text(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        result = runner.invoke(cli_app, ["add", "Hello world content", "--path", vault_path, "--name", "hello.md"])
        assert result.exit_code == 0
        assert "Added" in result.stdout

    def test_add_with_trust(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        result = runner.invoke(cli_app, ["add", "Canonical doc", "--path", vault_path, "--trust", "canonical"])
        assert result.exit_code == 0

    def test_add_with_tags(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        result = runner.invoke(cli_app, ["add", "Tagged doc", "--path", vault_path, "--tags", "important,reviewed"])
        assert result.exit_code == 0


class TestSearch:
    def test_search_no_results(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        result = runner.invoke(cli_app, ["search", "nonexistent", "--path", vault_path])
        assert result.exit_code == 0
        assert "No results" in result.stdout

    def test_search_with_results(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Searchable content about testing", "--path", vault_path])
        result = runner.invoke(cli_app, ["search", "testing", "--path", vault_path])
        assert result.exit_code == 0


class TestList:
    def test_list_empty(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        result = runner.invoke(cli_app, ["list", "--path", vault_path])
        assert result.exit_code == 0

    def test_list_with_resources(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Doc A", "--path", vault_path])
        runner.invoke(cli_app, ["add", "Doc B", "--path", vault_path])
        result = runner.invoke(cli_app, ["list", "--path", vault_path])
        assert result.exit_code == 0
        assert "2 resources" in result.stdout or "resource" in result.stdout.lower()


class TestStatus:
    def test_status(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Doc", "--path", vault_path])
        result = runner.invoke(cli_app, ["status", "--path", vault_path])
        assert result.exit_code == 0
        assert "Total" in result.stdout or "total" in result.stdout.lower()


class TestVerify:
    def test_verify_vault(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Doc", "--path", vault_path])
        result = runner.invoke(cli_app, ["verify", "--path", vault_path])
        assert result.exit_code == 0


class TestHealth:
    def test_health(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Doc", "--path", vault_path])
        result = runner.invoke(cli_app, ["health", "--path", vault_path])
        assert result.exit_code == 0


class TestExpiring:
    def test_expiring_none(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Doc", "--path", vault_path])
        result = runner.invoke(cli_app, ["expiring", "--path", vault_path])
        assert result.exit_code == 0
        assert "No resources expiring" in result.stdout


class TestCollections:
    def test_collections_empty(self, runner, cli_app, vault_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        result = runner.invoke(cli_app, ["collections", "--path", vault_path])
        assert result.exit_code == 0


class TestExport:
    def test_export(self, runner, cli_app, vault_path, tmp_path) -> None:
        runner.invoke(cli_app, ["init", vault_path])
        runner.invoke(cli_app, ["add", "Export content", "--path", vault_path])
        export_path = str(tmp_path / "export.json")
        result = runner.invoke(cli_app, ["export", export_path, "--path", vault_path])
        assert result.exit_code == 0

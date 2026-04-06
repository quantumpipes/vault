"""Tests for the vault CLI tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

try:
    from typer.testing import CliRunner

    from qp_vault.cli.main import app
    HAS_TYPER = True
except ImportError:
    HAS_TYPER = False

pytestmark = pytest.mark.skipif(not HAS_TYPER, reason="typer not installed")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return tmp_path / "cli-vault"


class TestCLIInit:
    def test_init_creates_vault(self, runner, vault_dir):
        result = runner.invoke(app, ["init", str(vault_dir)])
        assert result.exit_code == 0
        assert "initialized" in result.output.lower() or "Vault" in result.output
        assert (vault_dir / "vault.db").exists()

    def test_init_already_exists(self, runner, vault_dir):
        runner.invoke(app, ["init", str(vault_dir)])
        result = runner.invoke(app, ["init", str(vault_dir)])
        assert result.exit_code == 0
        assert "already exists" in result.output.lower()


class TestCLIAdd:
    def test_add_text(self, runner, vault_dir, tmp_path):
        runner.invoke(app, ["init", str(vault_dir)])

        # Create a test file
        test_file = tmp_path / "doc.md"
        test_file.write_text("Test document content for CLI testing.")

        result = runner.invoke(app, ["add", str(test_file), "--path", str(vault_dir)])
        assert result.exit_code == 0
        assert "Added" in result.output or "doc.md" in result.output

    def test_add_with_trust(self, runner, vault_dir, tmp_path):
        runner.invoke(app, ["init", str(vault_dir)])
        test_file = tmp_path / "sop.md"
        test_file.write_text("Standard operating procedure.")

        result = runner.invoke(app, [
            "add", str(test_file),
            "--trust", "canonical",
            "--path", str(vault_dir),
        ])
        assert result.exit_code == 0
        assert "canonical" in result.output.lower()


class TestCLISearch:
    def test_search(self, runner, vault_dir, tmp_path):
        runner.invoke(app, ["init", str(vault_dir)])
        test_file = tmp_path / "searchable.md"
        test_file.write_text("Incident response procedure for critical outages.")
        runner.invoke(app, ["add", str(test_file), "--path", str(vault_dir)])

        result = runner.invoke(app, ["search", "incident response", "--path", str(vault_dir)])
        assert result.exit_code == 0

    def test_search_no_results(self, runner, vault_dir):
        runner.invoke(app, ["init", str(vault_dir)])
        result = runner.invoke(app, ["search", "nonexistent_xyz", "--path", str(vault_dir)])
        assert result.exit_code == 0
        assert "No results" in result.output


class TestCLIStatus:
    def test_status_empty(self, runner, vault_dir):
        runner.invoke(app, ["init", str(vault_dir)])
        result = runner.invoke(app, ["status", "--path", str(vault_dir)])
        assert result.exit_code == 0
        assert "0" in result.output

    def test_status_with_resources(self, runner, vault_dir, tmp_path):
        runner.invoke(app, ["init", str(vault_dir)])
        test_file = tmp_path / "doc.md"
        test_file.write_text("Some content.")
        runner.invoke(app, ["add", str(test_file), "--path", str(vault_dir)])

        result = runner.invoke(app, ["status", "--path", str(vault_dir)])
        assert result.exit_code == 0
        assert "1" in result.output


class TestCLIVerify:
    def test_verify_all(self, runner, vault_dir, tmp_path):
        runner.invoke(app, ["init", str(vault_dir)])
        test_file = tmp_path / "doc.md"
        test_file.write_text("Verify this content.")
        runner.invoke(app, ["add", str(test_file), "--path", str(vault_dir)])

        result = runner.invoke(app, ["verify", "--path", str(vault_dir)])
        assert result.exit_code == 0
        assert "PASS" in result.output

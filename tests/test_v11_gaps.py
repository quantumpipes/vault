"""Tests for v1.1.0 gap fixes: classification enforcement, import roundtrip, telemetry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault import Vault
from qp_vault.enums import DataClassification
from qp_vault.exceptions import VaultError

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# GAP-1: DataClassification Enforcement
# =============================================================================


class MockCloudEmbedder:
    """Mock cloud embedder (is_local=False)."""

    @property
    def dimensions(self) -> int:
        return 4

    @property
    def is_local(self) -> bool:
        return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4] * len(texts)


class MockLocalEmbedder:
    """Mock local embedder (is_local=True)."""

    @property
    def dimensions(self) -> int:
        return 4

    @property
    def is_local(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4] * len(texts)


class TestClassificationEnforcement:
    def test_public_allows_cloud_embedder(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "pub", embedder=MockCloudEmbedder())
        r = vault.add("Public doc", name="pub.md", classification="public")
        assert r.data_classification == DataClassification.PUBLIC

    def test_internal_allows_cloud_embedder(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "int", embedder=MockCloudEmbedder())
        r = vault.add("Internal doc", name="int.md", classification="internal")
        assert r.data_classification == DataClassification.INTERNAL

    def test_confidential_rejects_cloud_embedder(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "conf", embedder=MockCloudEmbedder())
        with pytest.raises(VaultError, match="cloud embedder"):
            vault.add("Secret doc", name="secret.md", classification="confidential")

    def test_restricted_rejects_cloud_embedder(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "rest", embedder=MockCloudEmbedder())
        with pytest.raises(VaultError, match="cloud embedder"):
            vault.add("Top secret", name="ts.md", classification="restricted")

    def test_confidential_allows_local_embedder(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "conf2", embedder=MockLocalEmbedder())
        r = vault.add("Secret doc", name="secret.md", classification="confidential")
        assert r.data_classification == DataClassification.CONFIDENTIAL

    def test_restricted_allows_local_embedder(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "rest2", embedder=MockLocalEmbedder())
        r = vault.add("Top secret", name="ts.md", classification="restricted")
        assert r.data_classification == DataClassification.RESTRICTED

    def test_confidential_no_embedder_ok(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "noem")
        r = vault.add("Secret doc", name="s.md", classification="confidential")
        assert r.id

    def test_restricted_read_audited(self, tmp_path: Path) -> None:
        """Reading a RESTRICTED resource emits an audit event."""
        from qp_vault.audit.log_auditor import LogAuditor

        log_path = tmp_path / "aud" / "audit.jsonl"
        vault = Vault(tmp_path / "aud", auditor=LogAuditor(log_path))
        r = vault.add("Restricted content", name="r.md", classification="restricted")

        # Read the resource (should trigger audit)
        vault.get(r.id)

        import json
        lines = log_path.read_text().strip().split("\n")
        # Find the read audit event
        read_events = [json.loads(line) for line in lines if "restricted" in line]
        assert len(read_events) >= 1


# =============================================================================
# GAP-2: Import/Export Roundtrip
# =============================================================================


class TestImportExportRoundtrip:
    def test_export_includes_chunks(self, tmp_path: Path) -> None:
        """Export file includes chunk content."""
        import json

        vault = Vault(tmp_path / "exp")
        vault.add("Important document content here", name="doc.md")
        vault.export_vault(str(tmp_path / "export.json"))

        data = json.loads((tmp_path / "export.json").read_text())
        assert data["resources"][0]["_chunks"]
        assert data["resources"][0]["_chunks"][0]["content"]
        assert "Important document" in data["resources"][0]["_chunks"][0]["content"]

    def test_import_preserves_content(self, tmp_path: Path) -> None:
        """Import reconstructs content from chunks."""
        vault1 = Vault(tmp_path / "v1")
        vault1.add("Critical policy: all incidents must be reported within 15 minutes", name="policy.md")
        vault1.export_vault(str(tmp_path / "backup.json"))

        vault2 = Vault(tmp_path / "v2")
        imported = vault2.import_vault(str(tmp_path / "backup.json"))
        assert len(imported) == 1

        content = vault2.get_content(imported[0].id)
        assert "incidents must be reported" in content

    def test_roundtrip_preserves_metadata(self, tmp_path: Path) -> None:
        """Export/import preserves name, trust_tier, tags."""
        vault1 = Vault(tmp_path / "rt1")
        vault1.add(
            "Content with metadata",
            name="meta.md",
            trust_tier="canonical",
            tags=["important", "reviewed"],
        )
        vault1.export_vault(str(tmp_path / "rt.json"))

        vault2 = Vault(tmp_path / "rt2")
        imported = vault2.import_vault(str(tmp_path / "rt.json"))
        assert imported[0].name == "meta.md"
        assert imported[0].trust_tier.value == "canonical"
        assert "important" in imported[0].tags

    def test_import_old_format_without_chunks(self, tmp_path: Path) -> None:
        """Import handles old export format (no _chunks) gracefully."""
        import json

        old_export = {
            "version": "1.0.0",
            "resource_count": 1,
            "resources": [{"name": "old.md", "trust_tier": "working", "tags": [], "metadata": {}}],
        }
        (tmp_path / "old.json").write_text(json.dumps(old_export))

        vault = Vault(tmp_path / "old")
        imported = vault.import_vault(str(tmp_path / "old.json"))
        assert len(imported) == 1
        assert imported[0].name == "old.md"


# =============================================================================
# GAP-3: Telemetry Integration
# =============================================================================


class TestTelemetryIntegration:
    def test_telemetry_tracks_add(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "tel")
        vault.add("Doc", name="d.md")
        summary = vault._async._telemetry.summary()
        assert "add" in summary
        assert summary["add"]["count"] >= 1

    def test_telemetry_tracks_search(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "tel2")
        vault.add("Searchable content", name="s.md")
        vault.search("searchable")
        summary = vault._async._telemetry.summary()
        assert "search" in summary
        assert summary["search"]["count"] >= 1

    def test_telemetry_in_status(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "tel3")
        vault.add("Doc", name="d.md")
        status = vault.status()
        assert "telemetry" in status

    def test_telemetry_tracks_latency(self, tmp_path: Path) -> None:
        vault = Vault(tmp_path / "tel4")
        vault.add("Doc", name="d.md")
        metrics = vault._async._telemetry.get("add")
        assert metrics.count >= 1
        assert metrics.avg_duration_ms > 0

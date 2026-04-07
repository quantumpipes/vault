"""Tests for ResourceManager with mock embedder."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

from qp_vault.core.chunker import ChunkerConfig
from qp_vault.core.resource_manager import ResourceManager, _detect_resource_type
from qp_vault.enums import EventType, ResourceStatus, ResourceType
from qp_vault.storage.sqlite import SQLiteBackend

if TYPE_CHECKING:
    from qp_vault.models import VaultEvent


class MockEmbedder:
    """Deterministic embedder for testing."""

    @property
    def dimensions(self) -> int:
        return 4

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [float(b) / 255 for b in hashlib.sha256(t.encode()).digest()[:4]]
            for t in texts
        ]


class MockAuditor:
    """Captures audit events for assertions."""

    def __init__(self) -> None:
        self.events: list[VaultEvent] = []

    async def record(self, event: VaultEvent) -> str:
        self.events.append(event)
        return f"audit-{len(self.events)}"


@pytest.fixture
async def backend(tmp_path):
    b = SQLiteBackend(tmp_path / "rm-test.db")
    await b.initialize()
    return b


@pytest.fixture
def auditor():
    return MockAuditor()


@pytest.fixture
def manager(backend, auditor):
    return ResourceManager(
        storage=backend,
        embedder=MockEmbedder(),
        auditor=auditor,
        chunker_config=ChunkerConfig(target_tokens=50, min_tokens=5, max_tokens=100),
    )


class TestResourceManagerAdd:
    @pytest.mark.asyncio
    async def test_add_returns_resource(self, manager):
        r = await manager.add("Test content", name="test.md")
        assert r.name == "test.md"
        assert r.status == ResourceStatus.INDEXED
        assert r.chunk_count >= 1

    @pytest.mark.asyncio
    async def test_add_with_embeddings(self, manager):
        r = await manager.add("Content for embedding", name="embed.md")
        assert r.chunk_count >= 1

    @pytest.mark.asyncio
    async def test_add_emits_create_event(self, manager, auditor):
        await manager.add("Test", name="test.md")
        assert len(auditor.events) == 1
        assert auditor.events[0].event_type == EventType.CREATE

    @pytest.mark.asyncio
    async def test_add_computes_cid(self, manager):
        r = await manager.add("Test", name="test.md")
        assert r.cid.startswith("vault://sha3-256/")

    @pytest.mark.asyncio
    async def test_add_same_content_same_hash(self, manager):
        r1 = await manager.add("Identical", name="a.md")
        r2 = await manager.add("Identical", name="b.md")
        assert r1.content_hash == r2.content_hash


class TestResourceManagerCRUD:
    @pytest.mark.asyncio
    async def test_get(self, manager):
        r = await manager.add("Test", name="test.md")
        fetched = await manager.get(r.id)
        assert fetched.id == r.id

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, manager):
        from qp_vault.exceptions import VaultError
        with pytest.raises(VaultError):
            await manager.get("nonexistent")

    @pytest.mark.asyncio
    async def test_list(self, manager):
        await manager.add("A", name="a.md")
        await manager.add("B", name="b.md")
        resources = await manager.list()
        assert len(resources) == 2

    @pytest.mark.asyncio
    async def test_update_trust(self, manager, auditor):
        r = await manager.add("Test", name="test.md")
        updated = await manager.update(r.id, trust_tier="canonical")
        assert updated.trust_tier == "canonical"
        # Should emit trust_change event
        trust_events = [e for e in auditor.events if e.event_type == EventType.TRUST_CHANGE]
        assert len(trust_events) == 1

    @pytest.mark.asyncio
    async def test_delete_soft(self, manager, auditor):
        r = await manager.add("Test", name="test.md")
        await manager.delete(r.id)
        delete_events = [e for e in auditor.events if e.event_type == EventType.DELETE]
        assert len(delete_events) == 1
        assert delete_events[0].details["hard"] is False

    @pytest.mark.asyncio
    async def test_delete_hard(self, manager):
        r = await manager.add("Test", name="test.md")
        await manager.delete(r.id, hard=True)
        from qp_vault.exceptions import VaultError
        with pytest.raises(VaultError):
            await manager.get(r.id)

    @pytest.mark.asyncio
    async def test_restore(self, manager, auditor):
        r = await manager.add("Test", name="test.md")
        await manager.delete(r.id)
        restored = await manager.restore(r.id)
        assert restored.status == ResourceStatus.INDEXED
        restore_events = [e for e in auditor.events if e.event_type == EventType.RESTORE]
        assert len(restore_events) == 1


class TestResourceTypeDetection:
    def test_pdf(self):
        assert _detect_resource_type("report.pdf") == ResourceType.DOCUMENT

    def test_python(self):
        assert _detect_resource_type("script.py") == ResourceType.CODE

    def test_markdown(self):
        assert _detect_resource_type("readme.md") == ResourceType.NOTE

    def test_image(self):
        assert _detect_resource_type("photo.jpg") == ResourceType.IMAGE

    def test_transcript(self):
        assert _detect_resource_type("meeting.vtt") == ResourceType.TRANSCRIPT

    def test_spreadsheet(self):
        assert _detect_resource_type("data.csv") == ResourceType.SPREADSHEET

    def test_unknown_defaults_to_document(self):
        assert _detect_resource_type("file.xyz") == ResourceType.DOCUMENT

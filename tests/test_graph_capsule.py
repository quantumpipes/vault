"""Tests for graph capsule audit integration (TC-1.* from 17-testing.md).

Verifies that graph mutations fire VaultEvents with correct EventType
values, and that the audit provider records them.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from qp_vault import AsyncVault
from qp_vault.enums import EventType
from qp_vault.models import VaultEvent


class MockAuditor:
    """Captures audit events for testing."""

    def __init__(self):
        self.events: list[VaultEvent] = []

    async def record(self, event: VaultEvent) -> str:
        self.events.append(event)
        return str(uuid.uuid4())


@pytest.fixture
async def vault_with_auditor(tmp_vault_path):
    """Vault with a mock auditor to capture events."""
    auditor = MockAuditor()
    v = AsyncVault(tmp_vault_path, auditor=auditor)
    await v._ensure_initialized()
    return v, auditor


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


class TestEntityCreateEvent:
    async def test_entity_create_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        await vault.graph.create_node(
            name="Test Entity", entity_type="person", tenant_id=tenant_id,
        )
        graph_events = [e for e in auditor.events if e.event_type == EventType.ENTITY_CREATE]
        assert len(graph_events) == 1
        assert "entity_create" in graph_events[0].resource_name
        assert graph_events[0].details["entity_type"] == "person"


class TestEntityUpdateEvent:
    async def test_entity_update_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        node = await vault.graph.create_node(
            name="UpdateMe", entity_type="concept", tenant_id=tenant_id,
        )
        await vault.graph.update_node(node.id, name="Updated")
        update_events = [e for e in auditor.events if e.event_type == EventType.ENTITY_UPDATE]
        assert len(update_events) == 1


class TestEntityDeleteEvent:
    async def test_entity_delete_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        node = await vault.graph.create_node(
            name="DeleteMe", entity_type="temp", tenant_id=tenant_id,
        )
        await vault.graph.delete_node(node.id)
        delete_events = [e for e in auditor.events if e.event_type == EventType.ENTITY_DELETE]
        assert len(delete_events) == 1


class TestEdgeCreateEvent:
    async def test_edge_create_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        n1 = await vault.graph.create_node(name="A", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="B", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="knows", tenant_id=tenant_id,
        )
        edge_events = [e for e in auditor.events if e.event_type == EventType.EDGE_CREATE]
        assert len(edge_events) == 1
        assert edge_events[0].details["relation_type"] == "knows"


class TestEdgeDeleteEvent:
    async def test_edge_delete_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        n1 = await vault.graph.create_node(name="X", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Y", entity_type="t", tenant_id=tenant_id)
        edge = await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="linked", tenant_id=tenant_id,
        )
        await vault.graph.delete_edge(edge.id)
        delete_events = [e for e in auditor.events if e.event_type == EventType.EDGE_DELETE]
        assert len(delete_events) == 1


class TestMergeEvent:
    async def test_entity_merge_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        n1 = await vault.graph.create_node(name="Keep", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Absorb", entity_type="t", tenant_id=tenant_id)
        await vault.graph.merge_nodes(n1.id, n2.id)
        merge_events = [e for e in auditor.events if e.event_type == EventType.ENTITY_MERGE]
        assert len(merge_events) == 1


class TestMentionEvent:
    async def test_mention_track_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        node = await vault.graph.create_node(name="Ent", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("doc text", name="doc.md")
        await vault.graph.track_mention(node.id, resource.id, context_snippet="mentioned here")
        mention_events = [e for e in auditor.events if e.event_type == EventType.MENTION_TRACK]
        assert len(mention_events) == 1


class TestScanEvent:
    async def test_scan_start_fires_event(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        space_id = str(uuid.uuid4())
        await vault.graph.scan(space_id, tenant_id=tenant_id)
        scan_events = [e for e in auditor.events if e.event_type == EventType.SCAN_START]
        assert len(scan_events) == 1


class TestNoAuditProvider:
    """Graph operations work without an audit provider."""

    async def test_graph_ops_without_auditor(self, tmp_vault_path, tenant_id):
        vault = AsyncVault(tmp_vault_path, auditor=None)
        await vault._ensure_initialized()
        # Should not raise even with auditor=None (LogAuditor is auto-created)
        node = await vault.graph.create_node(
            name="NoAudit", entity_type="t", tenant_id=tenant_id,
        )
        assert node.name == "NoAudit"


class TestMixedEvents:
    """Document and graph events coexist in the audit stream."""

    async def test_mixed_document_and_graph_events(self, vault_with_auditor, tenant_id):
        vault, auditor = vault_with_auditor
        await vault.add("A document", name="mixed.md")
        await vault.graph.create_node(name="Mixed", entity_type="t", tenant_id=tenant_id)

        event_types = {e.event_type for e in auditor.events}
        assert EventType.CREATE in event_types
        assert EventType.ENTITY_CREATE in event_types

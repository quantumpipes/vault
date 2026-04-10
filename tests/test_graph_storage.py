"""Tests for graph storage primitives (TG-1.* from 17-testing.md).

Covers node CRUD, edge CRUD, traversal, mentions, merge, cross-space
membership, and scan jobs. Parametrized across SQLite backend.
"""

from __future__ import annotations

import uuid

import pytest

from qp_vault import AsyncVault
from qp_vault.enums import EventType
from qp_vault.graph.models import GraphEdge, GraphMention, GraphNode, GraphScanJob, NeighborResult


@pytest.fixture
async def vault(tmp_vault_path):
    """Create an AsyncVault with SQLite backend (graph-enabled)."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


class TestGraphProperty:
    """vault.graph is available on SQLite backend."""

    async def test_graph_not_none_sqlite(self, vault):
        assert vault.graph is not None

    async def test_graph_is_graph_engine(self, vault):
        from qp_vault.graph.service import GraphEngine
        assert isinstance(vault.graph, GraphEngine)


class TestNodeCRUD:
    """TG-1.1 through TG-1.5: Node create, get, update, delete, list."""

    async def test_create_node(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="Jane Doe",
            entity_type="person",
            tenant_id=tenant_id,
        )
        assert isinstance(node, GraphNode)
        assert node.name == "Jane Doe"
        assert node.entity_type == "person"
        assert node.slug == "jane-doe"
        assert node.mention_count == 0

    async def test_create_node_slug_collision(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Test", entity_type="thing", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Test", entity_type="thing", tenant_id=tenant_id)
        assert n1.slug != n2.slug
        assert n2.slug.startswith("test")

    async def test_get_node(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Alice", entity_type="person", tenant_id=tenant_id)
        fetched = await vault.graph.get_node(node.id)
        assert fetched is not None
        assert fetched.name == "Alice"

    async def test_get_node_not_found(self, vault):
        result = await vault.graph.get_node(uuid.uuid4())
        assert result is None

    async def test_update_node(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Bob", entity_type="person", tenant_id=tenant_id)
        updated = await vault.graph.update_node(node.id, name="Bobby", tags=["vip"])
        assert updated.name == "Bobby"
        assert "vip" in updated.tags

    async def test_delete_node(self, vault, tenant_id):
        node = await vault.graph.create_node(name="ToDelete", entity_type="temp", tenant_id=tenant_id)
        await vault.graph.delete_node(node.id)
        assert await vault.graph.get_node(node.id) is None

    async def test_list_nodes(self, vault, tenant_id):
        await vault.graph.create_node(name="A", entity_type="person", tenant_id=tenant_id)
        await vault.graph.create_node(name="B", entity_type="company", tenant_id=tenant_id)
        nodes, total = await vault.graph.list_nodes()
        assert total >= 2
        assert len(nodes) >= 2

    async def test_list_nodes_filter_type(self, vault, tenant_id):
        await vault.graph.create_node(name="C", entity_type="person", tenant_id=tenant_id)
        await vault.graph.create_node(name="D", entity_type="company", tenant_id=tenant_id)
        nodes, total = await vault.graph.list_nodes(entity_type="person")
        assert all(n.entity_type == "person" for n in nodes)

    async def test_search_nodes(self, vault, tenant_id):
        await vault.graph.create_node(name="Quantum Computing", entity_type="concept", tenant_id=tenant_id)
        results = await vault.graph.search_nodes("Quantum")
        assert len(results) >= 1
        assert any("Quantum" in r.name for r in results)


class TestEdgeCRUD:
    """TG-1.6 through TG-1.8: Edge create, get, update, delete."""

    async def test_create_edge(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Alice", entity_type="person", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Acme", entity_type="company", tenant_id=tenant_id)
        edge = await vault.graph.create_edge(
            source_id=n1.id,
            target_id=n2.id,
            relation_type="works_at",
            tenant_id=tenant_id,
        )
        assert isinstance(edge, GraphEdge)
        assert edge.relation_type == "works_at"
        assert edge.weight == 0.5

    async def test_self_edge_rejected(self, vault, tenant_id):
        n = await vault.graph.create_node(name="Solo", entity_type="thing", tenant_id=tenant_id)
        with pytest.raises(ValueError, match="Self-edges"):
            await vault.graph.create_edge(
                source_id=n.id, target_id=n.id,
                relation_type="self", tenant_id=tenant_id,
            )

    async def test_get_edges(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="X", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Y", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="related", tenant_id=tenant_id,
        )
        edges = await vault.graph.get_edges(n1.id, direction="outgoing")
        assert len(edges) == 1
        assert edges[0].relation_type == "related"

    async def test_update_edge(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="P", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Q", entity_type="t", tenant_id=tenant_id)
        edge = await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="knows", tenant_id=tenant_id,
        )
        updated = await vault.graph.update_edge(edge.id, weight=0.9)
        assert updated.weight == pytest.approx(0.9)

    async def test_delete_edge(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="M", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="N", entity_type="t", tenant_id=tenant_id)
        edge = await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="temp", tenant_id=tenant_id,
        )
        await vault.graph.delete_edge(edge.id)
        edges = await vault.graph.get_edges(n1.id)
        assert len(edges) == 0


class TestTraversal:
    """TG-1.9: Neighbor traversal."""

    async def test_neighbors_1_hop(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Center", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Hop1", entity_type="t", tenant_id=tenant_id)
        n3 = await vault.graph.create_node(name="Hop2", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n1.id, target_id=n2.id, relation_type="r", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n2.id, target_id=n3.id, relation_type="r", tenant_id=tenant_id)

        neighbors = await vault.graph.neighbors(n1.id, depth=1)
        assert len(neighbors) >= 1
        assert any(n.node_name == "Hop1" for n in neighbors)

    async def test_neighbors_2_hop(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Root", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="L1", entity_type="t", tenant_id=tenant_id)
        n3 = await vault.graph.create_node(name="L2", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n1.id, target_id=n2.id, relation_type="r", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n2.id, target_id=n3.id, relation_type="r", tenant_id=tenant_id)

        neighbors = await vault.graph.neighbors(n1.id, depth=2)
        names = {n.node_name for n in neighbors}
        assert "L1" in names
        assert "L2" in names

    async def test_depth_cap_at_3(self, vault, tenant_id):
        nodes = []
        for i in range(5):
            n = await vault.graph.create_node(name=f"D{i}", entity_type="t", tenant_id=tenant_id)
            nodes.append(n)
        for i in range(4):
            await vault.graph.create_edge(
                source_id=nodes[i].id, target_id=nodes[i + 1].id,
                relation_type="r", tenant_id=tenant_id,
            )
        neighbors = await vault.graph.neighbors(nodes[0].id, depth=10)
        max_depth = max((n.depth for n in neighbors), default=0)
        assert max_depth <= 3


class TestMentions:
    """TG-1.10, TG-1.11: Mention tracking and backlinks."""

    async def test_track_mention(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Entity", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("Document mentioning Entity", name="doc.md")

        await vault.graph.track_mention(
            node.id, resource.id, context_snippet="mentioning Entity here",
        )

        updated = await vault.graph.get_node(node.id)
        assert updated.mention_count == 1

    async def test_upsert_mention_idempotent(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Ent", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("Content", name="r.md")

        await vault.graph.track_mention(node.id, resource.id, context_snippet="first")
        await vault.graph.track_mention(node.id, resource.id, context_snippet="second")

        updated = await vault.graph.get_node(node.id)
        assert updated.mention_count == 1

    async def test_get_backlinks(self, vault, tenant_id):
        node = await vault.graph.create_node(name="BL", entity_type="t", tenant_id=tenant_id)
        r1 = await vault.add("Doc 1", name="d1.md")
        r2 = await vault.add("Doc 2", name="d2.md")

        await vault.graph.track_mention(node.id, r1.id)
        await vault.graph.track_mention(node.id, r2.id)

        backlinks = await vault.graph.get_backlinks(node.id)
        assert len(backlinks) == 2

    async def test_get_entities_in_resource(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="E1", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="E2", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("Both entities", name="both.md")

        await vault.graph.track_mention(n1.id, resource.id)
        await vault.graph.track_mention(n2.id, resource.id)

        entities = await vault.graph.get_entities_in_resource(resource.id)
        names = {e.name for e in entities}
        assert "E1" in names
        assert "E2" in names


class TestCrossSpace:
    """TG-1.12: Cross-space entity membership."""

    async def test_add_to_space(self, vault, tenant_id):
        space1 = str(uuid.uuid4())
        space2 = str(uuid.uuid4())
        node = await vault.graph.create_node(
            name="CrossSpace", entity_type="t",
            primary_space_id=space1, tenant_id=tenant_id,
        )
        await vault.graph.add_to_space(node.id, space2)
        # Verify node appears in space2 listing
        nodes, _ = await vault.graph.list_nodes(space_id=space2)
        assert any(n.id == node.id for n in nodes)

    async def test_remove_from_space(self, vault, tenant_id):
        space1 = str(uuid.uuid4())
        space2 = str(uuid.uuid4())
        node = await vault.graph.create_node(
            name="RemoveSpace", entity_type="t",
            primary_space_id=space1, tenant_id=tenant_id,
        )
        await vault.graph.add_to_space(node.id, space2)
        await vault.graph.remove_from_space(node.id, space2)


class TestMerge:
    """TG-1.13: Node merge."""

    async def test_merge_nodes(self, vault, tenant_id):
        n1 = await vault.graph.create_node(
            name="Keep", entity_type="person", tags=["a"],
            tenant_id=tenant_id,
        )
        n2 = await vault.graph.create_node(
            name="Merge", entity_type="person", tags=["b"],
            tenant_id=tenant_id,
        )
        n3 = await vault.graph.create_node(name="Other", entity_type="t", tenant_id=tenant_id)

        await vault.graph.create_edge(
            source_id=n2.id, target_id=n3.id,
            relation_type="knows", tenant_id=tenant_id,
        )

        merged = await vault.graph.merge_nodes(n1.id, n2.id)
        assert merged.name == "Keep"
        assert "a" in merged.tags
        assert "b" in merged.tags

        assert await vault.graph.get_node(n2.id) is None

        edges = await vault.graph.get_edges(n1.id)
        assert any(e.relation_type == "knows" for e in edges)


class TestContextFor:
    """context_for() builds structured LLM context."""

    async def test_context_for(self, vault, tenant_id):
        n1 = await vault.graph.create_node(
            name="Alice", entity_type="person",
            properties={"role": "engineer"},
            tenant_id=tenant_id,
        )
        n2 = await vault.graph.create_node(name="Acme", entity_type="company", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="works_at", tenant_id=tenant_id,
        )

        ctx = await vault.graph.context_for([n1.id])
        assert "Alice" in ctx
        assert "person" in ctx
        assert "works_at" in ctx
        assert "Acme" in ctx

    async def test_context_for_empty(self, vault):
        ctx = await vault.graph.context_for([])
        assert ctx == ""


class TestScanJobs:
    """Scan job lifecycle."""

    async def test_create_and_get_scan(self, vault, tenant_id):
        space_id = str(uuid.uuid4())
        job = await vault.graph.scan(space_id, tenant_id=tenant_id)
        assert isinstance(job, GraphScanJob)
        assert job.status == "running"

        fetched = await vault.graph.get_scan(job.id)
        assert fetched is not None
        assert fetched.status == "running"

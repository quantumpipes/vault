"""Edge case and error path tests for graph operations.

Covers: slugify edge cases, update filtering, direction filtering,
cascade deletion, merge edge cases, tenant resolution, mention
context truncation, nonexistent lookups, subscriber notification,
and graph property unavailability.
"""

from __future__ import annotations

import uuid

import pytest

from qp_vault import AsyncVault
from qp_vault.enums import EventType
from qp_vault.graph.service import GraphEngine, slugify
from qp_vault.models import VaultEvent


@pytest.fixture
async def vault(tmp_vault_path):
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


# --- slugify() ---

class TestSlugify:
    def test_basic_name(self):
        assert slugify("Jane Doe") == "jane-doe"

    def test_unicode_accents_stripped(self):
        assert slugify("Cafe") == "cafe"
        assert slugify("Rene") == "rene"

    def test_special_characters_replaced(self):
        assert slugify("A & B @ C") == "a-b-c"

    def test_empty_string_returns_entity(self):
        assert slugify("") == "entity"

    def test_all_special_chars_returns_entity(self):
        assert slugify("@#$%^&*") == "entity"

    def test_collapses_hyphens(self):
        result = slugify("hello   world")
        assert "--" not in result
        assert result == "hello-world"

    def test_strips_leading_trailing_hyphens(self):
        result = slugify("  hello  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_numeric_name(self):
        assert slugify("42") == "42"

    def test_mixed_case(self):
        assert slugify("OpenAI GPT-4o") == "openai-gpt-4o"


# --- Node Update Edge Cases ---

class TestNodeUpdateEdgeCases:
    async def test_update_ignores_disallowed_fields(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Orig", entity_type="t", tenant_id=tenant_id)
        updated = await vault.graph.update_node(
            node.id, name="New", disallowed_field="ignored",
        )
        assert updated.name == "New"

    async def test_update_name_regenerates_slug(self, vault, tenant_id):
        node = await vault.graph.create_node(name="OldName", entity_type="t", tenant_id=tenant_id)
        updated = await vault.graph.update_node(node.id, name="NewName")
        assert updated.slug == "newname"

    async def test_update_properties_preserves_other_fields(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="Stable", entity_type="person", tags=["keep"],
            tenant_id=tenant_id,
        )
        updated = await vault.graph.update_node(
            node.id, properties={"key": "val"},
        )
        assert updated.name == "Stable"
        assert updated.entity_type == "person"
        assert updated.properties["key"] == "val"


# --- Edge Direction Filtering ---

class TestEdgeDirectionFiltering:
    async def test_get_edges_incoming_only(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Src", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Tgt", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="points_to", tenant_id=tenant_id,
        )
        incoming = await vault.graph.get_edges(n2.id, direction="incoming")
        assert len(incoming) == 1
        assert incoming[0].relation_type == "points_to"

        outgoing = await vault.graph.get_edges(n2.id, direction="outgoing")
        assert len(outgoing) == 0

    async def test_get_edges_both_direction(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="A", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="B", entity_type="t", tenant_id=tenant_id)
        n3 = await vault.graph.create_node(name="C", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n1.id, target_id=n2.id, relation_type="r", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n3.id, target_id=n2.id, relation_type="r", tenant_id=tenant_id)
        both = await vault.graph.get_edges(n2.id, direction="both")
        assert len(both) == 2


# --- Edge with Properties ---

class TestEdgeWithProperties:
    async def test_create_edge_custom_weight_and_bidirectional(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="P", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Q", entity_type="t", tenant_id=tenant_id)
        edge = await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="linked",
            weight=0.9,
            bidirectional=True,
            properties={"strength": "high"},
            tenant_id=tenant_id,
        )
        assert edge.weight == pytest.approx(0.9)
        assert edge.bidirectional is True
        assert edge.properties["strength"] == "high"

    async def test_create_edge_with_source_resource(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="X", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Y", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("content", name="src.md")
        edge = await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="extracted_from",
            source_resource_id=resource.id,
            tenant_id=tenant_id,
        )
        assert edge.source_resource_id is not None


# --- Cascade Deletion ---

class TestCascadeDeletion:
    async def test_delete_node_cascades_edges(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Hub", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Spoke", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="connected", tenant_id=tenant_id,
        )
        await vault.graph.delete_node(n1.id)
        edges = await vault.graph.get_edges(n2.id)
        assert len(edges) == 0

    async def test_delete_nonexistent_node_is_silent(self, vault):
        await vault.graph.delete_node(uuid.uuid4())


# --- Merge Edge Cases ---

class TestMergeEdgeCases:
    async def test_merge_sums_mention_counts(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="KeepM", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="MergeM", entity_type="t", tenant_id=tenant_id)
        r1 = await vault.add("Doc A", name="a.md")
        r2 = await vault.add("Doc B", name="b.md")
        await vault.graph.track_mention(n1.id, r1.id)
        await vault.graph.track_mention(n2.id, r2.id)

        merged = await vault.graph.merge_nodes(n1.id, n2.id)
        assert merged.mention_count == 2

    async def test_merge_properties_keep_wins_on_conflict(self, vault, tenant_id):
        n1 = await vault.graph.create_node(
            name="K", entity_type="t",
            properties={"role": "admin", "shared": "from_keep"},
            tenant_id=tenant_id,
        )
        n2 = await vault.graph.create_node(
            name="M", entity_type="t",
            properties={"dept": "eng", "shared": "from_merge"},
            tenant_id=tenant_id,
        )
        merged = await vault.graph.merge_nodes(n1.id, n2.id)
        assert merged.properties["role"] == "admin"
        assert merged.properties["dept"] == "eng"
        assert merged.properties["shared"] == "from_keep"

    async def test_merge_deduplicates_mentions_on_same_resource(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="K2", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="M2", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("Shared doc", name="shared.md")
        await vault.graph.track_mention(n1.id, resource.id, context_snippet="from keep")
        await vault.graph.track_mention(n2.id, resource.id, context_snippet="from merge")

        await vault.graph.merge_nodes(n1.id, n2.id)
        backlinks = await vault.graph.get_backlinks(n1.id)
        resource_ids = [str(b.resource_id) for b in backlinks]
        assert resource_ids.count(str(resource.id)) == 1

    async def test_merge_nonexistent_raises(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Real", entity_type="t", tenant_id=tenant_id)
        with pytest.raises(Exception):
            await vault.graph.merge_nodes(n1.id, uuid.uuid4())


# --- Neighbors Edge Cases ---

class TestNeighborEdgeCases:
    async def test_neighbors_no_edges_returns_empty(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Isolated", entity_type="t", tenant_id=tenant_id)
        neighbors = await vault.graph.neighbors(node.id)
        assert neighbors == []

    async def test_neighbors_relation_type_filter(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Start", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Friend", entity_type="t", tenant_id=tenant_id)
        n3 = await vault.graph.create_node(name="Colleague", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n1.id, target_id=n2.id, relation_type="friend_of", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n1.id, target_id=n3.id, relation_type="works_with", tenant_id=tenant_id)

        friends = await vault.graph.neighbors(n1.id, relation_types=["friend_of"])
        names = {n.node_name for n in friends}
        assert "Friend" in names
        assert "Colleague" not in names

    async def test_neighbors_avoids_cycles(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="CycA", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="CycB", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n1.id, target_id=n2.id, relation_type="r", tenant_id=tenant_id)
        await vault.graph.create_edge(source_id=n2.id, target_id=n1.id, relation_type="r", tenant_id=tenant_id)
        neighbors = await vault.graph.neighbors(n1.id, depth=3)
        node_ids = [n.node_id for n in neighbors]
        assert len(node_ids) == len(set(node_ids))


# --- Context For Edge Cases ---

class TestContextForEdgeCases:
    async def test_context_for_nonexistent_entity_skipped(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Real", entity_type="t", tenant_id=tenant_id)
        ctx = await vault.graph.context_for([node.id, uuid.uuid4()])
        assert "Real" in ctx

    async def test_context_for_with_tags(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="Tagged", entity_type="concept",
            tags=["ai", "ml"], tenant_id=tenant_id,
        )
        ctx = await vault.graph.context_for([node.id])
        assert "ai" in ctx
        assert "ml" in ctx

    async def test_context_for_incoming_edge(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Child", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Parent", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n2.id, target_id=n1.id,
            relation_type="parent_of", tenant_id=tenant_id,
        )
        ctx = await vault.graph.context_for([n1.id])
        assert "Parent" in ctx


# --- Mention Snippet Truncation ---

class TestMentionSnippetTruncation:
    async def test_long_snippet_truncated_to_500(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Ent", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("content", name="doc.md")
        long_snippet = "x" * 1000
        await vault.graph.track_mention(
            node.id, resource.id, context_snippet=long_snippet,
        )
        backlinks = await vault.graph.get_backlinks(node.id)
        assert len(backlinks) == 1
        assert len(backlinks[0].context_snippet) <= 500


# --- Detect Returns Empty Without Detector ---

class TestDetectWithoutDetector:
    async def test_detect_returns_empty_when_no_detector(self, vault):
        results = await vault.graph.detect("Hello world")
        assert results == []


# --- Scan Get Nonexistent ---

class TestScanGetNonexistent:
    async def test_get_scan_nonexistent_returns_none(self, vault):
        result = await vault.graph.get_scan(uuid.uuid4())
        assert result is None


# --- Tenant Resolution ---

class TestTenantResolution:
    async def test_locked_tenant_used_when_no_tenant_provided(self, tmp_vault_path):
        locked = str(uuid.uuid4())
        vault = AsyncVault(tmp_vault_path, tenant_id=locked)
        await vault._ensure_initialized()
        node = await vault.graph.create_node(name="Locked", entity_type="t")
        assert str(node.tenant_id) == locked


# --- Subscriber Notification ---

class TestSubscriberNotification:
    async def test_graph_mutation_reaches_subscriber(self, vault, tenant_id):
        received: list[VaultEvent] = []

        def on_event(event: VaultEvent) -> None:
            received.append(event)

        vault.subscribe(on_event)
        await vault.graph.create_node(name="SubTest", entity_type="t", tenant_id=tenant_id)
        graph_events = [e for e in received if e.event_type == EventType.ENTITY_CREATE]
        assert len(graph_events) == 1


# --- Graph Property on Custom Backend ---

class TestGraphPropertyUnavailable:
    async def test_graph_none_when_storage_lacks_graph(self, tmp_vault_path):
        class MinimalBackend:
            async def initialize(self): pass
            async def store_resource(self, r): return ""
            async def get_resource(self, rid): return None
            async def get_resources(self, rids): return []
            async def list_resources(self, f): return []
            async def update_resource(self, rid, u): return None
            async def delete_resource(self, rid, *, hard=False): pass
            async def store_chunks(self, rid, c): pass
            async def search(self, q): return []
            async def get_all_hashes(self): return []
            async def get_chunks_for_resource(self, rid): return []
            async def restore_resource(self, rid): return None
            async def get_provenance(self, rid): return []
            async def store_provenance(self, *a, **k): pass
            async def store_collection(self, *a): pass
            async def list_collections(self): return []
            async def count_resources(self, tid): return 0
            async def find_by_cid(self, cid, tid=None): return None
            async def grep(self, kw, **k): return []
            async def get_embedding_dimension(self): return None

        vault = AsyncVault(tmp_vault_path, storage=MinimalBackend())
        assert vault.graph is None


# --- List Nodes Pagination ---

class TestListNodesPagination:
    async def test_list_nodes_with_offset(self, vault, tenant_id):
        for i in range(5):
            await vault.graph.create_node(name=f"Page{i}", entity_type="t", tenant_id=tenant_id)

        first_page, total = await vault.graph.list_nodes(limit=2, offset=0)
        assert len(first_page) == 2
        assert total == 5

        second_page, _ = await vault.graph.list_nodes(limit=2, offset=2)
        assert len(second_page) == 2

        first_ids = {n.id for n in first_page}
        second_ids = {n.id for n in second_page}
        assert first_ids.isdisjoint(second_ids)

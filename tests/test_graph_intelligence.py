"""Tests for graph intelligence services (TI-2.* from 17-testing.md).

Covers membrane sanitization, knowledge extraction, entity resolution,
entity detection, entity materialization, wikilinks, and graph-augmented search.
"""

from __future__ import annotations

import json
import uuid

import pytest

from qp_vault import AsyncVault
from qp_vault.graph.detection import EntityDetector
from qp_vault.graph.extraction import KnowledgeExtractor, KnowledgeGraph, Entity, Relationship
from qp_vault.graph.materialization import EntityMaterializer
from qp_vault.graph.resolution import EntityResolver
from qp_vault.graph.wikilinks import parse_wikilinks, resolve_wikilinks, WikilinkRef
from qp_vault.membrane.sanitize import sanitize_for_extraction


@pytest.fixture
async def vault(tmp_vault_path):
    """Create an AsyncVault with SQLite backend (graph-enabled)."""
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


# --- Membrane Sanitization (TI-2.0) ---

class TestMembraneSanitize:
    def test_sanitize_normalizes_unicode(self):
        result = sanitize_for_extraction("\ufb01")  # fi ligature
        assert "fi" in result

    def test_sanitize_escapes_html(self):
        result = sanitize_for_extraction("malicious <script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_sanitize_wraps_in_xml_tags(self):
        result = sanitize_for_extraction("hello")
        assert "<EXTERNAL_DOCUMENT_CONTENT>" in result
        assert "</EXTERNAL_DOCUMENT_CONTENT>" in result

    def test_sanitize_truncates(self):
        long_text = "x" * 20_000
        result = sanitize_for_extraction(long_text, max_length=100)
        assert len(result) < 20_000

    def test_sanitize_empty(self):
        assert sanitize_for_extraction("") == ""

    def test_sanitize_custom_label(self):
        result = sanitize_for_extraction("test", source_label="EMAIL")
        assert "<EXTERNAL_EMAIL_CONTENT>" in result


# --- KnowledgeExtractor (TI-2.1 through TI-2.6) ---

class TestKnowledgeExtractor:
    async def test_extract_parses_llm_response(self):
        llm_response = json.dumps({
            "entities": [
                {"name": "Alice", "type": "person", "properties": {"role": "engineer"}},
                {"name": "Acme Corp", "type": "company", "properties": {}},
            ],
            "relationships": [
                {"source": "Alice", "target": "Acme Corp", "type": "works_at", "description": "Senior role"},
            ],
        })

        async def mock_chat(messages, temp):
            return llm_response

        extractor = KnowledgeExtractor(chat_fn=mock_chat)
        graph = await extractor.extract("Alice works at Acme Corp", query="test")

        assert len(graph.entities) == 2
        assert len(graph.relationships) == 1
        assert graph.entities[0].name == "Alice"
        assert graph.relationships[0].relation_type == "works_at"

    async def test_extract_handles_markdown_fenced_json(self):
        llm_response = '```json\n{"entities": [{"name": "Bob", "type": "person", "properties": {}}], "relationships": []}\n```'

        async def mock_chat(messages, temp):
            return llm_response

        extractor = KnowledgeExtractor(chat_fn=mock_chat)
        graph = await extractor.extract("Bob is here")
        assert len(graph.entities) == 1
        assert graph.entities[0].name == "Bob"

    async def test_extract_handles_llm_failure(self):
        async def failing_chat(messages, temp):
            raise RuntimeError("LLM unavailable")

        extractor = KnowledgeExtractor(chat_fn=failing_chat)
        graph = await extractor.extract("test text")
        assert len(graph.entities) == 0
        assert len(graph.relationships) == 0

    async def test_validate_caps_entities(self):
        parsed = {
            "entities": [{"name": f"E{i}", "type": "t", "properties": {}} for i in range(300)],
            "relationships": [],
        }
        result = KnowledgeExtractor._validate_extraction(parsed)
        assert len(result["entities"]) == 200

    async def test_validate_caps_relationships(self):
        parsed = {
            "entities": [],
            "relationships": [{"source": "A", "target": "B", "type": "r"} for _ in range(600)],
        }
        result = KnowledgeExtractor._validate_extraction(parsed)
        assert len(result["relationships"]) == 500

    async def test_validate_rejects_invalid_entities(self):
        parsed = {
            "entities": [
                {"name": "", "type": "t", "properties": {}},
                {"name": None, "type": "t", "properties": {}},
                {"name": "Valid", "type": "t", "properties": {}},
            ],
            "relationships": [],
        }
        result = KnowledgeExtractor._validate_extraction(parsed)
        assert len(result["entities"]) == 1
        assert result["entities"][0]["name"] == "Valid"

    async def test_to_wikilink_markdown(self):
        graph = KnowledgeGraph(
            entities=[Entity(name="Alice", entity_type="person")],
            relationships=[Relationship(source="Alice", target="Bob", relation_type="knows")],
            source_query="test",
        )
        extractor = KnowledgeExtractor(chat_fn=lambda m, t: "")
        md = extractor.to_wikilink_markdown(graph)
        assert "[[Alice]]" in md
        assert "knows" in md

    async def test_persist_to_graph(self, vault, tenant_id):
        graph = KnowledgeGraph(
            entities=[
                Entity(name="Jane", entity_type="person"),
                Entity(name="MIT", entity_type="organization"),
            ],
            relationships=[
                Relationship(source="Jane", target="MIT", relation_type="affiliated_with"),
            ],
            source_query="test",
        )

        async def mock_chat(messages, temp):
            return ""

        extractor = KnowledgeExtractor(chat_fn=mock_chat)
        resolver = EntityResolver(vault.graph)
        extractor.set_graph_services(vault.graph, resolver)

        resource = await vault.add("Jane is affiliated with MIT", name="doc.md")
        node_ids, edge_ids = await extractor.persist_to_graph(
            graph, resource_id=resource.id,
        )
        assert len(node_ids) == 2
        assert len(edge_ids) == 1


# --- EntityResolver (TI-2.7 through TI-2.9) ---

class TestEntityResolver:
    async def test_resolve_exact_match(self, vault, tenant_id):
        await vault.graph.create_node(
            name="OpenAI", entity_type="company", tenant_id=tenant_id,
        )
        resolver = EntityResolver(vault.graph)
        node = await resolver.resolve("OpenAI", "company")
        assert node is not None
        assert node.name == "OpenAI"

    async def test_resolve_case_insensitive(self, vault, tenant_id):
        await vault.graph.create_node(
            name="OpenAI", entity_type="company", tenant_id=tenant_id,
        )
        resolver = EntityResolver(vault.graph)
        node = await resolver.resolve("openai", "company")
        assert node is not None
        assert node.name == "OpenAI"

    async def test_resolve_or_create_new(self, vault, tenant_id):
        resolver = EntityResolver(vault.graph)
        node = await resolver.resolve_or_create(
            "NewCorp", "company",
        )
        assert node is not None
        assert node.name == "NewCorp"

        fetched = await vault.graph.get_node(node.id)
        assert fetched is not None

    async def test_resolve_or_create_returns_existing(self, vault, tenant_id):
        existing = await vault.graph.create_node(
            name="ExistingCo", entity_type="company", tenant_id=tenant_id,
        )
        resolver = EntityResolver(vault.graph)
        node = await resolver.resolve_or_create("ExistingCo", "company")
        assert node.id == existing.id

    async def test_resolve_by_name_any_type(self, vault, tenant_id):
        await vault.graph.create_node(
            name="Turing", entity_type="person", tenant_id=tenant_id,
        )
        resolver = EntityResolver(vault.graph)
        node = await resolver.resolve_by_name("Turing")
        assert node is not None
        assert node.entity_type == "person"


# --- EntityDetector (TI-2.10 through TI-2.13) ---

class TestEntityDetector:
    async def test_detect_exact_match(self, vault, tenant_id):
        await vault.graph.create_node(
            name="Quantum Computing", entity_type="concept", tenant_id=tenant_id,
        )
        detector = EntityDetector(vault.graph)
        results = await detector.detect(
            "We are investing in quantum computing and AI",
        )
        assert len(results) >= 1
        assert any(d.name == "Quantum Computing" for d in results)

    async def test_detect_multiple_entities(self, vault, tenant_id):
        await vault.graph.create_node(name="Alice", entity_type="person", tenant_id=tenant_id)
        await vault.graph.create_node(name="Acme", entity_type="company", tenant_id=tenant_id)
        detector = EntityDetector(vault.graph)
        results = await detector.detect("Alice works at Acme on AI projects")
        names = {d.name for d in results}
        assert "Alice" in names
        assert "Acme" in names

    async def test_detect_empty_text(self, vault):
        detector = EntityDetector(vault.graph)
        results = await detector.detect("")
        assert results == []

    async def test_detect_text_cap(self, vault, tenant_id):
        await vault.graph.create_node(name="Target", entity_type="t", tenant_id=tenant_id)
        detector = EntityDetector(vault.graph)
        long_text = "x" * 60_000 + " Target"
        results = await detector.detect(long_text)
        assert len(results) == 0  # "Target" is beyond the 50k cap

    async def test_detect_ids_convenience(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Quick", entity_type="t", tenant_id=tenant_id)
        detector = EntityDetector(vault.graph)
        ids = await detector.detect_ids("Quick test")
        assert node.id in ids


# --- WikilinkResolver (TI-2.15) ---

class TestWikilinks:
    def test_parse_simple_wikilink(self):
        refs = parse_wikilinks("See [[Alice]] for details")
        assert len(refs) == 1
        assert refs[0].name == "Alice"
        assert refs[0].display_text is None

    def test_parse_display_text(self):
        refs = parse_wikilinks("Check [[Alice|Prof. Alice]]")
        assert len(refs) == 1
        assert refs[0].name == "Alice"
        assert refs[0].display_text == "Prof. Alice"

    def test_parse_multiple(self):
        refs = parse_wikilinks("[[A]] and [[B]] and [[C]]")
        assert len(refs) == 3

    def test_parse_skips_code_fence(self):
        text = "```\n[[NotALink]]\n```\n[[RealLink]]"
        refs = parse_wikilinks(text)
        assert len(refs) == 1
        assert refs[0].name == "RealLink"

    def test_parse_skips_inline_code(self):
        refs = parse_wikilinks("`[[Code]]` and [[Real]]")
        assert len(refs) == 1
        assert refs[0].name == "Real"

    def test_parse_deduplicates(self):
        refs = parse_wikilinks("[[Alice]] and [[alice]]")
        assert len(refs) == 1

    def test_parse_empty(self):
        assert parse_wikilinks("") == []

    async def test_resolve_wikilinks(self, vault, tenant_id):
        await vault.graph.create_node(
            name="Alice", entity_type="person", tenant_id=tenant_id,
        )
        resolver = EntityResolver(vault.graph)
        refs = [WikilinkRef(name="Alice", display_text=None, start=0, end=9)]
        resolved = await resolve_wikilinks(refs, resolver)
        assert len(resolved) == 1
        assert resolved[0].resolved is True
        assert resolved[0].node_id is not None

    async def test_resolve_unresolved(self, vault):
        resolver = EntityResolver(vault.graph)
        refs = [WikilinkRef(name="Unknown", display_text=None, start=0, end=11)]
        resolved = await resolve_wikilinks(refs, resolver)
        assert len(resolved) == 1
        assert resolved[0].resolved is False


# --- Graph-Augmented Search (TI-2.16, TI-2.17) ---

class TestGraphAugmentedSearch:
    async def test_search_default_no_graph_boost(self, vault):
        await vault.add("Document about machine learning models", name="ml.md")
        results = await vault.search("machine learning")
        assert isinstance(results, list)

    async def test_search_with_graph_boost_no_crash(self, vault, tenant_id):
        await vault.add("Document about quantum physics", name="physics.md")
        await vault.graph.create_node(
            name="quantum physics", entity_type="concept", tenant_id=tenant_id,
        )
        results = await vault.search("quantum physics", graph_boost=True)
        assert isinstance(results, list)

    async def test_graph_boost_false_is_default(self, vault):
        await vault.add("Test content", name="test.md")
        results = await vault.search("test")
        assert isinstance(results, list)

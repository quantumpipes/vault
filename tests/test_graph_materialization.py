"""Tests for EntityMaterializer (profile.md + manifest.json generation).

Covers: basic materialization, profile content structure, manifest JSON
validity, missing node error, relationships in profile, mentions in profile.
"""

from __future__ import annotations

import json
import uuid

import pytest

from qp_vault import AsyncVault
from qp_vault.graph.materialization import EntityMaterializer


@pytest.fixture
async def vault(tmp_vault_path):
    v = AsyncVault(tmp_vault_path)
    await v._ensure_initialized()
    return v


@pytest.fixture
def tenant_id():
    return str(uuid.uuid4())


class TestEntityMaterializer:
    async def test_materialize_creates_resources(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="Alice Wonderland",
            entity_type="person",
            properties={"role": "engineer", "team": "platform"},
            tags=["vip", "founder"],
            tenant_id=tenant_id,
        )
        materializer = EntityMaterializer(vault.graph, vault)
        result = await materializer.materialize(node.id)

        assert result["profile_resource_id"] is not None
        assert result["manifest_resource_id"] is not None

    async def test_materialize_nonexistent_node_raises(self, vault):
        materializer = EntityMaterializer(vault.graph, vault)
        with pytest.raises(ValueError, match="not found"):
            await materializer.materialize(uuid.uuid4())

    async def test_profile_contains_expected_sections(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="TestEntity",
            entity_type="concept",
            properties={"domain": "AI"},
            tags=["research"],
            tenant_id=tenant_id,
        )
        materializer = EntityMaterializer(vault.graph, vault)
        profile = await materializer._build_profile(node)

        assert "# TestEntity" in profile
        assert "**Type:** concept" in profile
        assert "## Properties" in profile
        assert "domain" in profile
        assert "AI" in profile
        assert "## Tags" in profile
        assert "`research`" in profile
        assert f"`{node.slug}`" in profile

    async def test_profile_includes_relationships(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="Alice", entity_type="person", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="Acme", entity_type="company", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="works_at", tenant_id=tenant_id,
        )
        materializer = EntityMaterializer(vault.graph, vault)
        profile = await materializer._build_profile(n1)

        assert "## Relationships" in profile
        assert "works_at" in profile
        assert "[[Acme]]" in profile

    async def test_profile_includes_mentions(self, vault, tenant_id):
        node = await vault.graph.create_node(name="Mentioned", entity_type="t", tenant_id=tenant_id)
        resource = await vault.add("Some content", name="doc.md")
        await vault.graph.track_mention(
            node.id, resource.id, context_snippet="mentioned in context",
        )
        materializer = EntityMaterializer(vault.graph, vault)
        profile = await materializer._build_profile(node)

        assert "## Mentions" in profile
        assert "mentioned in context" in profile

    async def test_manifest_is_valid_json(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="JSONTest",
            entity_type="thing",
            properties={"key": "value"},
            tenant_id=tenant_id,
        )
        materializer = EntityMaterializer(vault.graph, vault)
        manifest_str = await materializer._build_manifest(node)
        manifest = json.loads(manifest_str)

        assert manifest["schema_version"] == "1.0"
        assert manifest["name"] == "JSONTest"
        assert manifest["entity_type"] == "thing"
        assert manifest["properties"]["key"] == "value"
        assert manifest["slug"] == node.slug
        assert "materialized_at" in manifest

    async def test_manifest_includes_relationships(self, vault, tenant_id):
        n1 = await vault.graph.create_node(name="M1", entity_type="t", tenant_id=tenant_id)
        n2 = await vault.graph.create_node(name="M2", entity_type="t", tenant_id=tenant_id)
        await vault.graph.create_edge(
            source_id=n1.id, target_id=n2.id,
            relation_type="related", tenant_id=tenant_id,
        )
        materializer = EntityMaterializer(vault.graph, vault)
        manifest_str = await materializer._build_manifest(n1)
        manifest = json.loads(manifest_str)

        assert len(manifest["relationships"]) == 1
        assert manifest["relationships"][0]["relation_type"] == "related"
        assert manifest["relationships"][0]["direction"] == "outgoing"
        assert manifest["relationships"][0]["target_name"] == "M2"

    async def test_profile_minimal_node(self, vault, tenant_id):
        node = await vault.graph.create_node(
            name="Bare", entity_type="t", tenant_id=tenant_id,
        )
        materializer = EntityMaterializer(vault.graph, vault)
        profile = await materializer._build_profile(node)
        assert "# Bare" in profile
        assert "Properties" not in profile
        assert "Tags" not in profile
        assert "Relationships" not in profile
        assert "Mentions" not in profile

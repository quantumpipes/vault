"""Tests for graph domain models (Pydantic validation and field constraints).

Covers: GraphNode, GraphEdge, GraphMention, NeighborResult, GraphScanJob,
DetectedEntity field validation, defaults, and constraints.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from qp_vault.graph.models import (
    DetectedEntity,
    GraphEdge,
    GraphMention,
    GraphNode,
    GraphScanJob,
    NeighborResult,
)


class TestGraphNodeModel:
    def test_required_fields(self):
        node = GraphNode(name="Alice", slug="alice", entity_type="person")
        assert node.name == "Alice"
        assert node.slug == "alice"
        assert node.entity_type == "person"
        assert isinstance(node.id, UUID)
        assert isinstance(node.tenant_id, UUID)

    def test_defaults(self):
        node = GraphNode(name="X", slug="x", entity_type="t")
        assert node.properties == {}
        assert node.tags == []
        assert node.primary_space_id is None
        assert node.resource_id is None
        assert node.manifest_resource_id is None
        assert node.mention_count == 0
        assert node.last_mentioned_at is None
        assert node.created_at is not None
        assert node.updated_at is not None

    def test_mention_count_rejects_negative(self):
        with pytest.raises(ValidationError):
            GraphNode(name="X", slug="x", entity_type="t", mention_count=-1)

    def test_from_attributes_config(self):
        assert GraphNode.model_config.get("from_attributes") is True


class TestGraphEdgeModel:
    def test_required_fields(self):
        src, tgt = uuid4(), uuid4()
        edge = GraphEdge(source_node_id=src, target_node_id=tgt, relation_type="knows")
        assert edge.source_node_id == src
        assert edge.target_node_id == tgt
        assert edge.relation_type == "knows"

    def test_weight_default(self):
        edge = GraphEdge(source_node_id=uuid4(), target_node_id=uuid4(), relation_type="r")
        assert edge.weight == 0.5

    def test_weight_bounds(self):
        edge = GraphEdge(
            source_node_id=uuid4(), target_node_id=uuid4(),
            relation_type="r", weight=0.0,
        )
        assert edge.weight == 0.0

        edge = GraphEdge(
            source_node_id=uuid4(), target_node_id=uuid4(),
            relation_type="r", weight=1.0,
        )
        assert edge.weight == 1.0

    def test_weight_out_of_bounds_rejected(self):
        with pytest.raises(ValidationError):
            GraphEdge(
                source_node_id=uuid4(), target_node_id=uuid4(),
                relation_type="r", weight=1.5,
            )
        with pytest.raises(ValidationError):
            GraphEdge(
                source_node_id=uuid4(), target_node_id=uuid4(),
                relation_type="r", weight=-0.1,
            )

    def test_bidirectional_default_false(self):
        edge = GraphEdge(source_node_id=uuid4(), target_node_id=uuid4(), relation_type="r")
        assert edge.bidirectional is False


class TestGraphMentionModel:
    def test_required_fields(self):
        nid, rid = uuid4(), uuid4()
        mention = GraphMention(node_id=nid, resource_id=rid)
        assert mention.node_id == nid
        assert mention.resource_id == rid
        assert mention.context_snippet == ""

    def test_space_id_optional(self):
        mention = GraphMention(node_id=uuid4(), resource_id=uuid4())
        assert mention.space_id is None


class TestNeighborResultModel:
    def test_minimal(self):
        nr = NeighborResult(node_id=uuid4(), node_name="X", entity_type="t", depth=1)
        assert nr.depth == 1
        assert nr.path == []
        assert nr.relation_type is None
        assert nr.edge_weight is None


class TestGraphScanJobModel:
    def test_defaults(self):
        job = GraphScanJob(space_id=uuid4())
        assert job.status == "running"
        assert job.finished_at is None
        assert job.summary is None
        assert job.error is None

    def test_with_summary(self):
        job = GraphScanJob(
            space_id=uuid4(),
            status="completed",
            summary={"entities": 5, "edges": 3},
        )
        assert job.summary["entities"] == 5


class TestDetectedEntityModel:
    def test_defaults(self):
        de = DetectedEntity(name="Alice")
        assert de.entity_type == "unknown"
        assert de.node_id is None
        assert de.confidence == 1.0
        assert de.start is None
        assert de.end is None

    def test_confidence_bounds(self):
        de = DetectedEntity(name="X", confidence=0.0)
        assert de.confidence == 0.0
        de = DetectedEntity(name="X", confidence=1.0)
        assert de.confidence == 1.0

    def test_confidence_out_of_bounds(self):
        with pytest.raises(ValidationError):
            DetectedEntity(name="X", confidence=1.5)
        with pytest.raises(ValidationError):
            DetectedEntity(name="X", confidence=-0.1)

"""Tests for advanced integrity detection: near-duplicates and contradictions."""

from __future__ import annotations

from datetime import UTC, datetime

from qp_vault.integrity.detector import detect_contradictions, find_near_duplicates
from qp_vault.models import Chunk, Resource


def _resource(name: str, trust_tier: str = "working", lifecycle: str = "active") -> Resource:
    now = datetime.now(tz=UTC)
    return Resource(
        id=f"r-{name}", name=name, content_hash=f"h-{name}", cid=f"v://h-{name}",
        trust_tier=trust_tier, lifecycle=lifecycle, created_at=now, updated_at=now,
    )


def _chunks(resource_id: str, embedding: list[float]) -> list[Chunk]:
    return [Chunk(id=f"c-{resource_id}", resource_id=resource_id,
                  content="test", cid="v://c", embedding=embedding, chunk_index=0)]


class TestNearDuplicates:
    def test_similar_resources_detected(self):
        r1 = _resource("a.md")
        r2 = _resource("b.md")
        chunks = {
            r1.id: _chunks(r1.id, [1.0, 0.0, 0.0]),
            r2.id: _chunks(r2.id, [0.99, 0.1, 0.0]),  # Very similar
        }
        pairs = find_near_duplicates([r1, r2], chunks, similarity_threshold=0.9)
        assert len(pairs) >= 1
        assert pairs[0][2] > 0.9  # High similarity

    def test_different_resources_not_flagged(self):
        r1 = _resource("a.md")
        r2 = _resource("b.md")
        chunks = {
            r1.id: _chunks(r1.id, [1.0, 0.0, 0.0]),
            r2.id: _chunks(r2.id, [0.0, 1.0, 0.0]),  # Orthogonal
        }
        pairs = find_near_duplicates([r1, r2], chunks, similarity_threshold=0.85)
        assert len(pairs) == 0

    def test_no_chunks_returns_empty(self):
        r1 = _resource("a.md")
        pairs = find_near_duplicates([r1], None)
        assert pairs == []

    def test_empty_embeddings_skipped(self):
        r1 = _resource("a.md")
        r2 = _resource("b.md")
        chunks = {
            r1.id: _chunks(r1.id, []),
            r2.id: _chunks(r2.id, []),
        }
        pairs = find_near_duplicates([r1, r2], chunks)
        assert len(pairs) == 0


class TestContradictions:
    def test_trust_conflict_detected(self):
        r1 = _resource("a.md", trust_tier="canonical")
        r2 = _resource("b.md", trust_tier="working")
        chunks = {
            r1.id: _chunks(r1.id, [1.0, 0.0]),
            r2.id: _chunks(r2.id, [0.99, 0.1]),  # Similar content, different trust
        }
        contradictions = detect_contradictions([r1, r2], chunks)
        trust_conflicts = [c for c in contradictions if c["type"] == "trust_conflict"]
        assert len(trust_conflicts) >= 1

    def test_lifecycle_conflict_detected(self):
        r1 = _resource("a.md", lifecycle="active")
        r2 = _resource("b.md", lifecycle="superseded")
        chunks = {
            r1.id: _chunks(r1.id, [1.0, 0.0]),
            r2.id: _chunks(r2.id, [0.99, 0.1]),
        }
        contradictions = detect_contradictions([r1, r2], chunks)
        lc_conflicts = [c for c in contradictions if c["type"] == "lifecycle_conflict"]
        assert len(lc_conflicts) >= 1

    def test_no_contradictions_when_aligned(self):
        r1 = _resource("a.md", trust_tier="canonical")
        r2 = _resource("b.md", trust_tier="canonical")
        chunks = {
            r1.id: _chunks(r1.id, [1.0, 0.0]),
            r2.id: _chunks(r2.id, [0.99, 0.1]),
        }
        contradictions = detect_contradictions([r1, r2], chunks)
        trust_conflicts = [c for c in contradictions if c["type"] == "trust_conflict"]
        assert len(trust_conflicts) == 0

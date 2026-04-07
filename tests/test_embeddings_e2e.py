"""End-to-end embedding tests: verify that vector search actually works.

Tests SentenceTransformerEmbedder with real models through the full
vault pipeline: add -> embed -> search -> ranked results.

Requires: pip install qp-vault[local] (sentence-transformers)
Skipped if not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

try:
    import sentence_transformers  # noqa: F401

    HAS_ST = True
except ImportError:
    HAS_ST = False

pytestmark = pytest.mark.skipif(not HAS_ST, reason="sentence-transformers not installed")

if TYPE_CHECKING:
    from pathlib import Path


class TestSentenceTransformerEmbedder:
    """Unit tests for the embedder itself."""

    def test_default_model_dimensions(self) -> None:
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()  # all-MiniLM-L6-v2
        assert e.dimensions == 384

    def test_is_local(self) -> None:
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()
        assert e.is_local is True

    @pytest.mark.asyncio
    async def test_embed_single(self) -> None:
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()
        vecs = await e.embed(["hello world"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 384

    @pytest.mark.asyncio
    async def test_embed_batch(self) -> None:
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()
        vecs = await e.embed(["hello", "world", "test"])
        assert len(vecs) == 3
        assert all(len(v) == 384 for v in vecs)

    @pytest.mark.asyncio
    async def test_similar_texts_have_high_similarity(self) -> None:
        """Verify that semantically similar texts produce similar embeddings."""
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        e = SentenceTransformerEmbedder()
        vecs = await e.embed([
            "The cat sat on the mat",
            "A feline rested on the rug",
            "Quantum computing uses qubits",
        ])

        # Cosine similarity helper
        def cosine(a: list[float], b: list[float]) -> float:
            import math

            dot = sum(x * y for x, y in zip(a, b, strict=False))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0.0

        # Similar texts should have higher similarity than dissimilar
        sim_cats = cosine(vecs[0], vecs[1])
        sim_unrelated = cosine(vecs[0], vecs[2])
        assert sim_cats > sim_unrelated


class TestVaultWithEmbeddings:
    """End-to-end: vault add + search with real embeddings."""

    def test_semantic_search_ranks_correctly(self, tmp_path: Path) -> None:
        """Semantic search should rank relevant docs higher than irrelevant."""
        from qp_vault import Vault
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        vault = Vault(tmp_path / "e2e", embedder=SentenceTransformerEmbedder())

        vault.add(
            "Python is a programming language used for web development and data science",
            name="python.md",
        )
        vault.add(
            "Chocolate cake recipe: mix flour, sugar, cocoa powder, and eggs",
            name="recipe.md",
        )
        vault.add(
            "Machine learning models are trained on large datasets using neural networks",
            name="ml.md",
        )

        results = vault.search("artificial intelligence and deep learning")
        assert len(results) >= 1
        # ML doc should rank higher than recipe for an AI query
        names = [r.resource_name for r in results]
        if "ml.md" in names and "recipe.md" in names:
            ml_idx = names.index("ml.md")
            recipe_idx = names.index("recipe.md")
            assert ml_idx < recipe_idx, "ML doc should rank above recipe for AI query"

    def test_search_with_trust_weighting(self, tmp_path: Path) -> None:
        """Trust tier should influence ranking alongside vector similarity."""
        from qp_vault import Vault
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        vault = Vault(tmp_path / "trust", embedder=SentenceTransformerEmbedder())

        vault.add(
            "Security incident response procedure for production outages",
            name="sop.md",
            trust_tier="canonical",  # 1.5x boost
        )
        vault.add(
            "Draft notes about incident response improvements",
            name="draft.md",
            trust_tier="ephemeral",  # 0.7x penalty
        )

        results = vault.search("incident response")
        assert len(results) >= 1
        # Both are relevant, but canonical should outrank ephemeral
        if len(results) >= 2:
            assert results[0].resource_name == "sop.md"

    def test_confidential_with_local_embedder(self, tmp_path: Path) -> None:
        """CONFIDENTIAL content should work with local embedder."""
        from qp_vault import Vault
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        vault = Vault(tmp_path / "conf", embedder=SentenceTransformerEmbedder())
        r = vault.add(
            "Confidential financial projections for Q4",
            name="finance.md",
            classification="confidential",
        )
        assert r.id
        # Should be searchable
        results = vault.search("financial projections")
        assert len(results) >= 1

    def test_dedup_with_embeddings(self, tmp_path: Path) -> None:
        """Content dedup should work even with embeddings."""
        from qp_vault import Vault
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        vault = Vault(tmp_path / "dedup", embedder=SentenceTransformerEmbedder())
        r1 = vault.add("Exact same content for dedup test", name="a.md")
        r2 = vault.add("Exact same content for dedup test", name="b.md")
        assert r1.id == r2.id  # Dedup returns existing

    def test_export_import_preserves_searchability(self, tmp_path: Path) -> None:
        """Exported and re-imported vault should still be searchable."""
        from qp_vault import Vault
        from qp_vault.embeddings.sentence import SentenceTransformerEmbedder

        v1 = Vault(tmp_path / "exp", embedder=SentenceTransformerEmbedder())
        v1.add("Important security policy document", name="policy.md")
        v1.export_vault(str(tmp_path / "backup.json"))

        v2 = Vault(tmp_path / "imp", embedder=SentenceTransformerEmbedder())
        v2.import_vault(str(tmp_path / "backup.json"))

        results = v2.search("security policy")
        assert len(results) >= 1
        assert "policy" in results[0].resource_name

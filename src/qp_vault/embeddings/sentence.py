# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Sentence Transformers embedding provider (local, air-gap safe).

Requires: pip install sentence-transformers
"""

from __future__ import annotations

try:
    from sentence_transformers import SentenceTransformer
    HAS_ST = True
except ImportError:
    HAS_ST = False


class SentenceTransformerEmbedder:
    """Local embedding using sentence-transformers.

    Default model: all-MiniLM-L6-v2 (384 dimensions, fast, good quality).
    Air-gap safe: runs entirely on CPU, no internet after initial download.

    Args:
        model_name: HuggingFace model name. Default: all-MiniLM-L6-v2.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        if not HAS_ST:
            raise ImportError(
                "sentence-transformers is required. "
                "Install with: pip install sentence-transformers"
            )
        self._model = SentenceTransformer(model_name)
        self._dimensions = self._model.get_sentence_embedding_dimension()

    @property
    def dimensions(self) -> int:
        return int(self._dimensions or 0)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()  # type: ignore[no-any-return]

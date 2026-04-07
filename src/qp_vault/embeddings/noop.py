# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Noop embedding provider: explicit text-only search.

Use this when you intentionally want text-only search (FTS5/pg_trgm)
without vector similarity. Makes the choice explicit instead of silent.
"""

from __future__ import annotations


class NoopEmbedder:
    """Embedding provider that returns zero vectors.

    Makes text-only search an explicit choice. When used, the search
    formula degrades to: relevance = text_rank * trust_weight * freshness.
    """

    @property
    def dimensions(self) -> int:
        return 0

    @property
    def is_local(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return empty embeddings (text-only mode)."""
        return [[] for _ in texts]

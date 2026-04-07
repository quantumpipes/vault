"""Tests for NoopEmbedder (text-only search mode)."""

from __future__ import annotations

import pytest

from qp_vault.embeddings.noop import NoopEmbedder


class TestNoopEmbedder:
    def test_dimensions_zero(self):
        e = NoopEmbedder()
        assert e.dimensions == 0

    @pytest.mark.asyncio
    async def test_embed_returns_empty_lists(self):
        e = NoopEmbedder()
        result = await e.embed(["hello", "world"])
        assert result == [[], []]

    @pytest.mark.asyncio
    async def test_embed_empty_input(self):
        e = NoopEmbedder()
        result = await e.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embed_single(self):
        e = NoopEmbedder()
        result = await e.embed(["test"])
        assert len(result) == 1
        assert result[0] == []

# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""OpenAI embedding provider (cloud).

Requires: pip install openai
"""

from __future__ import annotations

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class OpenAIEmbedder:
    """OpenAI text-embedding-3-small (1536 dimensions).

    Requires OPENAI_API_KEY environment variable or explicit api_key.

    Args:
        model: OpenAI embedding model name.
        api_key: Optional API key (defaults to OPENAI_API_KEY env var).
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
    ) -> None:
        if not HAS_OPENAI:
            raise ImportError(
                "openai is required. Install with: pip install openai"
            )
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()
        self._dimensions = 1536 if "small" in model else 3072

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via OpenAI API."""
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [d.embedding for d in response.data]

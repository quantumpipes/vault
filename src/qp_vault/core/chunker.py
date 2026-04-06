"""Semantic text chunking for qp-vault.

Splits text into semantically meaningful chunks with configurable
target size, overlap, and section awareness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ChunkResult:
    """A single chunk produced by the chunker."""

    content: str
    chunk_index: int
    token_count: int
    page_number: int | None = None
    section_title: str | None = None


@dataclass
class ChunkerConfig:
    """Configuration for the semantic chunker."""

    target_tokens: int = 512
    min_tokens: int = 100
    max_tokens: int = 1024
    overlap_tokens: int = 50


def estimate_tokens(text: str) -> int:
    """Estimate token count using whitespace splitting.

    This is a fast approximation. For precise counts, use tiktoken.
    Roughly 1 token per 0.75 words for English text.
    """
    words = len(text.split())
    return int(words / 0.75)


def chunk_text(
    text: str,
    config: ChunkerConfig | None = None,
) -> list[ChunkResult]:
    """Split text into semantic chunks.

    Strategy:
    1. Split on paragraph boundaries (double newline)
    2. Accumulate paragraphs until target token count
    3. Apply overlap by including trailing tokens from previous chunk

    Args:
        text: The text to chunk.
        config: Chunking configuration.

    Returns:
        List of ChunkResult with content and metadata.
    """
    if config is None:
        config = ChunkerConfig()

    if not text or not text.strip():
        return []

    # Split into paragraphs
    paragraphs = re.split(r"\n\s*\n", text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[ChunkResult] = []
    current_paragraphs: list[str] = []
    current_tokens = 0
    chunk_index = 0

    # Track section titles (markdown headers)
    current_section: str | None = None

    for para in paragraphs:
        # Detect section headers
        header_match = re.match(r"^#{1,6}\s+(.+)$", para, re.MULTILINE)
        if header_match:
            current_section = header_match.group(1).strip()

        para_tokens = estimate_tokens(para)

        # If adding this paragraph exceeds max, flush current chunk
        if current_tokens + para_tokens > config.max_tokens and current_paragraphs:
            chunk_content = "\n\n".join(current_paragraphs)
            chunks.append(
                ChunkResult(
                    content=chunk_content,
                    chunk_index=chunk_index,
                    token_count=estimate_tokens(chunk_content),
                    section_title=current_section,
                )
            )
            chunk_index += 1

            # Apply overlap: keep last paragraph(s) up to overlap_tokens
            overlap_paras: list[str] = []
            overlap_count = 0
            for p in reversed(current_paragraphs):
                p_tokens = estimate_tokens(p)
                if overlap_count + p_tokens <= config.overlap_tokens:
                    overlap_paras.insert(0, p)
                    overlap_count += p_tokens
                else:
                    break

            current_paragraphs = overlap_paras
            current_tokens = overlap_count

        current_paragraphs.append(para)
        current_tokens += para_tokens

        # If we've reached target and next paragraph would be new content, flush
        if current_tokens >= config.target_tokens:
            chunk_content = "\n\n".join(current_paragraphs)
            chunks.append(
                ChunkResult(
                    content=chunk_content,
                    chunk_index=chunk_index,
                    token_count=estimate_tokens(chunk_content),
                    section_title=current_section,
                )
            )
            chunk_index += 1

            # Apply overlap
            overlap_paras = []
            overlap_count = 0
            for p in reversed(current_paragraphs):
                p_tokens = estimate_tokens(p)
                if overlap_count + p_tokens <= config.overlap_tokens:
                    overlap_paras.insert(0, p)
                    overlap_count += p_tokens
                else:
                    break

            current_paragraphs = overlap_paras
            current_tokens = overlap_count

    # Flush remaining content
    if current_paragraphs:
        chunk_content = "\n\n".join(current_paragraphs)
        chunk_tokens = estimate_tokens(chunk_content)

        # If too small and we have previous chunks, merge with last
        if chunk_tokens < config.min_tokens and chunks:
            last = chunks[-1]
            merged = last.content + "\n\n" + chunk_content
            chunks[-1] = ChunkResult(
                content=merged,
                chunk_index=last.chunk_index,
                token_count=estimate_tokens(merged),
                section_title=last.section_title,
            )
        else:
            chunks.append(
                ChunkResult(
                    content=chunk_content,
                    chunk_index=chunk_index,
                    token_count=chunk_tokens,
                    section_title=current_section,
                )
            )

    return chunks

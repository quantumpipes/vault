# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Shared utilities for the vault grep engine.

Provides FTS5 query building, keyword sanitization, snippet generation,
keyword matching, and term proximity scoring. Used by both SQLiteBackend
and PostgresBackend grep implementations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# FTS5 special characters that must be stripped from keywords
_FTS5_SPECIAL = re.compile(r'[*"()\-{}[\]^~:+]')

# Maximum keyword length to prevent pathological inputs
_MAX_KEYWORD_LENGTH = 200


@dataclass
class GrepMatch:
    """Raw grep result from storage backend.

    Lightweight intermediate type. Not exposed to callers; the vault
    layer converts these to SearchResult with blended scoring.
    """

    chunk_id: str
    resource_id: str
    resource_name: str
    content: str
    matched_keywords: list[str] = field(default_factory=list)
    hit_density: float = 0.0
    text_rank: float = 0.0
    trust_tier: str = "working"
    adversarial_status: str = "unverified"
    lifecycle: str = "active"
    updated_at: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    resource_type: str | None = None
    data_classification: str | None = None
    cid: str | None = None


def sanitize_grep_keyword(keyword: str) -> str:
    """Sanitize a keyword for safe use in FTS5 MATCH or SQL ILIKE.

    Strips FTS5 special characters, collapses whitespace, lowercases,
    and truncates to _MAX_KEYWORD_LENGTH.

    Args:
        keyword: Raw keyword string.

    Returns:
        Cleaned keyword, or empty string if nothing remains.
    """
    cleaned = _FTS5_SPECIAL.sub(" ", keyword)
    cleaned = " ".join(cleaned.split()).lower().strip()
    return cleaned[:_MAX_KEYWORD_LENGTH]


def normalize_keywords(keywords: list[str], max_keywords: int = 20) -> list[str]:
    """Sanitize, deduplicate, and limit a keyword list.

    Args:
        keywords: Raw keyword list from caller.
        max_keywords: Maximum keywords to retain.

    Returns:
        Deduplicated list of sanitized non-empty keywords.
    """
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords[:max_keywords * 2]:  # Allow extra for dedup headroom
        clean = sanitize_grep_keyword(kw)
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
            if len(result) >= max_keywords:
                break
    return result


def build_fts_or_query(keywords: list[str]) -> str:
    """Build an FTS5 OR expression from pre-sanitized keywords.

    Each keyword is double-quoted to treat as a literal phrase.
    Multi-word keywords become phrase matches.

    Args:
        keywords: Pre-sanitized keyword list (from normalize_keywords).

    Returns:
        FTS5 MATCH expression, e.g. '"machine learning" OR "NDA" OR "python"'.
        Empty string if no valid keywords.
    """
    parts = [f'"{kw}"' for kw in keywords if kw]
    return " OR ".join(parts)


def extract_matched_keywords(content: str, keywords: list[str]) -> list[str]:
    """Determine which keywords appear in a content string.

    Case-insensitive substring matching. Runs only on matched rows
    (small set), so Python-side checking is negligible.

    Args:
        content: Chunk text content.
        keywords: Pre-sanitized keyword list.

    Returns:
        List of keywords found in the content.
    """
    content_lower = content.lower()
    return [kw for kw in keywords if kw in content_lower]


def compute_proximity(content: str, matched_keywords: list[str]) -> float:
    """Compute term proximity score for matched keywords within content.

    Measures how close the matched keywords appear to each other.
    Based on cover density ranking (Clarke, Cormack, Tudhope):
    documents where search terms appear near each other rank higher.

    Formula: 1.0 / (1.0 + min_span_chars / total_chars)

    When only 0-1 keywords match, proximity is 1.0 (not penalized).

    Args:
        content: Chunk text content.
        matched_keywords: Keywords confirmed present in content.

    Returns:
        Float 0.0-1.0 where 1.0 = keywords adjacent, 0.0+ = keywords far apart.
    """
    if len(matched_keywords) <= 1:
        return 1.0

    content_lower = content.lower()
    total_chars = len(content_lower)
    if total_chars == 0:
        return 1.0

    # Find first occurrence position and length of each keyword
    hits: list[tuple[int, int]] = []  # (position, keyword_length)
    for kw in matched_keywords:
        idx = content_lower.find(kw)
        if idx >= 0:
            hits.append((idx, len(kw)))

    if len(hits) <= 1:
        return 1.0

    # Minimum spanning window: distance from first to last keyword occurrence
    hits.sort(key=lambda h: h[0])
    last_pos, last_len = hits[-1]
    min_span = last_pos - hits[0][0] + last_len

    return 1.0 / (1.0 + min_span / total_chars)


def generate_snippet(
    content: str,
    keywords: list[str],
    context_chars: int = 80,
    max_length: int = 300,
    marker_start: str = "**",
    marker_end: str = "**",
) -> str:
    """Generate a highlighted snippet showing keyword matches in context.

    Finds the first keyword occurrence and extracts surrounding context.
    All keyword occurrences within the snippet are highlighted.

    Args:
        content: Full chunk text.
        keywords: Keywords to highlight.
        context_chars: Characters of context around first match.
        max_length: Maximum snippet length (before markers).
        marker_start: Opening highlight marker.
        marker_end: Closing highlight marker.

    Returns:
        Highlighted snippet string, or empty string if no matches.
    """
    if not content or not keywords:
        return ""

    content_lower = content.lower()

    # Find the earliest keyword occurrence
    first_pos = len(content)
    for kw in keywords:
        idx = content_lower.find(kw)
        if 0 <= idx < first_pos:
            first_pos = idx

    if first_pos == len(content):
        return ""

    # Extract window around first match
    start = max(0, first_pos - context_chars)
    end = min(len(content), first_pos + context_chars + max_length)
    snippet = content[start:end]

    # Highlight all keyword occurrences (case-insensitive, longest first)
    patterns = [
        (re.compile(re.escape(kw), re.IGNORECASE), kw)
        for kw in sorted(keywords, key=len, reverse=True)
    ]
    for pattern, _kw in patterns:
        snippet = pattern.sub(
            lambda m: f"{marker_start}{m.group()}{marker_end}",
            snippet,
        )

    # Add ellipsis indicators
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""

    return f"{prefix}{snippet}{suffix}"

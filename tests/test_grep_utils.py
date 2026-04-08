# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for grep_utils: FTS query building, keyword sanitization,
snippet generation, keyword matching, and term proximity scoring."""

from __future__ import annotations

from qp_vault.storage.grep_utils import (
    build_fts_or_query,
    compute_proximity,
    extract_matched_keywords,
    generate_snippet,
    normalize_keywords,
    sanitize_grep_keyword,
)


class TestSanitizeGrepKeyword:
    def test_strips_fts5_operators(self) -> None:
        assert sanitize_grep_keyword('"hello" AND "world"') == "hello and world"

    def test_strips_special_chars(self) -> None:
        assert sanitize_grep_keyword("test*query(foo)") == "test query foo"

    def test_collapses_whitespace(self) -> None:
        assert sanitize_grep_keyword("  lots   of   spaces  ") == "lots of spaces"

    def test_lowercases(self) -> None:
        assert sanitize_grep_keyword("Python") == "python"

    def test_truncates_long_keywords(self) -> None:
        long_kw = "a" * 500
        result = sanitize_grep_keyword(long_kw)
        assert len(result) == 200

    def test_empty_after_strip(self) -> None:
        assert sanitize_grep_keyword("***") == ""

    def test_empty_input(self) -> None:
        assert sanitize_grep_keyword("") == ""

    def test_unicode_preserved(self) -> None:
        assert sanitize_grep_keyword("cafe\u0301") == "caf\u00e9" or sanitize_grep_keyword("cafe\u0301") == "cafe\u0301"


class TestNormalizeKeywords:
    def test_basic_normalization(self) -> None:
        result = normalize_keywords(["Python", "  rust  ", "Go"])
        assert result == ["python", "rust", "go"]

    def test_deduplicates(self) -> None:
        result = normalize_keywords(["python", "Python", "PYTHON"])
        assert result == ["python"]

    def test_filters_empty(self) -> None:
        result = normalize_keywords(["", "  ", "python", "***"])
        assert result == ["python"]

    def test_respects_max(self) -> None:
        many = [f"keyword{i}" for i in range(30)]
        result = normalize_keywords(many, max_keywords=5)
        assert len(result) == 5

    def test_empty_list(self) -> None:
        assert normalize_keywords([]) == []

    def test_all_empty_keywords(self) -> None:
        assert normalize_keywords(["", "  ", "***"]) == []


class TestBuildFtsOrQuery:
    def test_single_keyword(self) -> None:
        assert build_fts_or_query(["python"]) == '"python"'

    def test_multiple_keywords(self) -> None:
        result = build_fts_or_query(["python", "rust", "go"])
        assert result == '"python" OR "rust" OR "go"'

    def test_phrase_keyword(self) -> None:
        result = build_fts_or_query(["machine learning"])
        assert result == '"machine learning"'

    def test_empty_list(self) -> None:
        assert build_fts_or_query([]) == ""

    def test_filters_empty_strings(self) -> None:
        assert build_fts_or_query(["", "python", ""]) == '"python"'


class TestExtractMatchedKeywords:
    def test_finds_present_keywords(self) -> None:
        content = "Python is great for machine learning"
        result = extract_matched_keywords(content, ["python", "machine"])
        assert result == ["python", "machine"]

    def test_case_insensitive(self) -> None:
        content = "PYTHON and Rust"
        result = extract_matched_keywords(content, ["python", "rust"])
        assert result == ["python", "rust"]

    def test_no_matches(self) -> None:
        content = "Hello world"
        result = extract_matched_keywords(content, ["python", "rust"])
        assert result == []

    def test_partial_match(self) -> None:
        content = "Python is powerful"
        result = extract_matched_keywords(content, ["python", "rust"])
        assert result == ["python"]

    def test_empty_content(self) -> None:
        result = extract_matched_keywords("", ["python"])
        assert result == []


class TestComputeProximity:
    def test_single_keyword_returns_1(self) -> None:
        assert compute_proximity("Python is great", ["python"]) == 1.0

    def test_zero_keywords_returns_1(self) -> None:
        assert compute_proximity("Python is great", []) == 1.0

    def test_adjacent_keywords_high_score(self) -> None:
        content = "machine learning is powerful"
        score = compute_proximity(content, ["machine", "learning"])
        assert score > 0.5

    def test_distant_keywords_lower_score(self) -> None:
        content = "machine " + "x " * 500 + "learning"
        score = compute_proximity(content, ["machine", "learning"])
        # Distant keywords should score lower than adjacent ones
        adjacent_score = compute_proximity("machine learning is great", ["machine", "learning"])
        assert score < adjacent_score

    def test_three_keywords_clustered(self) -> None:
        content = "python machine learning rocks"
        score = compute_proximity(content, ["python", "machine", "learning"])
        assert score > 0.5

    def test_empty_content(self) -> None:
        assert compute_proximity("", ["python"]) == 1.0


class TestGenerateSnippet:
    def test_basic_highlight(self) -> None:
        content = "Python is a programming language for data science"
        snippet = generate_snippet(content, ["python"])
        assert "**Python**" in snippet

    def test_multiple_keywords_highlighted(self) -> None:
        content = "Python and Rust are programming languages"
        snippet = generate_snippet(content, ["python", "rust"])
        assert "**Python**" in snippet
        assert "**Rust**" in snippet

    def test_case_insensitive_highlight(self) -> None:
        content = "PYTHON is great"
        snippet = generate_snippet(content, ["python"])
        assert "**PYTHON**" in snippet

    def test_ellipsis_when_truncated(self) -> None:
        content = "x " * 500 + "Python is here" + " y" * 500
        snippet = generate_snippet(content, ["python"], context_chars=20)
        assert snippet.startswith("...")
        assert snippet.endswith("...")

    def test_no_match_returns_empty(self) -> None:
        assert generate_snippet("Hello world", ["python"]) == ""

    def test_empty_content_returns_empty(self) -> None:
        assert generate_snippet("", ["python"]) == ""

    def test_empty_keywords_returns_empty(self) -> None:
        assert generate_snippet("Python is great", []) == ""

    def test_custom_markers(self) -> None:
        content = "Python is great"
        snippet = generate_snippet(content, ["python"], marker_start="<b>", marker_end="</b>")
        assert "<b>Python</b>" in snippet

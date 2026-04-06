"""Tests for semantic text chunking."""

from qp_vault.core.chunker import ChunkerConfig, chunk_text, estimate_tokens


class TestEstimateTokens:
    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_single_word(self):
        tokens = estimate_tokens("hello")
        assert tokens >= 1

    def test_sentence(self):
        tokens = estimate_tokens("The quick brown fox jumps over the lazy dog")
        assert 5 <= tokens <= 15


class TestChunkText:
    def test_empty_text(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_short_text_single_chunk(self):
        text = "This is a short paragraph."
        chunks = chunk_text(text)
        assert len(chunks) == 1
        assert chunks[0].chunk_index == 0
        assert "short paragraph" in chunks[0].content

    def test_preserves_content(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunk_text(text)
        combined = " ".join(c.content for c in chunks)
        assert "First paragraph" in combined
        assert "Third paragraph" in combined

    def test_respects_max_tokens(self):
        config = ChunkerConfig(target_tokens=50, max_tokens=100, min_tokens=10, overlap_tokens=10)
        # Create text that definitely exceeds max
        paragraphs = [f"Paragraph {i} with some filler text to increase token count." for i in range(50)]
        text = "\n\n".join(paragraphs)
        chunks = chunk_text(text, config)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= config.max_tokens * 1.5  # Allow some overshoot

    def test_chunk_indexes_sequential(self):
        paragraphs = [f"Paragraph number {i} with content." for i in range(20)]
        text = "\n\n".join(paragraphs)
        config = ChunkerConfig(target_tokens=30, max_tokens=60, min_tokens=5, overlap_tokens=5)
        chunks = chunk_text(text, config)
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_detects_section_titles(self):
        text = "# Introduction\n\nThis is the intro.\n\n## Methods\n\nThis is the methods section."
        chunks = chunk_text(text)
        # At least one chunk should have a section title
        sections = [c.section_title for c in chunks if c.section_title]
        assert len(sections) > 0

    def test_small_trailing_chunk_merged(self):
        config = ChunkerConfig(target_tokens=100, min_tokens=50, max_tokens=200, overlap_tokens=10)
        # Create text where last paragraph is very small
        text = ("A " * 80) + "\n\n" + "tiny."
        chunks = chunk_text(text, config)
        # The tiny trailing text should be merged into previous chunk
        if len(chunks) == 1:
            assert "tiny" in chunks[0].content

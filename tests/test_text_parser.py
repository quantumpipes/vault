"""Tests for the built-in text parser."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault.exceptions import ParsingError
from qp_vault.processing.text_parser import TextParser

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def parser():
    return TextParser()


class TestTextParser:
    def test_supported_extensions(self, parser):
        exts = parser.supported_extensions
        assert ".md" in exts
        assert ".py" in exts
        assert ".txt" in exts
        assert ".json" in exts
        assert ".rs" in exts

    @pytest.mark.asyncio
    async def test_parse_markdown(self, parser, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("# Hello\n\nWorld")
        result = await parser.parse(f)
        assert "# Hello" in result.text
        assert result.metadata["format"] == "md"

    @pytest.mark.asyncio
    async def test_parse_python(self, parser, tmp_path: Path):
        f = tmp_path / "test.py"
        f.write_text("def hello():\n    return 'world'")
        result = await parser.parse(f)
        assert "def hello" in result.text

    @pytest.mark.asyncio
    async def test_parse_utf8(self, parser, tmp_path: Path):
        f = tmp_path / "unicode.txt"
        f.write_text("Hello \u00e9\u00e8\u00ea \u4e16\u754c")
        result = await parser.parse(f)
        assert "\u00e9" in result.text

    @pytest.mark.asyncio
    async def test_parse_latin1_fallback(self, parser, tmp_path: Path):
        f = tmp_path / "latin.txt"
        f.write_bytes(b"caf\xe9")  # Latin-1 encoded
        result = await parser.parse(f)
        assert "caf" in result.text

    @pytest.mark.asyncio
    async def test_parse_nonexistent_raises(self, parser, tmp_path: Path):
        f = tmp_path / "nonexistent.txt"
        with pytest.raises(ParsingError, match="Failed to read"):
            await parser.parse(f)

    @pytest.mark.asyncio
    async def test_parse_empty_file(self, parser, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = await parser.parse(f)
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_metadata_includes_source(self, parser, tmp_path: Path):
        f = tmp_path / "meta.json"
        f.write_text('{"key": "value"}')
        result = await parser.parse(f)
        assert result.metadata["source_path"] == str(f)
        assert result.metadata["format"] == "json"

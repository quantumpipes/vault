"""Tests for WebVTT and SRT transcript parsers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from qp_vault.processing.transcript_parser import SRTParser, WebVTTParser

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def vtt_file(tmp_path: Path) -> Path:
    """Standard WebVTT file with speaker labels."""
    content = """WEBVTT

1
00:00:01.000 --> 00:00:04.000
Alice: Welcome to the meeting everyone.

2
00:00:04.500 --> 00:00:08.000
Bob: Thanks Alice. Let's discuss the Q3 roadmap.

3
00:00:08.500 --> 00:00:12.000
Alice: First item is the vault extraction project.

4
00:00:12.500 --> 00:00:16.000
Charlie: I have concerns about the timeline.
"""
    p = tmp_path / "meeting.vtt"
    p.write_text(content)
    return p


@pytest.fixture
def zoom_vtt_file(tmp_path: Path) -> Path:
    """Zoom-style WebVTT with <v> tags."""
    content = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Alice>Welcome to the meeting everyone.</v>

00:00:04.500 --> 00:00:08.000
<v Bob>Thanks Alice. Let's discuss the roadmap.</v>
"""
    p = tmp_path / "zoom.vtt"
    p.write_text(content)
    return p


@pytest.fixture
def srt_file(tmp_path: Path) -> Path:
    """Standard SRT file."""
    content = """1
00:00:01,000 --> 00:00:04,000
Welcome to the presentation.

2
00:00:04,500 --> 00:00:08,000
Today we'll cover three topics.

3
00:00:08,500 --> 00:00:12,000
Speaker A: The first topic is security.
"""
    p = tmp_path / "subtitles.srt"
    p.write_text(content)
    return p


class TestWebVTTParser:
    @pytest.mark.asyncio
    async def test_parse_basic(self, vtt_file: Path):
        parser = WebVTTParser()
        result = await parser.parse(vtt_file)
        assert "Welcome to the meeting" in result.text
        assert "Q3 roadmap" in result.text
        assert result.metadata["format"] == "webvtt"

    @pytest.mark.asyncio
    async def test_detects_speakers(self, vtt_file: Path):
        parser = WebVTTParser()
        result = await parser.parse(vtt_file)
        assert "Alice" in result.metadata["speakers"]
        assert "Bob" in result.metadata["speakers"]
        assert "Charlie" in result.metadata["speakers"]
        assert result.metadata["speaker_count"] == 3

    @pytest.mark.asyncio
    async def test_speaker_labels_in_text(self, vtt_file: Path):
        parser = WebVTTParser()
        result = await parser.parse(vtt_file)
        assert "[Alice]" in result.text
        assert "[Bob]" in result.text

    @pytest.mark.asyncio
    async def test_zoom_v_tags(self, zoom_vtt_file: Path):
        parser = WebVTTParser()
        result = await parser.parse(zoom_vtt_file)
        assert "[Alice]" in result.text
        assert "[Bob]" in result.text
        assert result.metadata["speaker_count"] == 2

    def test_supported_extensions(self):
        parser = WebVTTParser()
        assert ".vtt" in parser.supported_extensions
        assert ".webvtt" in parser.supported_extensions


class TestSRTParser:
    @pytest.mark.asyncio
    async def test_parse_basic(self, srt_file: Path):
        parser = SRTParser()
        result = await parser.parse(srt_file)
        assert "Welcome to the presentation" in result.text
        assert "three topics" in result.text
        assert result.metadata["format"] == "srt"

    @pytest.mark.asyncio
    async def test_detects_speakers(self, srt_file: Path):
        parser = SRTParser()
        result = await parser.parse(srt_file)
        assert "Speaker A" in result.metadata["speakers"]
        assert "[Speaker A]" in result.text

    @pytest.mark.asyncio
    async def test_segment_count(self, srt_file: Path):
        parser = SRTParser()
        result = await parser.parse(srt_file)
        assert result.metadata["segment_count"] == 3

    def test_supported_extensions(self):
        parser = SRTParser()
        assert ".srt" in parser.supported_extensions

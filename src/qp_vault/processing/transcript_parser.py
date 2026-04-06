"""WebVTT and SRT transcript parsers with speaker attribution.

Parses subtitle/transcript files into text with speaker labels.
Pure Python, zero external dependencies.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from qp_vault.protocols import ParseResult

if TYPE_CHECKING:
    from pathlib import Path


class WebVTTParser:
    """Parse WebVTT (.vtt) transcript files.

    Extracts text content with speaker attribution from WEBVTT format.
    Handles both standard VTT and Zoom-style VTT with speaker labels.
    """

    @property
    def supported_extensions(self) -> set[str]:
        return {".vtt", ".webvtt"}

    async def parse(self, path: Path) -> ParseResult:
        """Parse a WebVTT file into text with speaker labels."""
        content = path.read_text(encoding="utf-8")
        lines = content.split("\n")

        segments: list[str] = []
        current_speaker: str | None = None
        speakers: set[str] = set()

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Skip WEBVTT header and metadata
            if line.startswith("WEBVTT") or line.startswith("NOTE") or not line:
                i += 1
                continue

            # Skip cue identifiers (numeric or named)
            if re.match(r"^\d+$", line):
                i += 1
                continue

            # Skip timestamp lines
            if "-->" in line:
                i += 1
                continue

            # Check for speaker label patterns:
            # "Speaker Name: text" or "<v Speaker Name>text</v>"
            speaker_match = re.match(r"^<v\s+([^>]+)>(.*)$", line)
            if speaker_match:
                speaker = speaker_match.group(1).strip()
                text = re.sub(r"</v>", "", speaker_match.group(2)).strip()
                if speaker != current_speaker:
                    current_speaker = speaker
                    speakers.add(speaker)
                if text:
                    segments.append(f"[{speaker}] {text}")
                i += 1
                continue

            colon_match = re.match(r"^([^:]{1,50}):\s*(.+)$", line)
            if colon_match and not re.match(r"^\d{2}:", line):
                speaker = colon_match.group(1).strip()
                text = colon_match.group(2).strip()
                if speaker != current_speaker:
                    current_speaker = speaker
                    speakers.add(speaker)
                segments.append(f"[{speaker}] {text}")
                i += 1
                continue

            # Plain text line
            if line:
                if current_speaker:
                    segments.append(f"[{current_speaker}] {line}")
                else:
                    segments.append(line)

            i += 1

        full_text = "\n".join(segments)

        return ParseResult(
            text=full_text,
            metadata={
                "format": "webvtt",
                "speakers": sorted(speakers),
                "speaker_count": len(speakers),
                "segment_count": len(segments),
            },
            pages=0,
        )


class SRTParser:
    """Parse SRT (.srt) subtitle files.

    Extracts text content from SubRip format. Speaker attribution
    is detected from common patterns like "Speaker: text".
    """

    @property
    def supported_extensions(self) -> set[str]:
        return {".srt"}

    async def parse(self, path: Path) -> ParseResult:
        """Parse an SRT file into plain text."""
        content = path.read_text(encoding="utf-8")

        # Remove BOM if present
        if content.startswith("\ufeff"):
            content = content[1:]

        segments: list[str] = []
        speakers: set[str] = set()

        # Split into subtitle blocks (separated by blank lines)
        blocks = re.split(r"\n\s*\n", content.strip())

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue

            # Skip index (first line) and timestamp (second line)
            text_lines = []
            for line in lines[2:]:
                # Strip HTML-style tags
                cleaned = re.sub(r"<[^>]+>", "", line).strip()
                if cleaned:
                    text_lines.append(cleaned)

            text = " ".join(text_lines)
            if not text:
                continue

            # Check for speaker label
            colon_match = re.match(r"^([^:]{1,50}):\s*(.+)$", text)
            if colon_match and not re.match(r"^\d{2}:", text):
                speaker = colon_match.group(1).strip()
                speakers.add(speaker)
                segments.append(f"[{speaker}] {colon_match.group(2).strip()}")
            else:
                segments.append(text)

        full_text = "\n".join(segments)

        return ParseResult(
            text=full_text,
            metadata={
                "format": "srt",
                "speakers": sorted(speakers),
                "speaker_count": len(speakers),
                "segment_count": len(segments),
            },
            pages=0,
        )

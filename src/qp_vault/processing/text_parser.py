"""Built-in text parser for common text formats.

Handles .txt, .md, .rst, .json, .yaml, .yml, .csv, .xml, .html, .htm
with zero external dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp_vault.exceptions import ParsingError
from qp_vault.protocols import ParseResult

if TYPE_CHECKING:
    from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".rst", ".json", ".yaml", ".yml",
    ".csv", ".xml", ".html", ".htm", ".log", ".ini",
    ".toml", ".cfg", ".conf", ".env", ".sh", ".bash",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go",
    ".java", ".c", ".cpp", ".h", ".hpp", ".rb", ".php",
    ".sql", ".r", ".swift", ".kt", ".scala", ".lua",
}


class TextParser:
    """Parses text-based files by reading their content directly.

    No external dependencies. Handles any file that can be read as UTF-8.
    """

    @property
    def supported_extensions(self) -> set[str]:
        return SUPPORTED_EXTENSIONS

    async def parse(self, path: Path) -> ParseResult:
        """Read a text file and return its content.

        Raises:
            ParsingError: If the file cannot be read.
        """
        try:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="latin-1")
        except OSError as e:
            raise ParsingError(f"Failed to read {path.name}: {e}") from e

        return ParseResult(
            text=text,
            metadata={"source_path": str(path), "format": path.suffix.lstrip(".")},
            pages=0,
        )

# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Docling document parser: 25+ format processing.

Converts PDF, DOCX, PPTX, XLSX, HTML, images, and more to text
using IBM's Docling library.

Requires: pip install qp-vault[docling]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp_vault.protocols import ParseResult

if TYPE_CHECKING:
    from pathlib import Path

try:
    from docling.document_converter import DocumentConverter
    HAS_DOCLING = True
except ImportError:
    HAS_DOCLING = False

DOCLING_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".html", ".htm", ".xml", ".csv", ".tsv",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp",
    ".md", ".rst", ".rtf", ".odt", ".ods", ".odp",
    ".epub", ".mobi",
}


class DoclingParser:
    """Parse 25+ document formats using Docling.

    Docling handles complex layouts (multi-column PDF, tables, figures)
    and extracts text with structural awareness.

    Requires: pip install qp-vault[docling]
    """

    def __init__(self) -> None:
        if not HAS_DOCLING:
            raise ImportError(
                "docling is required for DoclingParser. "
                "Install with: pip install qp-vault[docling]"
            )
        self._converter = DocumentConverter()

    @property
    def supported_extensions(self) -> set[str]:
        return DOCLING_EXTENSIONS

    async def parse(self, path: Path) -> ParseResult:
        """Parse a document file and extract text content.

        Args:
            path: Path to the document file.

        Returns:
            ParseResult with extracted text and metadata.
        """
        result = self._converter.convert(str(path))
        text = result.document.export_to_markdown()

        return ParseResult(
            text=text,
            metadata={
                "source_path": str(path),
                "format": path.suffix.lstrip("."),
                "parser": "docling",
            },
            pages=0,
        )

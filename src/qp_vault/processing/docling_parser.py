# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Docling document parser: the ONE document-extraction seam in this estate.

Every space that reads a primary document (verisgov, hcbs-ai, waaban, hyperlocal-hub,
greaternorthwoods) goes through this class. Do not construct a `DocumentConverter`
anywhere else. A declared seam with no injector becomes a reimplementation, and this
one was reimplemented three times before 2026-08-16.

Two things changed that day and both are load-bearing:

**The extension set is derived, not written.** It comes from the installed docling's
own `FormatToExtensions`, minus the formats another vault parser owns better. The
previous hand-written set claimed `.rtf`, `.epub`, `.mobi`, `.odt` and the legacy
Office trio, none of which docling reads, so a matching file routed here and crashed.
See `document_intelligence._CEDED` for what is deliberately given away and why.

**Absence is a capability answer, not an ImportError.** `capability()` reports whether
the Document Intelligence pack is installed and its models staged. Ask before you
parse. `DoclingParser()` raises `DocumentIntelligenceUnavailable`, whose message is
written for a person, only if you skipped that check.

Formats docling cannot read route to an alternate parser where one exists
(`ALTERNATE_PARSERS`), and to a named refusal where none does. A file type is never
silently dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qp_vault.processing.document_intelligence import (
    DocumentIntelligenceUnavailable,
    capability,
)
from qp_vault.protocols import ParseResult

if TYPE_CHECKING:
    from pathlib import Path

#: Formats this estate must read that docling does not support. Each entry names the
#: module that does. Keep the reason with the mapping: the RTF entry exists because
#: Utah publishes its administrative code as RTF and R539-3 (Rights and Protections)
#: and R539-4 (Behavior Interventions) are load-bearing for the HCBS corpus.
ALTERNATE_PARSERS: dict[str, str] = {
    ".rtf": "qp_vault.processing.rtf_parser:RtfParser",
}

#: Back-compatible alias. Prefer `capability().available`, which also tells you WHY.
HAS_DOCLING: bool = capability().available


def supported_extensions() -> frozenset[str]:
    """What the INSTALLED docling reads, right now. Cheap; safe to call repeatedly."""
    return capability().extensions


def new_converter(**pdf_options: Any) -> Any:
    """Build a FRESH configured `DocumentConverter`, with caller PDF pipeline options.

    For callers that genuinely cannot share one instance. `DocumentConverter` is not
    proven thread-safe, so a concurrent sweep runs a small pool of instances rather
    than serialising on a global lock; hyperlocal-hub measured that difference as
    roughly ten hours on a 3,700-document run.

    Whatever you pass is applied ON TOP of the air-gap configuration, never instead of
    it: `artifacts_path` is pinned to the staged models and `enable_remote_services` is
    forced False after your options are applied, so neither can be overridden by
    accident. Pass what your pipeline actually needs (`do_ocr=False` for deterministic
    text-layer extraction, for instance) and let this own the rest.

    Raises:
        DocumentIntelligenceUnavailable: the pack is not installed.
    """
    cap = capability()
    if not cap.available:
        raise DocumentIntelligenceUnavailable(cap)

    from docling.document_converter import DocumentConverter

    if not pdf_options and cap.artifacts is None:
        return DocumentConverter()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import PdfFormatOption

    opts = PdfPipelineOptions(**pdf_options)
    if cap.artifacts is not None:
        opts.artifacts_path = str(cap.artifacts)
    opts.enable_remote_services = False
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


class DoclingParser:
    """Parse documents using docling, with structural awareness.

    Handles multi-column PDF, tables and figures rather than flattening them, which is
    the reason this estate forbids a `pdftotext` fallback for anything it will later
    quote: a fallback that silently produces worse text is indistinguishable from one
    that produced good text.
    """

    def __init__(self) -> None:
        cap = capability()
        if not cap.available:
            raise DocumentIntelligenceUnavailable(cap)
        self._capability = cap
        self._converter: Any | None = None

    @property
    def capability(self):  # noqa: ANN201 - dataclass, typed at the call site
        """The capability record this parser was built against."""
        return self._capability

    @property
    def supported_extensions(self) -> set[str]:
        return set(self._capability.extensions)

    def _build_converter(self) -> Any:
        """Construct the converter once, pinned to staged artifacts when we have them.

        Deferred rather than built in `__init__` because loading the layout model costs
        seconds and a caller that only asks `supported_extensions` should pay nothing.
        """
        from docling.document_converter import DocumentConverter

        arts = self._capability.artifacts
        if arts is None:
            return DocumentConverter()

        # Pin every PDF pipeline to the staged artifacts so no format option can
        # quietly resolve a remote repo.
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        opts = PdfPipelineOptions(artifacts_path=str(arts))
        opts.enable_remote_services = False
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )

    def converter(self) -> Any:
        """The configured `DocumentConverter`, for callers that need the document object.

        Text is not always the deliverable. A sealing pass needs page count, table count
        and heading labels off `result.document` to make its structural claim, and
        `ParseResult` deliberately does not carry those.

        This is an escape hatch, not a licence to build your own: the invariant this
        module enforces is that ONE place CONFIGURES docling, pinning staged artifacts
        and refusing remote services. Construct your own `DocumentConverter` and you get
        neither, which is how a supposedly air-gapped host reaches HuggingFace on its
        first PDF. Take the converter from here and the configuration comes with it.
        """
        if self._converter is None:
            self._converter = self._build_converter()
        return self._converter

    async def parse(self, path: Path) -> ParseResult:
        """Extract a document to markdown.

        Args:
            path: Path to the document file.

        Returns:
            ParseResult with markdown text and provenance metadata. The metadata names
            the parser and the docling version, because a seal that cannot say which
            extractor produced its text cannot be re-verified later.

        Raises:
            DocumentIntelligenceUnavailable: the pack is not installed.
            ValueError: docling does not read this extension. The message names the
                alternate parser when one exists, so the caller is never told only
                that something failed.
        """
        suffix = path.suffix.lower()
        if suffix not in self._capability.extensions:
            alt = ALTERNATE_PARSERS.get(suffix)
            hint = (
                f" Use {alt} for this format."
                if alt
                else " No parser in this estate reads it."
            )
            raise ValueError(
                f"docling {self._capability.version} does not read {suffix!r}.{hint}"
            )

        if self._converter is None:
            self._converter = self._build_converter()

        result = self._converter.convert(str(path))
        text = result.document.export_to_markdown()

        return ParseResult(
            text=text,
            metadata={
                "source_path": str(path),
                "format": suffix.lstrip("."),
                "parser": "docling",
                "parser_version": self._capability.version,
                "artifacts_staged": self._capability.artifacts is not None,
                "offline_enforced": self._capability.offline_enforced,
            },
            pages=len(getattr(result.document, "pages", ()) or ()),
        )

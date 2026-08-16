# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""RTF parser: the alternate for the one format docling does not read.

Docling's `InputFormat` set has no RTF member, so RTF is not a docling failure, it is
outside docling's claim. That distinction matters here: the estate's "docling, never
pdftotext" rule exists to protect PDF *fidelity*, because a flattened multi-column PDF
looks like successful extraction and is not. RTF carries no layout to lose. It is a
tagged text format, and decoding it is deterministic.

Why this exists at all: Utah publishes its administrative code as RTF, and the HCBS
corpus rests on R539-3 (Rights and Protections) and R539-4 (Behavior Interventions),
which the RHE compliance director names as the only two R539 rules her network uses.
Without this parser those two rules cannot enter the corpus at all.

No third-party dependency. RTF's grammar is small and the alternative is adding a
package to the offline bundle for something this size.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING

from qp_vault.protocols import ParseResult

if TYPE_CHECKING:
    from pathlib import Path

RTF_EXTENSIONS = frozenset({".rtf"})

#: Destinations whose CONTENT is metadata, not document text. Skipping them is the
#: difference between the rule's words and the rule's words preceded by a font table.
_SKIP_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "listtable", "listoverridetable",
    "info", "pict", "object", "themedata", "colorschememapping", "datastore",
    "latentstyles", "rsidtbl", "generator", "xmlnstbl", "filetbl", "revtbl",
    "mmathPr", "wgrffmtfilter", "listtext", "pntext", "header", "footer",
    "headerl", "headerr", "headerf", "footerl", "footerr", "footerf",
    "footnote", "annotation", "bkmkstart", "bkmkend", "shppict", "nonshppict",
})

#: Control words that emit a character rather than set state.
_EMIT = {
    "par": "\n", "line": "\n", "sect": "\n\n", "page": "\n\n",
    "tab": "\t", "cell": "\t", "row": "\n", "nestcell": "\t", "nestrow": "\n",
    "emdash": "\u2014", "endash": "\u2013", "lquote": "\u2018", "rquote": "\u2019",
    "ldblquote": "\u201c", "rdblquote": "\u201d", "bullet": "\u2022",
    "enspace": " ", "emspace": " ", "~": "\u00a0", "-": "", "_": "\u2011",
}

_TOKEN = re.compile(
    r"\\([a-zA-Z]{1,32})(-?\d{1,10})?[ ]?"   # control word, optional numeric arg
    r"|\\'([0-9a-fA-F]{2})"                   # hex-escaped byte
    r"|\\([\\{}*])"                           # escaped literal, or the \* ignorable mark
    r"|([{}])"                                # group open/close
    r"|([^\\{}]+)"                            # plain run
)


def rtf_to_text(data: str) -> str:
    """Decode RTF to plain text.

    Handles groups, ignorable destinations (`\\*\\foo`), `\\uN` Unicode with its
    replacement-character skip count, `\\'hh` hex bytes, and the emitting control
    words. Unknown control words set state we do not model and are dropped, which is
    correct: RTF requires a reader to ignore what it does not understand.
    """
    out: list[str] = []
    depth = 0
    # Per-group state: how many literal chars to swallow after a \uN, and whether the
    # whole group is a destination we are skipping.
    skip_chars = 0
    skip_until_depth: int | None = None
    # `\*` marks the NEXT control word as an ignorable destination. Without this the
    # group's raw payload leaks into the text as punctuation soup: the Utah R539 files
    # emitted a literal `*0c0070686f656e697800010000` from one such destination.
    pending_ignorable = False

    for m in _TOKEN.finditer(data):
        word, arg, hexb, literal, brace, text = m.groups()

        if brace == "{":
            depth += 1
            continue
        if brace == "}":
            depth -= 1
            pending_ignorable = False
            if skip_until_depth is not None and depth < skip_until_depth:
                skip_until_depth = None
            continue

        if skip_until_depth is not None:
            continue

        if literal == "*":
            pending_ignorable = True
            continue

        if word is not None:
            if pending_ignorable:
                # Whatever destination this is, we do not model it. Drop the group.
                pending_ignorable = False
                skip_until_depth = depth
                continue
            if word == "u":
                # \uN emits one Unicode char, then N replacement chars must be eaten.
                if arg is not None:
                    code = int(arg)
                    if code < 0:
                        code += 0x10000
                    out.append(chr(code))
                skip_chars = 1
                continue
            if word == "uc":
                skip_chars = 0
                continue
            if word in _SKIP_DESTINATIONS:
                skip_until_depth = depth
                continue
            if word in _EMIT:
                out.append(_EMIT[word])
                continue
            continue

        if literal is not None:
            out.append(literal)
            continue

        if hexb is not None:
            if skip_chars > 0:
                skip_chars -= 1
                continue
            with contextlib.suppress(ValueError, UnicodeDecodeError):
                out.append(bytes([int(hexb, 16)]).decode("cp1252"))
            continue

        if text is not None:
            if skip_chars > 0:
                eat = min(skip_chars, len(text))
                skip_chars -= eat
                text = text[eat:]
            if text:
                out.append(text)

    joined = "".join(out)
    # RTF line-wraps its source; collapse the runs of blank lines that produces without
    # destroying paragraph structure, which the rule numbering depends on.
    joined = re.sub(r"[ \t]+\n", "\n", joined)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


class RtfParser:
    """Parse RTF documents to text. Deterministic, offline, no models."""

    @property
    def supported_extensions(self) -> set[str]:
        return set(RTF_EXTENSIONS)

    async def parse(self, path: Path) -> ParseResult:
        """Extract an RTF file to text.

        Args:
            path: Path to the .rtf file.

        Returns:
            ParseResult with decoded text and provenance naming this parser, so a
            later seal can tell docling-extracted text from RTF-decoded text.

        Raises:
            ValueError: the file is not RTF.
        """
        raw = path.read_bytes()
        if not raw.lstrip()[:5].startswith(b"{\\rtf"):
            raise ValueError(
                f"{path.name} does not begin with an RTF header; refusing to guess "
                f"at its encoding."
            )
        text = rtf_to_text(raw.decode("cp1252", errors="replace"))
        return ParseResult(
            text=text,
            metadata={
                "source_path": str(path),
                "format": "rtf",
                "parser": "rtf",
                "parser_version": "qp-vault builtin",
            },
            pages=0,
        )

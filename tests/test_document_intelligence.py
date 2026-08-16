# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Tests for the Document Intelligence capability and the RTF alternate.

Each test names the defect it prevents. The three that matter most are the vacuity
tests: a capability probe that reports available while nothing works, an allowlist
that claims a format the engine cannot read, and an air-gap guard set after the
library it is meant to constrain has already loaded.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from qp_vault.processing import document_intelligence as di
from qp_vault.processing.docling_parser import (
    ALTERNATE_PARSERS,
    DoclingParser,
    supported_extensions,
)
from qp_vault.processing.document_intelligence import (
    DocumentIntelligence,
    DocumentIntelligenceUnavailable,
    capability,
)
from qp_vault.processing.rtf_parser import RtfParser, rtf_to_text

MINIMAL_RTF = rb"{\rtf1\ansi\deff0{\fonttbl{\f0 Times;}}\f0 Hello world.\par Second line.}"


# ----------------------------------------------------------- the allowlist ----


def test_allowlist_is_derived_not_declared():
    """The 2026-08-16 defect: a hand-written set claimed 28 extensions, docling read 18.

    A file matching the claim routed to docling and crashed. The set must come from
    the installed library so it cannot outrun it again.
    """
    cap = capability()
    if not cap.available:
        pytest.skip("Document Intelligence pack not installed")

    from docling.datamodel.base_models import FormatToExtensions

    real = {f".{e.lower()}" for exts in FormatToExtensions.values() for e in exts}
    assert cap.extensions <= real, (
        f"claimed but unreadable: {sorted(cap.extensions - real)}"
    )


def test_formats_docling_cannot_read_are_not_claimed():
    """RTF, EPUB and the legacy Office trio were all claimed and none is supported."""
    cap = capability()
    if not cap.available:
        pytest.skip("Document Intelligence pack not installed")
    for ext in (".rtf", ".epub", ".mobi", ".odt", ".ods", ".odp", ".doc", ".ppt", ".xls"):
        assert ext not in cap.extensions, f"{ext} is claimed and docling cannot read it"


def test_ceded_formats_are_absent_and_documented():
    """A silent subtraction is indistinguishable from a bug, so each has a reason."""
    cap = capability()
    if not cap.available:
        pytest.skip("Document Intelligence pack not installed")
    for ext in (".txt", ".md", ".vtt", ".mp3"):
        assert ext not in cap.extensions
        assert di._CEDED[ext], f"{ext} ceded with no reason recorded"


def test_rtf_has_a_named_alternate_rather_than_silent_absence():
    """Dropping RTF would make R539-3 and R539-4 unreadable, and say nothing."""
    assert ".rtf" in ALTERNATE_PARSERS
    assert "RtfParser" in ALTERNATE_PARSERS[".rtf"]


# -------------------------------------------------------------- the air gap ----


def test_offline_is_forced_at_import():
    """Set after docling loads, these are a no-op: a guard that reads present and isn't.

    Import order is the enforcement, so assert the module did it, not that it could.
    """
    import os

    if os.environ.get(di.ALLOW_NETWORK_ENV, "").strip() in {"1", "true", "yes"}:
        pytest.skip("network explicitly allowed in this environment")
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"


def test_capability_reports_offline_enforcement():
    assert isinstance(capability().offline_enforced, bool)


def test_artifacts_path_honours_doclings_own_variable(tmp_path, monkeypatch):
    """A deployment staged the documented docling way must not read as unstaged.

    RHTP's Dockerfile runs `docling-tools models download -o $DOCLING_ARTIFACTS_PATH`,
    which works because docling's settings declare `env_prefix="DOCLING_"` over a field
    named `artifacts_path`. The first version of this module read only
    QP_DOCLING_ARTIFACTS and would have called that correctly-staged image unavailable.
    """
    monkeypatch.delenv(di.ARTIFACTS_ENV, raising=False)
    monkeypatch.setenv(di.DOCLING_ARTIFACTS_ENV, str(tmp_path))
    assert di.artifacts_path() == tmp_path


def test_pack_variable_wins_over_doclings(tmp_path, monkeypatch):
    pack = tmp_path / "pack"
    other = tmp_path / "other"
    pack.mkdir()
    other.mkdir()
    monkeypatch.setenv(di.ARTIFACTS_ENV, str(pack))
    monkeypatch.setenv(di.DOCLING_ARTIFACTS_ENV, str(other))
    assert di.artifacts_path() == pack


def test_a_configured_but_missing_artifacts_dir_is_not_accepted(monkeypatch):
    """A path that does not exist is not staging; treating it as such hides the gap."""
    monkeypatch.setenv(di.ARTIFACTS_ENV, "/nonexistent/models")
    monkeypatch.delenv(di.DOCLING_ARTIFACTS_ENV, raising=False)
    assert di.artifacts_path() is None


def test_unavailable_capability_always_explains_itself():
    """'PDF extraction unavailable' with no cause is the failure this module exists for."""
    cap = capability()
    if cap.available:
        cap = DocumentIntelligence(available=False, reason="docling is not importable.")
    assert cap.reason.strip(), "an unavailable capability with no reason is unactionable"
    assert cap.needs_pack


def test_refusal_names_the_file_and_stays_a_sentence():
    cap = DocumentIntelligence(available=False, reason="docling is not importable.")
    msg = cap.refusal(Path("/tmp/rules.pdf"))
    assert "rules.pdf" in msg
    assert "Document Intelligence" in msg


def test_unavailable_pack_raises_a_written_error_not_an_importerror():
    cap = DocumentIntelligence(available=False, reason="docling is not importable.")
    err = DocumentIntelligenceUnavailable(cap, Path("/tmp/x.pdf"))
    assert "x.pdf" in str(err)
    assert err.capability is cap


# ------------------------------------------------------------ the RTF path ----


def test_rtf_extracts_text():
    result = asyncio.run(_parse_rtf(MINIMAL_RTF))
    assert "Hello world." in result.text
    assert "Second line." in result.text


def test_rtf_drops_the_font_table():
    """Metadata destinations are not document text."""
    assert "Times" not in asyncio.run(_parse_rtf(MINIMAL_RTF)).text


def test_rtf_drops_ignorable_destinations():
    r"""The `\*` mark. Utah's R539 files leaked `*0c0070686f...` without this."""
    src = rb"{\rtf1\ansi{\*\privatedata 0c0070686f656e69}Real text.}"
    text = asyncio.run(_parse_rtf(src)).text
    assert "Real text." in text
    assert "0c0070686f" not in text
    assert "*" not in text


def test_rtf_decodes_unicode_escapes_and_eats_the_replacement():
    src = rb"{\rtf1\ansi Se\u241 ?or and \'e9clair.}"
    text = asyncio.run(_parse_rtf(src)).text
    assert "Señor" in text, text
    assert "?" not in text
    assert "éclair" in text


def test_rtf_refuses_a_non_rtf_file_instead_of_guessing():
    """An extractor that guesses at an encoding produces plausible wrong text."""
    with pytest.raises(ValueError, match="RTF header"):
        asyncio.run(_parse_rtf(b"This is plain text, not RTF."))


def test_rtf_records_its_parser_in_provenance():
    """A seal that cannot say which extractor produced its text cannot be re-verified."""
    meta = asyncio.run(_parse_rtf(MINIMAL_RTF)).metadata or {}
    assert meta["parser"] == "rtf"
    assert meta["format"] == "rtf"


def test_rtf_output_looks_like_language():
    r"""The vacuity test. A control-word soup of `*.*.*` passes a length check.

    Named for the estate's own rule: a token-count test marks OCR garbage as
    recovered and hides loss behind the guard built to expose it.
    """
    text = rtf_to_text(
        r"{\rtf1\ansi{\fonttbl{\f0 Times;}}{\*\generator Riched;}"
        r"\f0 The Division shall protect the rights of each Person served.\par}"
    )
    letters = sum(c.isalpha() or c.isspace() for c in text)
    assert letters / max(len(text), 1) > 0.9, f"not language: {text!r}"
    assert "Riched" not in text


# ---------------------------------------------------------------- the seam ----


def test_parser_refuses_a_format_docling_cannot_read_and_names_the_alternate():
    """Never 'it failed'. Always which format, and what does read it."""
    if not capability().available:
        pytest.skip("Document Intelligence pack not installed")
    parser = DoclingParser()
    with pytest.raises(ValueError, match=r"rtf_parser|does not read"):
        asyncio.run(parser.parse(Path("/nonexistent/rules.rtf")))


def test_supported_extensions_matches_the_capability():
    assert supported_extensions() == capability().extensions


def test_parser_reports_provenance_including_version():
    if not capability().available:
        pytest.skip("Document Intelligence pack not installed")
    assert DoclingParser().capability.version


async def _parse_rtf_async(raw: bytes, tmp: Path):
    p = tmp / "doc.rtf"
    p.write_bytes(raw)
    return await RtfParser().parse(p)


def _parse_rtf(raw: bytes):
    import tempfile

    async def run():
        with tempfile.TemporaryDirectory() as d:
            return await _parse_rtf_async(raw, Path(d))

    return run()

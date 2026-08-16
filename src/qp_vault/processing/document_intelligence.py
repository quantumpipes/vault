# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""The Document Intelligence capability: is docling here, and may it reach the network?

This module is the ONE place that answers those two questions. It exists because on
2026-08-16 an audit found docling reached for six different ways in one estate:

  1. `qp_vault.processing.docling_parser`      the declared seam
  2. `quantumpipes.vault.processor`            the kernel's own converter singleton
  3. `services/verisgov-corpus/build/`         its own 1.2 GB `.venv-docling`
  4. `services/hyperlocal-hub/gov_docs.py`     its own converter and pipeline options
  5. `services/rhtp-freshness-engine/ingest`   the only one that imported the seam
  6. a throwaway script                        written that morning

Three consequences the audit measured, each of which this module is built to make
impossible rather than merely discouraged:

**The engine did not ship with the seam.** `AskQP.app` bundles `docling_parser.py` and
no `docling` package, so `HAS_DOCLING` was False in the shipped desktop app and every
PDF raised `ImportError`. A capability that can be absent must therefore SAY it is
absent, in a form a user interface can render, which is what `capability()` returns.

**Five of the six could reach HuggingFace.** Docling downloads its layout and table
models on first use, and no call site pinned `artifacts_path` or forced `HF_HUB_OFFLINE`
in code. Offline is therefore FORCED here at import, before docling is ever imported,
and leaving it requires naming an environment variable out loud. The pattern is lifted
from the embedding provider, which already got this right (`local_files_only=True`,
`HF_HUB_OFFLINE`, `trust_remote_code=False`).

*Five, not six, and the correction is instructive.* The RHTP freshness engine solved this
a layer down, in its Dockerfile: `docling-tools models download -o
$DOCLING_ARTIFACTS_PATH`, with the variable set in the image. That works, because
docling's settings model declares `env_prefix="DOCLING_"` over a field named
`artifacts_path`. The first version of this module read only its own `QP_DOCLING_ARTIFACTS`
and would have declared that correctly-staged image unavailable. Hence `artifacts_path()`
below reads both. The lesson is the one this whole module is about: a capability check
narrower than the ways the capability can legitimately be present produces a confident
false negative.

**The format allowlist outran the engine.** A hand-written set claimed 28 extensions,
including `.rtf`, `.epub`, `.mobi` and the legacy Office trio, against 18 real
`InputFormat` members. A file matching the claim routed to docling and crashed. The
allowlist is now DERIVED from the installed docling's own `FormatToExtensions`, so the
claim cannot outrun the engine again: upgrade docling and the answer moves with it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- air gap ----
#
# Forced BEFORE any docling/transformers import anywhere in the process. Setting
# these after the libraries load is a no-op, which is the trap: the guard reads as
# present and does nothing. Module import order is the enforcement.

#: Set to "1" to let Document Intelligence reach the network. Deliberate and named,
#: because the alternative is a silent egress from an air-gapped deployment.
ALLOW_NETWORK_ENV = "QP_DOCLING_ALLOW_NETWORK"

#: Directory holding pre-staged docling model artifacts (the Document Intelligence
#: pack). When set, docling loads from here and never resolves a remote repo.
ARTIFACTS_ENV = "QP_DOCLING_ARTIFACTS"

_NETWORK_ALLOWED = os.environ.get(ALLOW_NETWORK_ENV, "").strip() in {"1", "true", "yes"}

if not _NETWORK_ALLOWED:  # pragma: no branch - trivially covered both ways in tests
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


#: Docling's OWN artifacts variable. Its settings model declares
#: `env_prefix="DOCLING_"` over a field named `artifacts_path`, so docling honours this
#: with no help from us. Read it here too, because a deployment that already staged
#: models the documented docling way must not be told it has none: the RHTP freshness
#: engine's Dockerfile does exactly that (`docling-tools models download -o
#: $DOCLING_ARTIFACTS_PATH`), and an earlier version of this module ignored it and would
#: have reported that image as unavailable.
DOCLING_ARTIFACTS_ENV = "DOCLING_ARTIFACTS_PATH"


def artifacts_path() -> Path | None:
    """The pre-staged model directory, or None when no staging is configured.

    Checks the pack variable first, then docling's own. Ours wins only because the pack
    installer sets it deliberately; either is a correct answer.
    """
    for var in (ARTIFACTS_ENV, DOCLING_ARTIFACTS_ENV):
        raw = os.environ.get(var, "").strip()
        if not raw:
            continue
        p = Path(raw).expanduser()
        if p.is_dir():
            return p
    return None


def _cached_models() -> Path | None:
    """A local model cache docling can load from with no network.

    Checked because `artifacts_path` is not the only air-gap-safe source. With
    `HF_HUB_OFFLINE` forced, a populated HuggingFace cache CANNOT reach the network:
    a missing model raises an offline error rather than downloading. Treating a
    populated cache as unavailable would refuse a machine that is already fully
    capable, which is its own kind of dishonesty.
    """
    docling_cache = Path.home() / ".cache" / "docling"
    if docling_cache.is_dir() and any(docling_cache.iterdir()):
        return docling_cache
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    if hub.is_dir() and any(hub.glob("models--docling-project--*")):
        return hub
    return None


# ------------------------------------------------------------ format truth ----
#
# Extensions docling CAN read but that another vault parser owns better. Ceded
# explicitly, with the reason, because a silent subtraction is indistinguishable from
# a bug and the next reader would re-add them.
_CEDED: dict[str, str] = {
    ".txt": "TextParser: plain text needs no layout model",
    ".md": "TextParser: already markdown, converting it only loses fidelity",
    ".text": "TextParser",
    ".vtt": "TranscriptParser: cue timings carry meaning docling discards",
    ".json": "structured input, not a document to extract",
    # Audio and video: docling transcribes them, which is a different capability with
    # a different cost profile and a different accuracy question. Out of scope here.
    ".aac": "audio", ".avi": "audio", ".flac": "audio", ".m4a": "audio",
    ".mov": "audio", ".mp3": "audio", ".mp4": "audio", ".ogg": "audio",
    ".wav": "audio",
}


def _derive_extensions() -> tuple[frozenset[str], str | None]:
    """Ask the installed docling what it reads. Never assert it from memory.

    Returns (extensions, failure_reason). An empty set with a reason means the pack
    is absent; an empty set with no reason would be a bug and cannot happen.
    """
    try:
        from docling.datamodel.base_models import FormatToExtensions
    except ImportError as exc:
        return frozenset(), f"docling is not importable: {exc}"

    exts = {
        f".{ext.lower()}"
        for extensions in FormatToExtensions.values()
        for ext in extensions
    }
    return frozenset(exts - set(_CEDED)), None


def _installed_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("docling")
    except Exception:  # noqa: BLE001 - absence is the answer, not an error
        return None


# -------------------------------------------------------------- capability ----


@dataclass(frozen=True)
class DocumentIntelligence:
    """What this deployment can actually do with a document, and why.

    Rendered directly by the pack installer surface. Every falsey `available` carries
    a `reason` written for a person, because "PDF extraction unavailable" with no
    cause is the failure this whole module exists to stop.
    """

    available: bool
    version: str | None = None
    extensions: frozenset[str] = field(default_factory=frozenset)
    #: Pack-staged model directory, pinned into docling's pipeline options when set.
    artifacts: Path | None = None
    #: Where the models will actually load from: `artifacts` when staged, otherwise the
    #: local cache that made this deployment available. None only when unavailable.
    models: Path | None = None
    offline_enforced: bool = True
    reason: str = ""

    @property
    def needs_pack(self) -> bool:
        """True when installing the Document Intelligence pack would fix this."""
        return not self.available

    def refusal(self, path: Path | None = None) -> str:
        """The sentence a user should see instead of a stack trace."""
        subject = f"{path.name} " if path is not None else ""
        return (
            f"Cannot extract {subject}because Document Intelligence is not installed. "
            f"{self.reason} Install the pack to enable PDF, DOCX, PPTX, XLSX and image "
            f"extraction; until then this file is stored but not indexed."
        )


def capability() -> DocumentIntelligence:
    """Report the Document Intelligence capability. Never raises, never guesses.

    Call this to decide what to offer. Call `DoclingParser()` only once this says
    `available`.
    """
    exts, why = _derive_extensions()
    if why is not None:
        return DocumentIntelligence(
            available=False,
            offline_enforced=not _NETWORK_ALLOWED,
            reason=(
                f"{why}. The pack ships docling and its pre-staged models; the "
                f"application bundles the parser but not the engine."
            ),
        )

    arts = artifacts_path()
    models = arts or _cached_models()
    if models is None and not _NETWORK_ALLOWED:
        # docling imports but has nothing to load. Refuse rather than let it resolve a
        # HuggingFace repo: a first-use network call that "usually works" is exactly
        # the dependency this estate forbids, and it fails at the worst moment.
        return DocumentIntelligence(
            available=False,
            version=_installed_version(),
            extensions=exts,
            offline_enforced=True,
            reason=(
                f"docling {_installed_version()} is installed but no model artifacts "
                f"are available locally. Install the Document Intelligence pack, or "
                f"point {ARTIFACTS_ENV} at a staged model directory. Setting "
                f"{ALLOW_NETWORK_ENV}=1 would permit a one-time download, which an "
                f"air-gapped deployment must not do."
            ),
        )

    return DocumentIntelligence(
        available=True,
        version=_installed_version(),
        extensions=exts,
        artifacts=arts,
        models=models,
        offline_enforced=not _NETWORK_ALLOWED,
    )


class DocumentIntelligenceUnavailable(RuntimeError):  # noqa: N818 - reads as a state, not an error type
    """Raised only by code that already checked `capability()` and proceeded anyway."""

    def __init__(self, cap: DocumentIntelligence, path: Path | None = None) -> None:
        super().__init__(cap.refusal(path))
        self.capability = cap

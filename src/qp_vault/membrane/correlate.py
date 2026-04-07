# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Correlate stage: cross-document contradiction detection.

Checks whether incoming content contradicts existing trusted knowledge
in the vault. Detects "poisoning by contradiction" attacks where an
adversary submits content that conflicts with authoritative sources.

Requires an LLMScreener for semantic contradiction analysis.
Without one, the stage is skipped. Without a vault reference, skipped.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from qp_vault.enums import MembraneResult, MembraneStage
from qp_vault.models import MembraneStageRecord

if TYPE_CHECKING:
    from qp_vault.protocols import LLMScreener, ScreeningResult

_CONTRADICTION_PROMPT = """\
Compare the NEW content against the EXISTING trusted content below.
Determine if the NEW content contradicts the EXISTING content.

<existing>
{existing}
</existing>

<new>
{new_content}
</new>

Respond with ONLY a JSON object:
{{"risk_score": 0.0, "reasoning": "one sentence", "flags": []}}

risk_score: 0.0 (no contradiction) to 1.0 (direct contradiction).
flags: ["contradiction"] if contradictory, else [].
reasoning: one-sentence explanation.\
"""


@dataclass
class CorrelateConfig:
    """Configuration for the correlate stage."""

    screener: LLMScreener | None = None
    vault: Any = None  # AsyncVault (avoid circular import)
    max_trusted_docs: int = 5
    max_content_chars: int = 2000
    risk_threshold: float = 0.7
    tenant_id: str | None = None


async def run_correlate(
    content: str,
    config: CorrelateConfig | None = None,
) -> MembraneStageRecord:
    """Check if new content contradicts existing trusted knowledge.

    Args:
        content: The new text content to check.
        config: Correlate configuration (includes screener + vault ref).

    Returns:
        MembraneStageRecord with PASS, FLAG, or SKIP result.
    """
    if config is None or config.screener is None or config.vault is None:
        return MembraneStageRecord(
            stage=MembraneStage.CORRELATE,
            result=MembraneResult.SKIP,
            reasoning="No screener or vault reference, stage skipped",
        )

    start = time.monotonic()

    # Search vault for related trusted content
    try:
        related = await config.vault.search(
            content[:500],
            tenant_id=config.tenant_id,
            top_k=config.max_trusted_docs,
            min_trust_tier="canonical",
        )
    except Exception:
        return MembraneStageRecord(
            stage=MembraneStage.CORRELATE,
            result=MembraneResult.SKIP,
            reasoning="Vault search failed during correlate",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    if not related:
        return MembraneStageRecord(
            stage=MembraneStage.CORRELATE,
            result=MembraneResult.PASS,  # nosec B105
            reasoning="No trusted content found for comparison",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    # Build existing content summary from trusted docs
    existing_texts = [r.content[:config.max_content_chars] for r in related]
    existing_summary = "\n---\n".join(existing_texts)

    # Ask LLM to check for contradictions
    prompt = _CONTRADICTION_PROMPT.format(
        existing=existing_summary,
        new_content=content[:config.max_content_chars],
    )

    try:
        screening: ScreeningResult = await config.screener.screen(prompt)
    except Exception as e:
        return MembraneStageRecord(
            stage=MembraneStage.CORRELATE,
            result=MembraneResult.SKIP,
            reasoning=f"LLM screener error: {type(e).__name__}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    if screening.risk_score >= config.risk_threshold:
        contradicted_names = [r.resource_name for r in related[:3]]
        return MembraneStageRecord(
            stage=MembraneStage.CORRELATE,
            result=MembraneResult.FLAG,
            risk_score=screening.risk_score,
            reasoning=f"Contradicts trusted content: {', '.join(contradicted_names)}",
            matched_patterns=screening.flags or ["contradiction"],
            duration_ms=duration_ms,
        )

    return MembraneStageRecord(
        stage=MembraneStage.CORRELATE,
        result=MembraneResult.PASS,  # nosec B105
        risk_score=screening.risk_score,
        reasoning=screening.reasoning,
        duration_ms=duration_ms,
    )

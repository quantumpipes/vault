# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Adaptive scan: LLM-based semantic content screening.

Uses a pluggable LLMScreener to detect adversarial content that regex
patterns cannot catch: obfuscated prompt injection, encoded payloads,
social engineering, and semantic attacks. Air-gap safe when backed by
a local LLM (Ollama, vLLM).

The adaptive scan runs after innate_scan and before the release gate.
If no LLMScreener is configured, the stage is skipped (SKIP result).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qp_vault.enums import MembraneResult, MembraneStage
from qp_vault.models import MembraneStageRecord

if TYPE_CHECKING:
    from qp_vault.protocols import LLMScreener

_DEFAULT_MAX_CONTENT_LENGTH = 4000  # Chars sent to LLM (cost/latency bound)
_DEFAULT_RISK_THRESHOLD = 0.7  # >= this score triggers FLAG


@dataclass
class AdaptiveScanConfig:
    """Configuration for the adaptive scan stage."""

    screener: LLMScreener | None = None
    max_content_length: int = _DEFAULT_MAX_CONTENT_LENGTH
    risk_threshold: float = _DEFAULT_RISK_THRESHOLD
    flag_categories: list[str] = field(default_factory=lambda: [
        "prompt_injection",
        "jailbreak",
        "encoded_payload",
        "social_engineering",
        "data_exfiltration",
        "instruction_override",
    ])


async def run_adaptive_scan(
    content: str,
    config: AdaptiveScanConfig | None = None,
) -> MembraneStageRecord:
    """Run LLM-based adaptive scan on content.

    Args:
        content: The text content to screen.
        config: Adaptive scan configuration (includes LLMScreener).

    Returns:
        MembraneStageRecord with PASS, FLAG, or SKIP result.
    """
    if config is None or config.screener is None:
        return MembraneStageRecord(
            stage=MembraneStage.ADAPTIVE_SCAN,
            result=MembraneResult.SKIP,
            reasoning="No LLM screener configured, stage skipped",
        )

    # Truncate content for cost/latency
    scan_content = content[:config.max_content_length]

    start = time.monotonic()
    try:
        screening = await config.screener.screen(scan_content)
    except Exception as e:
        # LLM failure should not block ingestion; log and skip
        return MembraneStageRecord(
            stage=MembraneStage.ADAPTIVE_SCAN,
            result=MembraneResult.SKIP,
            reasoning=f"LLM screener error: {type(e).__name__}",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    if screening.risk_score >= config.risk_threshold:
        return MembraneStageRecord(
            stage=MembraneStage.ADAPTIVE_SCAN,
            result=MembraneResult.FLAG,
            risk_score=screening.risk_score,
            reasoning=screening.reasoning,
            matched_patterns=screening.flags or [],
            duration_ms=duration_ms,
        )

    return MembraneStageRecord(
        stage=MembraneStage.ADAPTIVE_SCAN,
        result=MembraneResult.PASS,  # nosec B105
        risk_score=screening.risk_score,
        reasoning=screening.reasoning,
        matched_patterns=screening.flags or [],
        duration_ms=duration_ms,
    )

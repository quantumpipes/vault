# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Innate scan: pattern-based content screening.

Fast, deterministic checks using regex patterns, blocklists,
and heuristics. No LLM required. Analogous to the innate immune
system: broad, fast, non-adaptive detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from qp_vault.enums import CISResult, CISStage
from qp_vault.models import CISStageRecord

# Default blocklist patterns (prompt injection, jailbreak attempts, data exfiltration)
DEFAULT_BLOCKLIST: list[str] = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+the\s+above",
    r"disregard\s+your\s+(system\s+)?prompt",
    r"you\s+are\s+now\s+(?:DAN|jailbroken|unfiltered)",
    r"pretend\s+you\s+are\s+(?:not\s+)?an?\s+AI",
    r"bypass\s+(?:your\s+)?(?:safety|content)\s+(?:filter|policy)",
    r"<script[\s>]",
    r"javascript:",
    r"data:text/html",
    r"\bexec\s*\(",
    r"\beval\s*\(",
    r"__import__\s*\(",
    r"subprocess\.",
    r"os\.system\s*\(",
]


@dataclass
class InnateScanConfig:
    """Configuration for innate scan stage."""

    blocklist_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKLIST))
    max_pattern_matches: int = 0  # 0 = any match triggers flag
    case_sensitive: bool = False


async def run_innate_scan(
    content: str,
    config: InnateScanConfig | None = None,
) -> CISStageRecord:
    """Run innate scan on content.

    Checks content against regex blocklist patterns.

    Args:
        content: The text content to scan.
        config: Optional scan configuration.

    Returns:
        CISStageRecord with PASS, FLAG, or FAIL result.
    """
    if config is None:
        config = InnateScanConfig()

    flags = re.IGNORECASE if not config.case_sensitive else 0
    matches: list[str] = []

    for pattern in config.blocklist_patterns:
        try:
            if re.search(pattern, content, flags):
                matches.append(pattern)
        except re.error:
            continue  # Skip malformed patterns

    if matches:
        return CISStageRecord(
            stage=CISStage.INNATE_SCAN,
            result=CISResult.FLAG,
            matched_patterns=matches[:5],
            reasoning=f"Matched {len(matches)} blocklist patterns",
        )

    return CISStageRecord(
        stage=CISStage.INNATE_SCAN,
        result=CISResult.PASS,  # nosec B105 — CIS stage result, not a password
        reasoning=f"Checked {len(config.blocklist_patterns)} patterns, none matched",
    )

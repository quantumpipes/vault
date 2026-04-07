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

from qp_vault.enums import MembraneResult, MembraneStage
from qp_vault.models import MembraneStageRecord

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
) -> MembraneStageRecord:
    """Run innate scan on content.

    Checks content against regex blocklist patterns.

    Args:
        content: The text content to scan.
        config: Optional scan configuration.

    Returns:
        MembraneStageRecord with PASS, FLAG, or FAIL result.
    """
    if config is None:
        config = InnateScanConfig()

    flags = re.IGNORECASE if not config.case_sensitive else 0
    matches: list[str] = []

    # Limit content length for regex scanning to prevent catastrophic backtracking
    scan_content = content[:500_000]  # 500KB max for pattern matching

    for pattern in config.blocklist_patterns:
        try:
            # Pre-compile to validate pattern; skip if invalid
            compiled = re.compile(pattern, flags)
            if compiled.search(scan_content):
                matches.append(pattern)
        except (re.error, RecursionError):
            continue  # Skip malformed or pathological patterns

    if matches:
        return MembraneStageRecord(
            stage=MembraneStage.INNATE_SCAN,
            result=MembraneResult.FLAG,
            matched_patterns=matches[:5],
            reasoning=f"Matched {len(matches)} blocklist patterns",
        )

    return MembraneStageRecord(
        stage=MembraneStage.INNATE_SCAN,
        result=MembraneResult.PASS,  # nosec B105 — Membrane stage result, not a password
        reasoning=f"Checked {len(config.blocklist_patterns)} patterns, none matched",
    )

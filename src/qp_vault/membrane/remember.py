# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Remember stage: attack pattern registry.

Learns from quarantined and flagged content to improve future screening.
Maintains a registry of attack patterns (content fingerprints, matched
patterns, risk scores) that boost the innate scan on future ingestion.

The registry is in-memory by default. For persistence, patterns can be
exported/imported via JSON.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from qp_vault.enums import MembraneResult, MembraneStage
from qp_vault.models import MembraneStageRecord


@dataclass
class AttackPattern:
    """A learned attack pattern from previously flagged content."""

    fingerprint: str  # SHA3-256 of normalized content prefix
    matched_flags: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    first_seen: str = ""
    last_seen: str = ""
    count: int = 1


class AttackRegistry:
    """In-memory registry of learned attack patterns.

    Patterns are fingerprinted from content prefixes so that similar
    future attacks are flagged faster (before LLM evaluation).
    """

    def __init__(self, max_patterns: int = 10_000) -> None:
        self._patterns: dict[str, AttackPattern] = {}
        self._max = max_patterns

    def learn(self, content: str, flags: list[str], risk_score: float) -> None:
        """Record an attack pattern from flagged/quarantined content."""
        fp = self._fingerprint(content)
        now = datetime.now(tz=UTC).isoformat()

        if fp in self._patterns:
            p = self._patterns[fp]
            p.count += 1
            p.last_seen = now
            p.risk_score = max(p.risk_score, risk_score)
            for f in flags:
                if f not in p.matched_flags:
                    p.matched_flags.append(f)
        else:
            if len(self._patterns) >= self._max:
                # Evict oldest pattern
                oldest = min(self._patterns, key=lambda k: self._patterns[k].last_seen)
                del self._patterns[oldest]
            self._patterns[fp] = AttackPattern(
                fingerprint=fp,
                matched_flags=flags,
                risk_score=risk_score,
                first_seen=now,
                last_seen=now,
            )

    def check(self, content: str) -> AttackPattern | None:
        """Check if content matches a known attack pattern."""
        fp = self._fingerprint(content)
        return self._patterns.get(fp)

    def export_patterns(self) -> list[dict[str, Any]]:
        """Export all patterns as dicts for persistence."""
        return [
            {
                "fingerprint": p.fingerprint,
                "matched_flags": p.matched_flags,
                "risk_score": p.risk_score,
                "first_seen": p.first_seen,
                "last_seen": p.last_seen,
                "count": p.count,
            }
            for p in self._patterns.values()
        ]

    def import_patterns(self, patterns: list[dict[str, Any]]) -> None:
        """Import patterns from persistence."""
        for p in patterns:
            self._patterns[p["fingerprint"]] = AttackPattern(**p)

    @property
    def pattern_count(self) -> int:
        return len(self._patterns)

    @staticmethod
    def _fingerprint(content: str) -> str:
        """SHA3-256 fingerprint of normalized content prefix."""
        normalized = content[:500].lower().strip()
        return hashlib.sha3_256(normalized.encode()).hexdigest()[:32]


# Global registry instance
_registry = AttackRegistry()


def get_attack_registry() -> AttackRegistry:
    """Get the global attack pattern registry."""
    return _registry


async def run_remember(
    content: str,
    registry: AttackRegistry | None = None,
) -> MembraneStageRecord:
    """Check content against known attack patterns.

    Runs before innate_scan as a fast pre-check. Known attack
    fingerprints are flagged immediately without regex or LLM.

    Args:
        content: The text content to check.
        registry: Attack pattern registry (default: global).

    Returns:
        MembraneStageRecord with PASS or FLAG result.
    """
    reg = registry or _registry
    start = time.monotonic()

    match = reg.check(content)
    duration_ms = int((time.monotonic() - start) * 1000)

    if match:
        return MembraneStageRecord(
            stage=MembraneStage.REMEMBER,
            result=MembraneResult.FLAG,
            risk_score=match.risk_score,
            reasoning=f"Matches known attack pattern (seen {match.count}x)",
            matched_patterns=match.matched_flags,
            duration_ms=duration_ms,
        )

    return MembraneStageRecord(
        stage=MembraneStage.REMEMBER,
        result=MembraneResult.PASS,  # nosec B105
        reasoning="No known attack pattern match",
        duration_ms=duration_ms,
    )

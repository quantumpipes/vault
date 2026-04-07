# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Surveil stage: query-time re-evaluation of search results.

Applied at search time (not ingest time). Re-scores resources based on
adversarial status changes since initial indexing. Resources that were
originally VERIFIED but later became SUSPICIOUS get a penalty applied
to their search relevance.

This is not a pipeline stage in the traditional sense. It's a post-search
filter that vault.search() calls after trust weighting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp_vault.enums import AdversarialStatus

if TYPE_CHECKING:
    from qp_vault.models import SearchResult


def apply_surveil(
    results: list[SearchResult],
    *,
    quarantine_threshold: float = 0.0,
) -> list[SearchResult]:
    """Re-evaluate search results at query time.

    Filters out quarantined resources and applies penalties to suspicious
    resources that may have been flagged since initial screening.

    Args:
        results: Search results after trust weighting.
        quarantine_threshold: Minimum adversarial multiplier to include.
            Resources below this are excluded (default: exclude quarantined).

    Returns:
        Filtered and re-scored results.
    """
    filtered: list[SearchResult] = []

    for r in results:
        adv_status = r.adversarial_status
        if isinstance(adv_status, str):
            try:
                adv_status = AdversarialStatus(adv_status)
            except ValueError:
                adv_status = AdversarialStatus.UNVERIFIED

        # Exclude suspicious resources with very high penalty
        # (Quarantined resources are already excluded by storage layer)

        # Apply surveillance penalty for suspicious resources
        if adv_status == AdversarialStatus.SUSPICIOUS:
            r = r.model_copy(update={
                "relevance": r.relevance * 0.3,
                "explain_metadata": {
                    **(r.explain_metadata or {}),
                    "surveil": "suspicious, relevance penalized 0.3x",
                },
            })

        # Add verification boost for explicitly verified resources
        if adv_status == AdversarialStatus.VERIFIED:
            r = r.model_copy(update={
                "explain_metadata": {
                    **(r.explain_metadata or {}),
                    "surveil": "verified",
                },
            })

        if r.relevance >= quarantine_threshold:
            filtered.append(r)

    return filtered

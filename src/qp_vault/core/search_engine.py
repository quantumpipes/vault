"""Trust-weighted hybrid search engine for qp-vault.

Applies trust tier weights and freshness decay on top of raw
vector + text scores from the storage backend.

Formula:
    relevance = (vector_weight * vector_sim + text_weight * text_rank)
                * trust_weight
                * freshness_decay
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from qp_vault.enums import AdversarialStatus, ResourceStatus, TrustTier

if TYPE_CHECKING:
    from qp_vault.config import VaultConfig
    from qp_vault.models import SearchResult

# Default trust weights (organizational dimension)
TRUST_WEIGHTS: dict[str, float] = {
    TrustTier.CANONICAL.value: 1.5,
    TrustTier.WORKING.value: 1.0,
    TrustTier.EPHEMERAL.value: 0.7,
    TrustTier.ARCHIVED.value: 0.25,
}

# Adversarial verification multipliers (security dimension)
# Effective RAG weight = trust_weight * adversarial_multiplier
ADVERSARIAL_MULTIPLIERS: dict[str, float] = {
    AdversarialStatus.VERIFIED.value: 1.0,
    AdversarialStatus.UNVERIFIED.value: 0.7,
    AdversarialStatus.SUSPICIOUS.value: 0.3,
}

# Statuses excluded from search results by default
EXCLUDED_STATUSES: set[str] = {
    ResourceStatus.QUARANTINED.value,
    ResourceStatus.DELETED.value,
}

# Default freshness half-life in days
FRESHNESS_HALF_LIFE: dict[str, int] = {
    TrustTier.CANONICAL.value: 365,
    TrustTier.WORKING.value: 180,
    TrustTier.EPHEMERAL.value: 30,
    TrustTier.ARCHIVED.value: 730,
}


def compute_trust_weight(trust_tier: str, config: VaultConfig | None = None) -> float:
    """Get trust weight multiplier for a given tier.

    Args:
        trust_tier: Trust tier value (e.g., "canonical", "working").
        config: Optional VaultConfig with custom trust_weights.

    Returns:
        Float multiplier (e.g., 1.5 for canonical, 1.0 for working).
    """
    weights = config.trust_weights if config else TRUST_WEIGHTS
    return weights.get(trust_tier, 1.0)


def compute_adversarial_multiplier(adversarial_status: str) -> float:
    """Get adversarial verification multiplier.

    Args:
        adversarial_status: Adversarial status value ("verified", "unverified", "suspicious").

    Returns:
        Float multiplier. Effective RAG weight = trust_weight * adversarial_multiplier.
    """
    return ADVERSARIAL_MULTIPLIERS.get(adversarial_status, 0.7)


def is_searchable(status: str) -> bool:
    """Check if a resource with the given status should appear in search results.

    QUARANTINED and DELETED resources are excluded by default.
    This MUST be checked at every retrieval path, not just search.

    Args:
        status: ResourceStatus value (e.g., "quarantined", "indexed").

    Returns:
        True if the resource should appear in results.
    """
    return status not in EXCLUDED_STATUSES


def filter_searchable(
    results: list[SearchResult],
    resource_statuses: dict[str, str] | None = None,
    *,
    include_quarantined: bool = False,
) -> list[SearchResult]:
    """Defense-in-depth filter: remove non-searchable results from any result list.

    Call this as a final safety net on every result set, even if the query
    should have already excluded quarantined resources. Belt-and-suspenders.

    Uses resource_statuses lookup (resource_id -> ResourceStatus value) to check
    whether each result's source resource is searchable. If no lookup is provided,
    results pass through (the caller is responsible for pre-filtering).

    Args:
        results: Search results to filter.
        resource_statuses: Mapping of resource_id to ResourceStatus value.
        include_quarantined: If True, skip filtering (admin use only).

    Returns:
        Filtered results with non-searchable resources removed.
    """
    if include_quarantined or resource_statuses is None:
        return results
    return [
        r for r in results
        if is_searchable(resource_statuses.get(r.resource_id, "indexed"))
    ]


def compute_freshness(
    updated_at: datetime | str | None,
    trust_tier: str,
    config: VaultConfig | None = None,
) -> float:
    """Compute freshness decay: exp(-age_days / half_life).

    Returns 1.0 for recent documents, decays toward 0 over time.
    Half-life is configurable per trust tier.
    """
    if updated_at is None:
        return 1.0

    if isinstance(updated_at, str):
        try:
            updated_at = datetime.fromisoformat(updated_at)
        except ValueError:
            return 1.0

    half_lives = config.freshness_half_life if config else FRESHNESS_HALF_LIFE
    half_life = half_lives.get(trust_tier, 180)

    age_days = (datetime.now(tz=UTC) - updated_at).total_seconds() / 86400
    if age_days <= 0:
        return 1.0

    # Exponential decay: exp(-age / half_life * ln(2))
    return math.exp(-age_days / half_life * math.log(2))


def apply_trust_weighting(
    results: list[SearchResult],
    config: VaultConfig | None = None,
) -> list[SearchResult]:
    """Apply 2D trust weights and freshness decay to search results.

    Computes composite relevance = raw * organizational_trust * adversarial_multiplier * freshness.
    Re-sorts results by composite score (highest first).

    Args:
        results: List of SearchResult objects from storage backend.
        config: Optional VaultConfig with custom trust weights and freshness half-lives.

    Returns:
        New list of SearchResult objects with updated relevance, trust_weight, and freshness fields.
    """
    weighted: list[SearchResult] = []

    for result in results:
        tier = result.trust_tier.value if hasattr(result.trust_tier, "value") else str(result.trust_tier)
        tw = compute_trust_weight(tier, config)

        # CIS 2D trust: multiply by adversarial verification status
        adv_status = getattr(result, "adversarial_status", None)
        adv_str = adv_status.value if hasattr(adv_status, "value") else str(adv_status or "unverified")
        adv_mult = compute_adversarial_multiplier(adv_str)

        # Freshness: we don't have updated_at on SearchResult, use 1.0 for now
        freshness = 1.0

        # Composite score: raw * organizational_trust * adversarial_verification * freshness
        raw = result.relevance
        composite = raw * tw * adv_mult * freshness

        weighted.append(
            result.model_copy(
                update={
                    "trust_weight": tw * adv_mult,
                    "freshness": freshness,
                    "relevance": composite,
                }
            )
        )

    # Re-sort by composite relevance
    weighted.sort(key=lambda r: r.relevance, reverse=True)
    return weighted

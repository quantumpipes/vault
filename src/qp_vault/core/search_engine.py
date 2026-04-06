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

from qp_vault.enums import TrustTier

if TYPE_CHECKING:
    from qp_vault.config import VaultConfig
    from qp_vault.models import SearchResult

# Default trust weights
TRUST_WEIGHTS: dict[str, float] = {
    TrustTier.CANONICAL.value: 1.5,
    TrustTier.WORKING.value: 1.0,
    TrustTier.EPHEMERAL.value: 0.7,
    TrustTier.ARCHIVED.value: 0.25,
}

# Default freshness half-life in days
FRESHNESS_HALF_LIFE: dict[str, int] = {
    TrustTier.CANONICAL.value: 365,
    TrustTier.WORKING.value: 180,
    TrustTier.EPHEMERAL.value: 30,
    TrustTier.ARCHIVED.value: 730,
}


def compute_trust_weight(trust_tier: str, config: VaultConfig | None = None) -> float:
    """Get trust weight multiplier for a given tier."""
    weights = config.trust_weights if config else TRUST_WEIGHTS
    return weights.get(trust_tier, 1.0)


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
    """Apply trust weights and freshness decay to search results.

    Mutates the relevance, trust_weight, and freshness fields on each result,
    then re-sorts by composite relevance score.
    """
    weighted: list[SearchResult] = []

    for result in results:
        tier = result.trust_tier.value if hasattr(result.trust_tier, "value") else str(result.trust_tier)
        tw = compute_trust_weight(tier, config)
        # Freshness: we don't have updated_at on SearchResult, use 1.0 for now
        # (will be enhanced when we add resource timestamps to search results)
        freshness = 1.0

        # Composite score
        raw = result.relevance  # Already computed by storage backend
        composite = raw * tw * freshness

        weighted.append(
            result.model_copy(
                update={
                    "trust_weight": tw,
                    "freshness": freshness,
                    "relevance": composite,
                }
            )
        )

    # Re-sort by composite relevance
    weighted.sort(key=lambda r: r.relevance, reverse=True)
    return weighted

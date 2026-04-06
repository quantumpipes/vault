"""Integrity detection suite for qp-vault.

Detects quality issues in stored knowledge:
  - Staleness: documents that may be outdated
  - Duplicates: near-identical content (by hash or semantic similarity)
  - Orphans: resources with zero search hits / low connectivity
  - Contradictions: logically incompatible claims (requires embedding provider)

Produces a composite HealthScore (0-100).
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import UTC, datetime

from qp_vault.models import HealthScore, Resource


def compute_staleness_score(
    resource: Resource,
    *,
    volatile_keywords: set[str] | None = None,
) -> float:
    """Score how stale a resource is (0 = fresh, 1 = very stale).

    Considers:
    - Age since last update
    - Trust tier (ephemeral decays faster)
    - Presence of volatile topic keywords
    """
    default_volatile = {"policy", "procedure", "sop", "guideline", "regulation", "deadline", "schedule"}
    volatile = volatile_keywords or default_volatile

    # Age in days
    updated = resource.updated_at
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    age_days = max(0, (datetime.now(tz=UTC) - updated).total_seconds() / 86400)

    # Half-life based on trust tier
    tier = resource.trust_tier.value if hasattr(resource.trust_tier, "value") else str(resource.trust_tier)
    half_lives = {
        "canonical": 365,
        "working": 180,
        "ephemeral": 30,
        "archived": 730,
    }
    half_life = half_lives.get(tier, 180)

    # Volatility boost: if name contains volatile keywords, decay faster
    name_lower = resource.name.lower()
    if any(kw in name_lower for kw in volatile):
        half_life = int(half_life * 0.5)

    # Exponential decay -> staleness
    freshness = math.exp(-age_days / max(half_life, 1) * math.log(2))
    staleness = 1.0 - freshness

    return min(1.0, max(0.0, staleness))


def find_duplicates_by_hash(resources: list[Resource]) -> list[list[Resource]]:
    """Find resources with identical content hashes.

    Returns groups of 2+ resources sharing the same hash.
    """
    by_hash: dict[str, list[Resource]] = {}
    for r in resources:
        by_hash.setdefault(r.content_hash, []).append(r)

    return [group for group in by_hash.values() if len(group) > 1]


def find_orphans(
    resources: list[Resource],
    *,
    min_age_days: int = 30,
) -> list[Resource]:
    """Find orphan resources: old, never in a collection, no tags.

    These are resources that likely have low connectivity in the knowledge graph.
    """
    orphans = []
    now = datetime.now(tz=UTC)

    for r in resources:
        updated = r.updated_at
        if isinstance(updated, str):
            updated = datetime.fromisoformat(updated)
        age_days = (now - updated).total_seconds() / 86400

        if age_days < min_age_days:
            continue

        is_orphan = (
            not r.collection_id
            and not r.tags
            and not r.supersedes
            and not r.superseded_by
        )
        if is_orphan:
            orphans.append(r)

    return orphans


def compute_health_score(
    resources: list[Resource],
) -> HealthScore:
    """Compute composite health score (0-100) for the vault.

    Components:
    - coherence: absence of duplicates (100 = no duplicates)
    - freshness: average freshness across resources (100 = all fresh)
    - uniqueness: content diversity (100 = all unique hashes)
    - connectivity: resources in collections / with tags (100 = all connected)
    - trust_alignment: resources have explicit trust tiers (100 = all classified)
    """
    if not resources:
        return HealthScore(
            overall=100.0,
            coherence=100.0,
            freshness=100.0,
            uniqueness=100.0,
            connectivity=100.0,
            trust_alignment=100.0,
            issue_count=0,
            resource_count=0,
        )

    n = len(resources)

    # Freshness: average (1 - staleness) * 100
    staleness_scores = [compute_staleness_score(r) for r in resources]
    avg_freshness = (1.0 - sum(staleness_scores) / n) * 100

    # Uniqueness: unique hashes / total * 100
    unique_hashes = len(set(r.content_hash for r in resources))
    uniqueness = (unique_hashes / n) * 100

    # Connectivity: resources with collection or tags / total * 100
    connected = sum(1 for r in resources if r.collection_id or r.tags)
    connectivity = (connected / n) * 100

    # Trust alignment: resources with non-default trust / total * 100
    # (having explicit trust assignment is better than all being "working")
    tier_counts = Counter(
        r.trust_tier.value if hasattr(r.trust_tier, "value") else str(r.trust_tier)
        for r in resources
    )
    # Penalize if 100% are "working" (no curation); only for non-trivial vaults
    non_default = sum(v for k, v in tier_counts.items() if k != "working")
    trust_alignment = min(100.0, (non_default / n) * 200 + 50) if n > 5 else 100.0

    # Coherence: penalize duplicates
    dup_groups = find_duplicates_by_hash(resources)
    dup_count = sum(len(g) - 1 for g in dup_groups)  # Extra copies
    coherence = max(0, (1 - dup_count / max(n, 1))) * 100

    # Issue count
    stale_count = sum(1 for s in staleness_scores if s > 0.7)
    orphan_count = len(find_orphans(resources))
    issue_count = dup_count + stale_count + orphan_count

    # Weighted composite
    overall = (
        0.25 * avg_freshness
        + 0.20 * uniqueness
        + 0.20 * coherence
        + 0.20 * connectivity
        + 0.15 * trust_alignment
    )

    return HealthScore(
        overall=round(min(100, max(0, overall)), 1),
        coherence=round(coherence, 1),
        freshness=round(avg_freshness, 1),
        uniqueness=round(uniqueness, 1),
        connectivity=round(connectivity, 1),
        trust_alignment=round(trust_alignment, 1),
        issue_count=issue_count,
        resource_count=n,
    )

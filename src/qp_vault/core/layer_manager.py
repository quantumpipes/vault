"""Memory layer manager for qp-vault.

Provides three semantic partitions of vault knowledge:
  - OPERATIONAL: SOPs, runbooks, active procedures (high freshness weight)
  - STRATEGIC: Decisions, OKRs, ADRs (long half-life, canonical default)
  - COMPLIANCE: Audit evidence, certifications (permanent retention, audit reads)

Each layer has configurable defaults for trust tier, freshness half-life,
search boost, retention policy, and whether reads are audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from qp_vault.enums import (
    EventType,
    MemoryLayer,
    TrustTier,
)
from qp_vault.models import Resource, SearchResult, VaultEvent

if TYPE_CHECKING:
    from qp_vault.config import VaultConfig


@dataclass
class LayerConfig:
    """Runtime configuration for a memory layer."""

    name: MemoryLayer
    default_trust: TrustTier
    freshness_half_life_days: int
    search_boost: float
    retention: str  # "standard" or "permanent"
    audit_reads: bool


DEFAULT_LAYER_CONFIGS: dict[MemoryLayer, LayerConfig] = {
    MemoryLayer.OPERATIONAL: LayerConfig(
        name=MemoryLayer.OPERATIONAL,
        default_trust=TrustTier.WORKING,
        freshness_half_life_days=90,
        search_boost=1.5,
        retention="standard",
        audit_reads=False,
    ),
    MemoryLayer.STRATEGIC: LayerConfig(
        name=MemoryLayer.STRATEGIC,
        default_trust=TrustTier.CANONICAL,
        freshness_half_life_days=365,
        search_boost=1.0,
        retention="standard",
        audit_reads=False,
    ),
    MemoryLayer.COMPLIANCE: LayerConfig(
        name=MemoryLayer.COMPLIANCE,
        default_trust=TrustTier.CANONICAL,
        freshness_half_life_days=730,
        search_boost=1.0,
        retention="permanent",
        audit_reads=True,
    ),
}


class LayerManager:
    """Manages memory layer configuration and routing."""

    def __init__(self, config: VaultConfig | None = None) -> None:
        self._configs: dict[MemoryLayer, LayerConfig] = dict(DEFAULT_LAYER_CONFIGS)

        # Override from VaultConfig if provided
        if config and config.layer_defaults:
            for name, defaults in config.layer_defaults.items():
                layer = MemoryLayer(name)
                if layer in self._configs:
                    lc = self._configs[layer]
                    lc.default_trust = TrustTier(defaults.trust_tier)
                    lc.freshness_half_life_days = defaults.half_life_days
                    lc.search_boost = defaults.search_boost
                    lc.retention = defaults.retention
                    lc.audit_reads = defaults.audit_reads

    def get_config(self, layer: MemoryLayer) -> LayerConfig:
        """Get configuration for a layer."""
        return self._configs[layer]

    def get_default_trust(self, layer: MemoryLayer) -> TrustTier:
        """Get the default trust tier for a layer."""
        return self._configs[layer].default_trust

    def get_search_boost(self, layer: MemoryLayer) -> float:
        """Get the search relevance boost for a layer."""
        return self._configs[layer].search_boost

    def should_audit_reads(self, layer: MemoryLayer) -> bool:
        """Whether reads on this layer should be audited."""
        return self._configs[layer].audit_reads

    def get_stats(
        self, resources: list[Resource]
    ) -> dict[str, dict[str, Any]]:
        """Compute per-layer statistics."""
        stats: dict[str, dict[str, Any]] = {}

        for layer in MemoryLayer:
            layer_resources = [r for r in resources if r.layer and
                               (r.layer.value if hasattr(r.layer, "value") else r.layer) == layer.value]
            lc = self._configs[layer]
            stats[layer.value] = {
                "resource_count": len(layer_resources),
                "default_trust": lc.default_trust.value,
                "search_boost": lc.search_boost,
                "retention": lc.retention,
                "audit_reads": lc.audit_reads,
            }

        return stats


class LayerView:
    """Scoped view of a memory layer.

    Provides the same add/search/list API as Vault, but automatically
    scoped to a specific layer with layer-appropriate defaults.
    """

    def __init__(
        self,
        layer: MemoryLayer,
        vault: Any,  # AsyncVault (avoid circular import)
        layer_manager: LayerManager,
    ) -> None:
        self._layer = layer
        self._vault = vault
        self._layer_config = layer_manager.get_config(layer)
        self._layer_manager = layer_manager

    async def add(
        self,
        source: Any,
        *,
        name: str | None = None,
        trust_tier: TrustTier | str | None = None,
        **kwargs: Any,
    ) -> Resource:
        """Add a resource to this layer.

        If trust_tier is not specified, uses the layer's default trust tier.
        """
        effective_trust = trust_tier or self._layer_config.default_trust
        return await self._vault.add(  # type: ignore[no-any-return]
            source,
            name=name,
            trust_tier=effective_trust,
            layer=self._layer,
            **kwargs,
        )

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        **kwargs: Any,
    ) -> list[SearchResult]:
        """Search within this layer only."""
        # Audit the read if this layer requires it
        if self._layer_config.audit_reads and self._vault._auditor:
            event = VaultEvent(
                event_type=EventType.SEARCH,
                resource_id="",
                resource_name="",
                resource_hash="",
                details={"query": query, "layer": self._layer.value},
            )
            await self._vault._auditor.record(event)

        return await self._vault.search(  # type: ignore[no-any-return]
            query,
            top_k=top_k,
            layer=self._layer,
            _layer_boost=self._layer_config.search_boost,
            **kwargs,
        )

    async def list(self, **kwargs: Any) -> list[Resource]:
        """List resources in this layer."""
        return await self._vault.list(layer=self._layer, **kwargs)  # type: ignore[no-any-return]

    @property
    def config(self) -> LayerConfig:
        """Get this layer's configuration."""
        return self._layer_config

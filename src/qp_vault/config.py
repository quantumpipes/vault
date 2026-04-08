"""Configuration for qp-vault."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pathlib import Path


class LayerDefaults(BaseModel):
    """Default settings for a memory layer."""

    trust_tier: str = "working"
    half_life_days: int = 180
    search_boost: float = 1.0
    retention: str = "standard"
    audit_reads: bool = False


class VaultConfig(BaseModel):
    """Configuration for a Vault instance."""

    # Storage
    backend: str = "sqlite"
    postgres_dsn: str | None = None
    postgres_ssl: bool = True  # Require SSL for PostgreSQL connections
    postgres_ssl_verify: bool = False  # Allow self-signed certs (dev-friendly default)

    # Chunking
    chunk_target_tokens: int = 512
    chunk_min_tokens: int = 100
    chunk_max_tokens: int = 1024
    chunk_overlap_tokens: int = 50

    # Search
    vector_weight: float = 0.7
    text_weight: float = 0.3
    default_top_k: int = 10
    default_threshold: float = 0.0

    # Grep scoring (coverage is a multiplier, these weight the base score)
    grep_rank_weight: float = 0.7       # Weight for native text rank (FTS5/trigram)
    grep_proximity_weight: float = 0.3  # Weight for keyword proximity within chunk

    # Trust weights (trust_tier -> multiplier)
    trust_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "canonical": 1.5,
            "working": 1.0,
            "ephemeral": 0.7,
            "archived": 0.25,
        }
    )

    # Freshness half-life in days (trust_tier -> days)
    freshness_half_life: dict[str, int] = Field(
        default_factory=lambda: {
            "canonical": 365,
            "working": 180,
            "ephemeral": 30,
            "archived": 730,
        }
    )

    # Lifecycle
    ephemeral_ttl_days: int = 90
    auto_expire: bool = True

    # Limits
    max_file_size_mb: int = 500
    max_resources_per_tenant: int | None = None  # None = unlimited
    query_timeout_ms: int = 30000  # 30 seconds default
    health_cache_ttl_seconds: int = 30  # Cache health/status responses

    # Plugins
    plugins_dir: str | None = None

    # Memory layer defaults
    layer_defaults: dict[str, LayerDefaults] = Field(
        default_factory=lambda: {
            "operational": LayerDefaults(
                trust_tier="working", half_life_days=90, search_boost=1.5
            ),
            "strategic": LayerDefaults(
                trust_tier="canonical", half_life_days=365, search_boost=1.0
            ),
            "compliance": LayerDefaults(
                trust_tier="canonical",
                retention="permanent",
                audit_reads=True,
            ),
        }
    )

    @classmethod
    def from_toml(cls, path: str | Path) -> VaultConfig:
        """Load configuration from a TOML file."""
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)
        return cls(**_flatten_toml(data))


def _flatten_toml(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested TOML sections into flat config keys."""
    flat: dict[str, Any] = {}
    for section, values in data.items():
        if isinstance(values, dict) and section in (
            "storage",
            "chunking",
            "search",
            "lifecycle",
            "limits",
            "plugins",
        ):
            flat.update(values)
        else:
            flat[section] = values
    return flat

"""Knowledge graph subpackage for qp-vault.

Public API: GraphEngine (via lazy import) and all domain models.
"""

from qp_vault.graph.models import (
    DetectedEntity,
    GraphEdge,
    GraphMention,
    GraphNode,
    GraphScanJob,
    NeighborResult,
)

__all__ = [
    "DetectedEntity",
    "GraphEdge",
    "GraphEngine",
    "GraphMention",
    "GraphNode",
    "GraphScanJob",
    "NeighborResult",
]


def __getattr__(name: str) -> type:
    """Lazy import for GraphEngine to avoid circular imports."""
    if name == "GraphEngine":
        from qp_vault.graph.service import GraphEngine
        return GraphEngine
    raise AttributeError(f"module 'qp_vault.graph' has no attribute {name!r}")

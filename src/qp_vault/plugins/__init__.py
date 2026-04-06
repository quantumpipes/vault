"""Plugin system for qp-vault.

Decorators for registering custom plugins:
    from qp_vault.plugins import embedder, parser, policy
"""

from qp_vault.plugins.decorators import embedder, parser, policy
from qp_vault.plugins.registry import PluginRegistry, get_registry

__all__ = ["embedder", "parser", "policy", "PluginRegistry", "get_registry"]

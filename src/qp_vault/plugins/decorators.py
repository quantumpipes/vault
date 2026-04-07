"""Plugin decorators for qp-vault.

Use these to register custom plugins:

    from qp_vault.plugins import embedder, parser, policy

    @embedder("my-model")
    class MyEmbedder:
        dimensions = 768
        async def embed(self, texts):
            return my_model.encode(texts)

    @parser("dicom")
    class DicomParser:
        supported_extensions = {".dcm"}
        async def parse(self, path):
            return ParseResult(text=extract(path))

    @policy("itar")
    class ItarPolicy:
        async def evaluate(self, resource, action, context):
            return PolicyResult(allowed=True)
"""

from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


def embedder(name: str) -> Any:
    """Decorator to register an embedding provider plugin.

    Args:
        name: Unique name for this embedder (e.g., "nomic-embed", "openai").
    """
    def decorator(cls: type[T]) -> type[T]:
        setattr(cls, "_qp_vault_plugin_type", "embedder")  # noqa: B010
        setattr(cls, "_qp_vault_plugin_name", name)  # noqa: B010
        return cls
    return decorator


def parser(name: str) -> Any:
    """Decorator to register a file parser plugin.

    Args:
        name: Unique name for this parser (e.g., "dicom", "cad").
    """
    def decorator(cls: type[T]) -> type[T]:
        setattr(cls, "_qp_vault_plugin_type", "parser")  # noqa: B010
        setattr(cls, "_qp_vault_plugin_name", name)  # noqa: B010
        return cls
    return decorator


def policy(name: str) -> Any:
    """Decorator to register a governance policy plugin.

    Args:
        name: Unique name for this policy (e.g., "itar", "hipaa").
    """
    def decorator(cls: type[T]) -> type[T]:
        setattr(cls, "_qp_vault_plugin_type", "policy")  # noqa: B010
        setattr(cls, "_qp_vault_plugin_name", name)  # noqa: B010
        return cls
    return decorator

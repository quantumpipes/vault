# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""
Vault: Governed knowledge store for autonomous organizations.

Every fact has provenance. Every read is verified. Every write is auditable.
Content-addressed storage, trust tiers, knowledge lifecycle, Merkle verification.

    pip install qp-vault                # SQLite, basic search, trust tiers
    pip install qp-vault[postgres]      # + PostgreSQL + pgvector hybrid search
    pip install qp-vault[docling]       # + 25+ format document processing
    pip install qp-vault[capsule]       # + Cryptographic audit trail (qp-capsule)
    pip install qp-vault[encryption]    # + AES-256-GCM + ML-KEM-768
    pip install qp-vault[all]          # Everything

Quick start:

    from qp_vault import Vault

    vault = Vault("./my-knowledge")
    vault.add("quarterly-report.pdf", trust="canonical")
    results = vault.search("Q3 revenue projections")
    print(results[0].content, results[0].trust_tier)

Docs: https://github.com/quantumpipes/vault
"""

__version__ = "0.5.0"
__author__ = "Quantum Pipes Technologies, LLC"
__license__ = "Apache-2.0"

from qp_vault.enums import (
    DataClassification,
    EventType,
    Lifecycle,
    MemoryLayer,
    ResourceStatus,
    ResourceType,
    TrustTier,
)
from qp_vault.exceptions import (
    ChunkingError,
    LifecycleError,
    ParsingError,
    PolicyError,
    StorageError,
    VaultError,
    VerificationError,
)
from qp_vault.models import (
    Chunk,
    Collection,
    HealthScore,
    MerkleProof,
    Resource,
    SearchResult,
    VaultEvent,
    VaultVerificationResult,
    VerificationResult,
)
from qp_vault.protocols import (
    AuditProvider,
    EmbeddingProvider,
    ParserProvider,
    PolicyProvider,
    StorageBackend,
)

__all__ = [
    # Version
    "__version__",
    # Main classes (lazy-loaded to avoid circular imports)
    "Vault",
    "AsyncVault",
    # Domain models
    "Resource",
    "Chunk",
    "Collection",
    "SearchResult",
    "HealthScore",
    "VerificationResult",
    "VaultVerificationResult",
    "MerkleProof",
    "VaultEvent",
    # Enums
    "TrustTier",
    "DataClassification",
    "ResourceType",
    "ResourceStatus",
    "Lifecycle",
    "MemoryLayer",
    "EventType",
    # Protocols (for implementors)
    "StorageBackend",
    "EmbeddingProvider",
    "AuditProvider",
    "ParserProvider",
    "PolicyProvider",
    # Exceptions
    "VaultError",
    "StorageError",
    "VerificationError",
    "LifecycleError",
    "PolicyError",
    "ChunkingError",
    "ParsingError",
]


def __getattr__(name: str) -> type:
    """Lazy import for Vault and AsyncVault to avoid circular imports."""
    if name == "Vault":
        from qp_vault.vault import Vault
        return Vault
    if name == "AsyncVault":
        from qp_vault.vault import AsyncVault
        return AsyncVault
    raise AttributeError(f"module 'qp_vault' has no attribute {name!r}")

# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Capsule Protocol auditor for qp-vault.

Creates a cryptographically sealed Capsule for each VaultEvent
using the typed Section API from qp-capsule.

Requires: pip install qp-vault[capsule]
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qp_vault.models import VaultEvent

try:
    from qp_capsule import (
        Capsule,
        CapsuleType,
        ContextSection,
        ExecutionSection,
        OutcomeSection,
        Seal,
        TriggerSection,
    )
    HAS_CAPSULE = True
except ImportError:
    HAS_CAPSULE = False


class CapsuleAuditor:
    """Audit provider that creates Capsule records for vault operations.

    Uses qp-capsule's typed Section objects (TriggerSection, ContextSection,
    ExecutionSection, OutcomeSection) for proper serialization and sealing.

    Requires qp-capsule >= 1.5 to be installed.
    """

    def __init__(self, chain: Any = None, signing_key: Any = None) -> None:
        """Initialize the Capsule auditor.

        Args:
            chain: A CapsuleChain instance for hash-chaining. Optional.
            signing_key: Ed25519 signing key for sealing. Optional.
        """
        if not HAS_CAPSULE:
            raise ImportError(
                "qp-capsule is required for CapsuleAuditor. "
                "Install with: pip install qp-vault[capsule]"
            )
        self._chain = chain
        self._signing_key = signing_key
        self._seal = Seal() if signing_key is None else Seal(signing_key)

    async def record(self, event: VaultEvent) -> str:
        """Record a vault event as a sealed Capsule.

        Returns:
            Capsule ID string.
        """
        event_type_val = (
            event.event_type.value
            if hasattr(event.event_type, "value")
            else str(event.event_type)
        )

        capsule = Capsule(
            type=CapsuleType.VAULT if hasattr(CapsuleType, "VAULT") else CapsuleType.GENERAL,
            trigger=TriggerSection(
                type="vault_operation",
                source=f"qp-vault/{event_type_val}",
                request=f"{event_type_val} {event.resource_name}",
            ),
            context=ContextSection(
                agent_id="qp-vault",
                environment={
                    "resource_id": event.resource_id,
                    "resource_hash": event.resource_hash,
                    "actor": event.actor or "system",
                },
            ),
            execution=ExecutionSection(
                tool_calls=[],
            ),
            outcome=OutcomeSection(
                status="success",
                summary=f"Vault {event_type_val}: {event.resource_name}",
            ),
        )

        # Seal the capsule
        self._seal.seal(capsule)

        # Add to chain if available
        if self._chain:
            await self._chain.seal_and_store(capsule, self._seal)

        return str(capsule.id) if hasattr(capsule, "id") else event.resource_id

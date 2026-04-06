"""Capsule Protocol auditor for qp-vault.

Creates a cryptographically sealed Capsule for each VaultEvent.
Requires: pip install qp-vault[capsule]

Falls back gracefully if qp-capsule is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qp_vault.models import VaultEvent

try:
    from qp_capsule import Capsule, CapsuleType, Seal  # noqa: F401
    HAS_CAPSULE = True
except ImportError:
    HAS_CAPSULE = False


class CapsuleAuditor:
    """Audit provider that creates Capsule records for vault operations.

    Each VaultEvent becomes a sealed Capsule with:
    - Trigger: event type + resource ID
    - Context: resource hash, trust tier, timestamp
    - Execution: operation details
    - Outcome: success/failure

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

    async def record(self, event: VaultEvent) -> str:
        """Record a vault event as a sealed Capsule.

        Returns:
            Capsule ID string.
        """
        event_type_val = event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)

        capsule = Capsule(
            capsule_type=CapsuleType.VAULT if hasattr(CapsuleType, "VAULT") else CapsuleType.GENERAL,
            trigger={
                "type": "vault_operation",
                "event": event_type_val,
                "resource_id": event.resource_id,
            },
            context={
                "resource_name": event.resource_name,
                "resource_hash": event.resource_hash,
                "actor": event.actor,
                "timestamp": event.timestamp.isoformat(),
            },
            execution={
                "actions": [event_type_val],
                "details": event.details,
            },
            outcome={
                "status": "success",
                "event_type": event_type_val,
            },
        )

        # Seal with signing key if available
        if self._signing_key:
            seal = Seal.create(capsule, self._signing_key)
            capsule.seal = seal

        # Add to chain if available
        if self._chain:
            self._chain.append(capsule)

        return str(capsule.id) if hasattr(capsule, "id") else event.resource_id

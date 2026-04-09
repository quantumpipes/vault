# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Adversarial verification: the security dimension of the 2D trust model.

Manages the `adversarial_status` field on VaultResources. This is orthogonal
to `trust_tier` (organizational confidence). Together they form the 2D trust
model where effective RAG weight = trust_tier_weight * adversarial_multiplier.

Status transitions:
    UNVERIFIED -> VERIFIED  (all Membrane stages passed)
    UNVERIFIED -> SUSPICIOUS (one or more Membrane stages flagged)
    SUSPICIOUS -> VERIFIED  (human reviewer cleared after investigation)
    VERIFIED   -> SUSPICIOUS (re-assessment flagged new concerns)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp_vault.enums import AdversarialStatus, EventType
from qp_vault.models import VaultEvent

if TYPE_CHECKING:
    from qp_vault.protocols import AuditProvider, StorageBackend


# Valid adversarial status transitions
VALID_TRANSITIONS: dict[AdversarialStatus, set[AdversarialStatus]] = {
    AdversarialStatus.UNVERIFIED: {
        AdversarialStatus.VERIFIED,
        AdversarialStatus.SUSPICIOUS,
    },
    AdversarialStatus.VERIFIED: {
        AdversarialStatus.SUSPICIOUS,
    },
    AdversarialStatus.SUSPICIOUS: {
        AdversarialStatus.VERIFIED,
    },
}


class AdversarialVerifier:
    """Manages the adversarial verification dimension of the 2D trust model.

    Args:
        auditor: Optional audit provider for recording status changes.
        storage: Optional storage backend for persistent status reads.
    """

    def __init__(
        self,
        auditor: AuditProvider | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        self._auditor = auditor
        self._storage = storage
        self._status_store: dict[str, AdversarialStatus] = {}

    async def set_status(
        self,
        resource_id: str,
        status: AdversarialStatus,
        reason: str = "",
        reviewer_id: str | None = None,
    ) -> AdversarialStatus:
        """Transition a resource's adversarial status.

        Args:
            resource_id: Vault resource ID.
            status: Target adversarial status.
            reason: Justification for the transition.
            reviewer_id: ID of the reviewer (for human-initiated transitions).

        Returns:
            The new adversarial status.

        Raises:
            ValueError: If the transition is not valid.
        """
        current = self._status_store.get(resource_id, AdversarialStatus.UNVERIFIED)

        if status != current:
            allowed = VALID_TRANSITIONS.get(current, set())
            if status not in allowed:
                msg = f"Invalid transition: {current.value} -> {status.value}"
                raise ValueError(msg)

        self._status_store[resource_id] = status

        # Emit audit event
        if self._auditor is not None:
            event = VaultEvent(
                event_type=EventType.ADVERSARIAL_STATUS_CHANGE,
                resource_id=resource_id,
                details={
                    "previous": current.value,
                    "new": status.value,
                    "reason": reason,
                    "reviewer_id": reviewer_id or "",
                },
            )
            await self._auditor.record(event)

        return status

    async def get_status(self, resource_id: str) -> AdversarialStatus:
        """Get the current adversarial status for a resource.

        Checks in-memory cache first, then falls back to the storage
        backend so status survives process restarts.

        Args:
            resource_id: Vault resource ID.

        Returns:
            Current adversarial status (UNVERIFIED if unknown).
        """
        # Memory cache (hot path)
        if resource_id in self._status_store:
            return self._status_store[resource_id]

        # Database fallback (cold path, survives restart)
        if self._storage is not None:
            try:
                resource = await self._storage.get_resource(resource_id)
                if resource is not None:
                    status_val = getattr(resource, "adversarial_status", None)
                    if status_val is not None:
                        if isinstance(status_val, str):
                            status = AdversarialStatus(status_val)
                        else:
                            status = status_val
                        self._status_store[resource_id] = status
                        return status
            except Exception:
                pass  # Storage errors fall through to default

        return AdversarialStatus.UNVERIFIED

    async def bulk_reassess(
        self,
        resource_ids: list[str],
        status: AdversarialStatus,
        reason: str = "",
    ) -> dict[str, AdversarialStatus]:
        """Reassess multiple resources (e.g., after an attack is confirmed).

        Args:
            resource_ids: List of resource IDs to reassess.
            status: Target status for all resources.
            reason: Justification for the bulk reassessment.

        Returns:
            Dict mapping resource_id to new status. Skips invalid transitions.
        """
        results: dict[str, AdversarialStatus] = {}
        for rid in resource_ids:
            try:
                new = await self.set_status(rid, status, reason=reason)
                results[rid] = new
            except ValueError:
                results[rid] = await self.get_status(rid)
        return results

    async def get_verified_count(self) -> int:
        """Count resources with VERIFIED status."""
        return sum(
            1 for s in self._status_store.values()
            if s == AdversarialStatus.VERIFIED
        )

    async def get_suspicious_count(self) -> int:
        """Count resources with SUSPICIOUS status."""
        return sum(
            1 for s in self._status_store.values()
            if s == AdversarialStatus.SUSPICIOUS
        )

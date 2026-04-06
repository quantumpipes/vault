"""Knowledge lifecycle state machine for qp-vault.

Manages lifecycle transitions with validation:
    DRAFT -> REVIEW -> ACTIVE -> SUPERSEDED -> ARCHIVED
                         |
                      EXPIRED (auto when valid_until passes)

Every transition emits a VaultEvent for audit.
"""

from __future__ import annotations

from datetime import date

from qp_vault.enums import EventType, Lifecycle
from qp_vault.exceptions import LifecycleError, VaultError
from qp_vault.models import Resource, VaultEvent
from qp_vault.protocols import AuditProvider, ResourceUpdate, StorageBackend

# Valid state transitions
VALID_TRANSITIONS: dict[Lifecycle, set[Lifecycle]] = {
    Lifecycle.DRAFT: {Lifecycle.REVIEW, Lifecycle.ACTIVE, Lifecycle.ARCHIVED},
    Lifecycle.REVIEW: {Lifecycle.ACTIVE, Lifecycle.DRAFT, Lifecycle.ARCHIVED},
    Lifecycle.ACTIVE: {Lifecycle.SUPERSEDED, Lifecycle.EXPIRED, Lifecycle.ARCHIVED},
    Lifecycle.SUPERSEDED: {Lifecycle.ARCHIVED},
    Lifecycle.EXPIRED: {Lifecycle.ACTIVE, Lifecycle.ARCHIVED},
    Lifecycle.ARCHIVED: set(),  # Terminal
}


class LifecycleEngine:
    """Manages knowledge lifecycle transitions."""

    def __init__(
        self,
        storage: StorageBackend,
        auditor: AuditProvider | None = None,
    ) -> None:
        self._storage = storage
        self._auditor = auditor

    async def transition(
        self,
        resource_id: str,
        target: Lifecycle | str,
        *,
        reason: str | None = None,
    ) -> Resource:
        """Transition a resource to a new lifecycle state.

        Args:
            resource_id: The resource to transition.
            target: Target lifecycle state.
            reason: Optional reason for the transition.

        Raises:
            LifecycleError: If the transition is not valid.
            VaultError: If the resource is not found.
        """
        resource = await self._storage.get_resource(resource_id)
        if resource is None:
            raise VaultError(f"Resource {resource_id} not found")

        target_lc = Lifecycle(target) if isinstance(target, str) else target
        current_lc = Lifecycle(resource.lifecycle) if isinstance(resource.lifecycle, str) else resource.lifecycle

        # Validate transition
        allowed = VALID_TRANSITIONS.get(current_lc, set())
        if target_lc not in allowed:
            raise LifecycleError(
                f"Cannot transition from {current_lc.value} to {target_lc.value}. "
                f"Allowed: {', '.join(s.value for s in allowed) or 'none (terminal state)'}"
            )

        # Apply transition
        updated = await self._storage.update_resource(
            resource_id,
            ResourceUpdate(lifecycle=target_lc.value),
        )

        # Audit
        if self._auditor:
            event = VaultEvent(
                event_type=EventType.LIFECYCLE_TRANSITION,
                resource_id=resource_id,
                resource_name=resource.name,
                resource_hash=resource.content_hash,
                details={
                    "from": current_lc.value,
                    "to": target_lc.value,
                    "reason": reason,
                },
            )
            await self._auditor.record(event)

        return updated

    async def supersede(
        self,
        old_id: str,
        new_id: str,
    ) -> tuple[Resource, Resource]:
        """Mark a resource as superseded by a newer version.

        The old resource transitions to SUPERSEDED with a superseded_by pointer.
        The new resource gets a supersedes pointer to the old one.

        Args:
            old_id: Resource being superseded.
            new_id: Resource that supersedes it.

        Returns:
            Tuple of (old_resource, new_resource) after update.
        """
        old = await self._storage.get_resource(old_id)
        new = await self._storage.get_resource(new_id)
        if old is None:
            raise VaultError(f"Resource {old_id} not found")
        if new is None:
            raise VaultError(f"Resource {new_id} not found")

        # Transition old to SUPERSEDED
        old_updated = await self.transition(old_id, Lifecycle.SUPERSEDED, reason=f"Superseded by {new_id}")

        # Set pointers
        await self._storage.update_resource(old_id, ResourceUpdate(superseded_by=new_id))
        new_updated = await self._storage.update_resource(new_id, ResourceUpdate(supersedes=old_id))

        # Re-fetch old with superseded_by set
        old_final = await self._storage.get_resource(old_id)
        if old_final is None:
            old_final = old_updated

        if self._auditor:
            event = VaultEvent(
                event_type=EventType.SUPERSEDE,
                resource_id=old_id,
                resource_name=old.name,
                resource_hash=old.content_hash,
                details={"superseded_by": new_id, "new_resource_name": new.name},
            )
            await self._auditor.record(event)

        return old_final, new_updated

    async def check_expirations(self) -> list[Resource]:
        """Find ACTIVE resources past their valid_until date and auto-expire them.

        Returns:
            List of resources that were transitioned to EXPIRED.
        """
        from qp_vault.protocols import ResourceFilter

        all_active = await self._storage.list_resources(
            ResourceFilter(lifecycle=Lifecycle.ACTIVE.value, limit=10000)
        )

        today = date.today()
        expired: list[Resource] = []

        for resource in all_active:
            if resource.valid_until and str(resource.valid_until) <= str(today):
                try:
                    updated = await self.transition(
                        resource.id,
                        Lifecycle.EXPIRED,
                        reason=f"valid_until ({resource.valid_until}) has passed",
                    )
                    expired.append(updated)
                except LifecycleError:
                    pass  # Already in a state that can't transition to EXPIRED

        return expired

    async def expiring(self, *, days: int = 90) -> list[Resource]:
        """Find resources expiring within the given number of days.

        Args:
            days: Look-ahead window in days.

        Returns:
            Resources with valid_until within the window.
        """
        from qp_vault.protocols import ResourceFilter

        all_active = await self._storage.list_resources(
            ResourceFilter(lifecycle=Lifecycle.ACTIVE.value, limit=10000)
        )

        today = date.today()
        cutoff = date.fromordinal(today.toordinal() + days)
        expiring_resources: list[Resource] = []

        for resource in all_active:
            if resource.valid_until:
                valid_until = resource.valid_until
                if isinstance(valid_until, str):
                    valid_until = date.fromisoformat(valid_until)
                if today <= valid_until <= cutoff:
                    expiring_resources.append(resource)

        return expiring_resources

    async def chain(self, resource_id: str, *, max_length: int = 1000) -> list[Resource]:
        """Get the full supersession chain for a resource.

        Walks both directions: predecessors (via supersedes) and
        successors (via superseded_by). Returns in chronological order.

        Args:
            resource_id: Any resource in the chain.
            max_length: Safety limit to prevent cycles (default 1000).

        Returns:
            Full chain from oldest to newest.

        Raises:
            VaultError: If chain exceeds max_length (likely cycle).
        """
        visited: set[str] = set()
        chain_resources: list[Resource] = []

        # Walk backwards to find the oldest
        current_id: str | None = resource_id
        while current_id and current_id not in visited:
            if len(visited) > max_length:
                raise VaultError(f"Supersession chain exceeds {max_length} (possible cycle)")
            visited.add(current_id)
            resource = await self._storage.get_resource(current_id)
            if resource is None:
                break
            chain_resources.insert(0, resource)
            current_id = resource.supersedes

        # Walk forwards from the starting resource
        resource = await self._storage.get_resource(resource_id)
        if resource and resource.superseded_by:
            current_id = resource.superseded_by
            while current_id and current_id not in visited:
                if len(visited) > max_length:
                    raise VaultError(f"Supersession chain exceeds {max_length} (possible cycle)")
                visited.add(current_id)
                resource = await self._storage.get_resource(current_id)
                if resource is None:
                    break
                chain_resources.append(resource)
                current_id = resource.superseded_by

        return chain_resources

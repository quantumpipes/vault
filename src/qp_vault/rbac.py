# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Role-Based Access Control (RBAC) for qp-vault.

Defines three roles with escalating permissions:
- READER: search, get, list, verify, health, status
- WRITER: all reader ops + add, update, delete, replace, transition, supersede
- ADMIN: all writer ops + export, import, config, create_collection

Enforcement is at the Vault API boundary. Storage backends are not
role-aware; RBAC is enforced before operations reach storage.
"""

from __future__ import annotations

from enum import StrEnum

from qp_vault.exceptions import VaultError


class Role(StrEnum):
    """Vault access roles."""

    READER = "reader"
    """Search, get, list, verify, health, status."""

    WRITER = "writer"
    """All reader ops + add, update, delete, replace, transition, supersede."""

    ADMIN = "admin"
    """All writer ops + export, import, config, create_collection."""


# Permission matrix: operation -> minimum required role
PERMISSIONS: dict[str, Role] = {
    # Reader operations
    "search": Role.READER,
    "get": Role.READER,
    "get_content": Role.READER,
    "list": Role.READER,
    "verify": Role.READER,
    "health": Role.READER,
    "status": Role.READER,
    "get_provenance": Role.READER,
    "chain": Role.READER,
    "expiring": Role.READER,
    "list_collections": Role.READER,
    "search_with_facets": Role.READER,
    # Writer operations
    "add": Role.WRITER,
    "add_batch": Role.WRITER,
    "update": Role.WRITER,
    "delete": Role.WRITER,
    "replace": Role.WRITER,
    "transition": Role.WRITER,
    "supersede": Role.WRITER,
    "set_adversarial_status": Role.WRITER,
    # Admin operations
    "export_vault": Role.ADMIN,
    "import_vault": Role.ADMIN,
    "create_collection": Role.ADMIN,
    "export_proof": Role.ADMIN,
}

# Role hierarchy: higher roles include all lower permissions
ROLE_HIERARCHY: dict[Role, int] = {
    Role.READER: 1,
    Role.WRITER: 2,
    Role.ADMIN: 3,
}


def check_permission(
    role: Role | str | None, operation: str, *, strict: bool = False
) -> None:
    """Check if a role has permission for an operation.

    Args:
        role: The caller's role. When ``strict`` is False, ``None`` means no RBAC
            is configured and all operations are allowed (library/in-process use).
            When ``strict`` is True (the API boundary), ``None`` is denied.
        operation: The operation name (e.g., "add", "search").
        strict: Fail-closed mode for untrusted callers (the REST boundary). When
            True, an unknown ``role`` (None) is denied and an operation that is
            not present in ``PERMISSIONS`` is denied (default-deny) rather than
            allowed. Defaults to False to preserve the in-process contract where
            ``check_permission(None, ...)`` is a no-op.

    Raises:
        VaultError: If the role is missing/unknown (strict) or lacks permission,
            or if the operation is unknown (strict).
    """
    if role is None:
        if strict:
            # Fail closed at the trust boundary: no identity => no access.
            raise VaultError(f"Permission denied: {operation} requires an authenticated role")
        return  # No RBAC configured (in-process default)

    # An unrecognized role string raises ValueError (denied either way).
    role_enum = Role(role) if isinstance(role, str) else role

    required = PERMISSIONS.get(operation)

    if required is None:
        if strict:
            # Default-deny: an operation not in the matrix is not authorizable.
            raise VaultError(f"Permission denied: unknown operation {operation}")
        return  # Unknown operation, allow by default (in-process default)

    caller_level = ROLE_HIERARCHY.get(role_enum, 0)
    required_level = ROLE_HIERARCHY.get(required, 0)

    if caller_level < required_level:
        raise VaultError(
            f"Permission denied: {operation} requires {required.value} role "
            f"(current: {role_enum.value})"
        )

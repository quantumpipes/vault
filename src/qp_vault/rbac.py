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


def check_permission(role: Role | str | None, operation: str) -> None:
    """Check if a role has permission for an operation.

    Args:
        role: The caller's role. None means no RBAC (all operations allowed).
        operation: The operation name (e.g., "add", "search").

    Raises:
        VaultError: If the role lacks permission.
    """
    if role is None:
        return  # No RBAC configured

    role_enum = Role(role) if isinstance(role, str) else role
    required = PERMISSIONS.get(operation)

    if required is None:
        return  # Unknown operation, allow by default

    caller_level = ROLE_HIERARCHY.get(role_enum, 0)
    required_level = ROLE_HIERARCHY.get(required, 0)

    if caller_level < required_level:
        raise VaultError(
            f"Permission denied: {operation} requires {required.value} role "
            f"(current: {role_enum.value})"
        )

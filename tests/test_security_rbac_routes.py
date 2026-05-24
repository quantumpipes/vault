# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Security tests for the vault REST boundary (C1 + C2).

Covers:
- check_permission strict (fail-closed) mode: None role and unknown operation deny.
- create_vault_router refuses to build unauthenticated (require_auth default).
- Per-operation RBAC enforced at the boundary (reader cannot write).
- import/export disabled without io_base_dir, and path-escape rejected.
"""

from __future__ import annotations

import pytest

from qp_vault import AsyncVault
from qp_vault.rbac import Role, check_permission

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from qp_vault.integrations.fastapi_routes import create_vault_router

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


# --- check_permission strict mode ---------------------------------------------

def test_strict_none_role_denied() -> None:
    from qp_vault.exceptions import VaultError

    # Non-strict: None is a no-op (in-process default).
    check_permission(None, "search")
    # Strict: None has no identity and is denied.
    with pytest.raises(VaultError):
        check_permission(None, "search", strict=True)


def test_strict_unknown_operation_denied() -> None:
    from qp_vault.exceptions import VaultError

    # Non-strict: unknown operation allowed (in-process default).
    check_permission(Role.ADMIN, "totally_unknown_op")
    # Strict: unknown operation default-denied.
    with pytest.raises(VaultError):
        check_permission(Role.ADMIN, "totally_unknown_op", strict=True)


def test_reader_denied_write_operation() -> None:
    from qp_vault.exceptions import VaultError

    with pytest.raises(VaultError):
        check_permission(Role.READER, "add", strict=True)
    # Reader allowed read operation.
    check_permission(Role.READER, "search", strict=True)


# --- router contract ----------------------------------------------------------

@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_router_refuses_unauthenticated(tmp_path) -> None:
    vault = AsyncVault(tmp_path / "v")
    with pytest.raises(ValueError):
        create_vault_router(vault)


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_boundary_rbac_reader_blocked_from_write(tmp_path) -> None:
    vault = AsyncVault(tmp_path / "v")

    async def reader_role() -> Role:
        return Role.READER

    app = FastAPI()
    app.include_router(
        create_vault_router(vault, role_resolver=reader_role), prefix="/v1/vault"
    )
    client = TestClient(app)

    # Reader can search.
    assert client.post("/v1/vault/search", json={"query": "x"}).status_code == 200
    # Reader cannot add (write) -> 403 at the boundary.
    resp = client.post("/v1/vault/resources", json={"content": "hello"})
    assert resp.status_code == 403


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_import_export_disabled_without_base_dir(tmp_path) -> None:
    vault = AsyncVault(tmp_path / "v")
    app = FastAPI()
    app.include_router(
        create_vault_router(vault, require_auth=False), prefix="/v1/vault"
    )
    client = TestClient(app)

    assert client.post("/v1/vault/import", json={"path": "x.json"}).status_code == 403
    assert client.get("/v1/vault/export").status_code == 403


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_import_path_escape_rejected(tmp_path) -> None:
    vault = AsyncVault(tmp_path / "v")
    base = tmp_path / "v"
    app = FastAPI()
    app.include_router(
        create_vault_router(vault, require_auth=False, io_base_dir=str(base)),
        prefix="/v1/vault",
    )
    client = TestClient(app)

    # Traversal and absolute escape both rejected with 400.
    assert client.post("/v1/vault/import", json={"path": "../../../etc/passwd"}).status_code == 400
    assert client.post("/v1/vault/import", json={"path": "/etc/passwd"}).status_code == 400

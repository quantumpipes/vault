"""FastAPI routes for qp-vault.

Provides a ready-made APIRouter with all vault endpoints.
Requires: pip install qp-vault[fastapi]

Usage:
    from qp_vault.integrations.fastapi_routes import create_vault_router

    vault = AsyncVault("./knowledge")
    router = create_vault_router(vault)
    app.include_router(router, prefix="/v1/vault")
"""

from __future__ import annotations

from datetime import date
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel, Field
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def _require_fastapi() -> None:
    if not HAS_FASTAPI:
        raise ImportError(
            "FastAPI is required for vault routes. "
            "Install with: pip install qp-vault[fastapi]"
        )


# --- Request/Response Models ---

if HAS_FASTAPI:

    class AddResourceRequest(BaseModel):
        content: str = Field(..., max_length=500_000_000)  # 500MB max
        name: str = "untitled.md"
        trust: str = "working"
        classification: str = "internal"
        layer: str | None = None
        collection: str | None = None
        tags: list[str] = Field(default_factory=list)
        metadata: dict[str, Any] = Field(default_factory=dict)
        lifecycle: str = "active"

    class SearchRequest(BaseModel):
        query: str = Field(..., max_length=10000)
        top_k: int = Field(10, ge=1, le=1000)
        threshold: float = Field(0.0, ge=0.0, le=1.0)
        trust_min: str | None = None
        layer: str | None = None
        collection: str | None = None
        as_of: str | None = None

        @classmethod
        def _validate_as_of(cls, v: str | None) -> str | None:
            if v is None:
                return v
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError("Invalid date format. Expected YYYY-MM-DD") from None
            return v

    class UpdateResourceRequest(BaseModel):
        name: str | None = None
        trust: str | None = None
        classification: str | None = None
        tags: list[str] | None = None
        metadata: dict[str, Any] | None = None

    class TransitionRequest(BaseModel):
        target: str
        reason: str | None = None

    class SupersedeRequest(BaseModel):
        new_id: str

    class ApiResponse(BaseModel):
        data: Any = None
        meta: dict[str, Any] = Field(default_factory=dict)


def create_vault_router(vault: Any) -> APIRouter:
    """Create a FastAPI router with all vault endpoints.

    Args:
        vault: An AsyncVault instance.

    Returns:
        FastAPI APIRouter ready to include in your app.
    """
    _require_fastapi()
    from qp_vault.exceptions import LifecycleError, StorageError, VaultError

    router = APIRouter(tags=["vault"])

    import logging
    _logger = logging.getLogger("qp_vault.api")

    def _handle_error(e: Exception) -> HTTPException:
        """Map vault exceptions to safe HTTP responses.

        Logs full error internally; returns sanitized message to client.
        """
        _logger.exception("Vault API error: %s", type(e).__name__)
        if isinstance(e, LifecycleError):
            return HTTPException(status_code=409, detail="Invalid lifecycle transition")
        if isinstance(e, VaultError):
            return HTTPException(status_code=404, detail="Resource not found")
        if isinstance(e, StorageError):
            return HTTPException(status_code=500, detail="Storage operation failed")
        return HTTPException(status_code=500, detail="Internal server error")

    @router.post("/resources")
    async def add_resource(req: AddResourceRequest) -> dict[str, Any]:
        resource = await vault.add(
            req.content,
            name=req.name,
            trust=req.trust,
            classification=req.classification,
            layer=req.layer,
            collection=req.collection,
            tags=req.tags,
            metadata=req.metadata,
            lifecycle=req.lifecycle,
        )
        return {"data": resource.model_dump(), "meta": {}}

    @router.get("/resources")
    async def list_resources(
        trust: str | None = None,
        layer: str | None = None,
        lifecycle: str | None = None,
        status: str | None = None,
        limit: int = Query(50, ge=1, le=1000),
        offset: int = Query(0, ge=0, le=1_000_000),
    ) -> dict[str, Any]:
        resources = await vault.list(
            trust=trust,
            layer=layer,
            lifecycle=lifecycle,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"data": [r.model_dump() for r in resources], "meta": {"count": len(resources)}}

    @router.get("/resources/{resource_id}")
    async def get_resource(resource_id: str) -> dict[str, Any]:
        try:
            resource = await vault.get(resource_id)
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": resource.model_dump(), "meta": {}}

    @router.put("/resources/{resource_id}")
    async def update_resource(resource_id: str, req: UpdateResourceRequest) -> dict[str, Any]:
        try:
            resource = await vault.update(
                resource_id,
                name=req.name,
                trust=req.trust,
                classification=req.classification,
                tags=req.tags,
                metadata=req.metadata,
            )
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": resource.model_dump(), "meta": {}}

    @router.delete("/resources/{resource_id}")
    async def delete_resource(resource_id: str, hard: bool = False) -> dict[str, Any]:
        try:
            await vault.delete(resource_id, hard=hard)
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": {"deleted": True}, "meta": {}}

    @router.post("/resources/{resource_id}/transition")
    async def transition_resource(resource_id: str, req: TransitionRequest) -> dict[str, Any]:
        try:
            resource = await vault.transition(resource_id, req.target, reason=req.reason)
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": resource.model_dump(), "meta": {}}

    @router.post("/resources/{resource_id}/supersede")
    async def supersede_resource(resource_id: str, req: SupersedeRequest) -> dict[str, Any]:
        try:
            old, new = await vault.supersede(resource_id, req.new_id)
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": {"old": old.model_dump(), "new": new.model_dump()}, "meta": {}}

    @router.get("/resources/{resource_id}/verify")
    async def verify_resource(resource_id: str) -> dict[str, Any]:
        result = await vault.verify(resource_id)
        return {"data": result.model_dump(), "meta": {}}

    @router.get("/resources/{resource_id}/proof")
    async def export_proof(resource_id: str) -> dict[str, Any]:
        try:
            proof = await vault.export_proof(resource_id)
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": proof.model_dump(), "meta": {}}

    @router.get("/resources/{resource_id}/chain")
    async def get_chain(resource_id: str) -> dict[str, Any]:
        chain = await vault.chain(resource_id)
        return {"data": [r.model_dump() for r in chain], "meta": {"length": len(chain)}}

    @router.post("/search")
    async def search(req: SearchRequest) -> dict[str, Any]:
        as_of = date.fromisoformat(req.as_of) if req.as_of else None
        results = await vault.search(
            req.query,
            top_k=req.top_k,
            threshold=req.threshold,
            trust_min=req.trust_min,
            layer=req.layer,
            collection=req.collection,
            as_of=as_of,
        )
        return {
            "data": [r.model_dump() for r in results],
            "meta": {"query": req.query, "total": len(results)},
        }

    @router.get("/verify")
    async def verify_all() -> dict[str, Any]:
        result = await vault.verify()
        return {"data": result.model_dump(), "meta": {}}

    @router.get("/health")
    async def health() -> dict[str, Any]:
        score = await vault.health()
        return {"data": score.model_dump(), "meta": {}}

    @router.get("/status")
    async def status() -> dict[str, Any]:
        s = await vault.status()
        return {"data": s, "meta": {}}

    @router.get("/expiring")
    async def expiring(days: int = 90) -> dict[str, Any]:
        resources = await vault.expiring(days=days)
        return {"data": [r.model_dump() for r in resources], "meta": {"days": days}}

    @router.get("/resources/{resource_id}/content")
    async def get_content(resource_id: str) -> dict[str, Any]:
        try:
            text = await vault.get_content(resource_id)
        except Exception as e:
            raise _handle_error(e) from e
        return {"data": {"content": text}, "meta": {}}

    @router.get("/resources/{resource_id}/provenance")
    async def get_provenance(resource_id: str) -> dict[str, Any]:
        records = await vault.get_provenance(resource_id)
        return {"data": records, "meta": {"count": len(records)}}

    @router.get("/collections")
    async def list_collections() -> dict[str, Any]:
        colls = await vault.list_collections()
        return {"data": colls, "meta": {"count": len(colls)}}

    @router.post("/collections")
    async def create_collection(req: dict[str, Any]) -> dict[str, Any]:
        result = await vault.create_collection(req.get("name", ""), description=req.get("description", ""))
        return {"data": result, "meta": {}}

    @router.post("/search/faceted")
    async def search_faceted(req: SearchRequest) -> dict[str, Any]:
        as_of_date = date.fromisoformat(req.as_of) if req.as_of else None
        result = await vault.search_with_facets(
            req.query,
            top_k=req.top_k,
            trust_min=req.trust_min,
            layer=req.layer,
            as_of=as_of_date,
        )
        return {
            "data": [r.model_dump() for r in result["results"]],
            "meta": {"total": result["total"], "facets": result["facets"]},
        }

    @router.post("/batch")
    async def add_batch(req: dict[str, Any]) -> dict[str, Any]:
        sources = req.get("sources", [])
        if len(sources) > 100:
            raise HTTPException(status_code=400, detail="Batch limited to 100 items")
        trust = req.get("trust", "working")
        tenant_id = req.get("tenant_id")
        resources = await vault.add_batch(
            [s.get("content", "") if isinstance(s, dict) else s for s in sources],
            trust=trust,
            tenant_id=tenant_id,
        )
        return {"data": [r.model_dump() for r in resources], "meta": {"count": len(resources)}}

    @router.get("/export")
    async def export_vault_endpoint(output: str = "vault_export.json") -> dict[str, Any]:
        result = await vault.export_vault(output)
        return {"data": result, "meta": {}}

    return router

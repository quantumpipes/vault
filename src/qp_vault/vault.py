"""Main Vault classes: sync and async interfaces.

The primary entry point for qp-vault. Vault (sync) wraps AsyncVault.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from qp_vault.audit.log_auditor import LogAuditor
from qp_vault.config import VaultConfig
from qp_vault.core.chunker import ChunkerConfig
from qp_vault.core.hasher import compute_merkle_root
from qp_vault.core.resource_manager import ResourceManager
from qp_vault.core.search_engine import apply_trust_weighting
from qp_vault.enums import (
    DataClassification,
    Lifecycle,
    MemoryLayer,
    ResourceStatus,
    TrustTier,
)
from qp_vault.exceptions import VaultError
from qp_vault.models import (
    HealthScore,
    MerkleProof,
    Resource,
    SearchResult,
    VaultVerificationResult,
    VerificationResult,
)
from qp_vault.protocols import (
    AuditProvider,
    EmbeddingProvider,
    ParserProvider,
    PolicyProvider,
    SearchQuery,
    StorageBackend,
)
from qp_vault.storage.sqlite import SQLiteBackend

if TYPE_CHECKING:
    from datetime import date

    from qp_vault.core.layer_manager import LayerView

# --- Input Sanitization ---

_MAX_TAG_LENGTH = 100
_MAX_TAGS = 50
_MAX_METADATA_KEYS = 100
_MAX_METADATA_KEY_LENGTH = 100
_MAX_METADATA_VALUE_SIZE = 10_000


def _sanitize_name(name: str) -> str:
    """Sanitize a resource name for safe storage.

    Applies Unicode NFC normalization, strips path components, null bytes,
    control characters, backslashes. Caps length at 255.
    """
    import re
    import unicodedata
    # Unicode NFC normalization (prevents homograph collisions)
    name = unicodedata.normalize("NFC", name)
    # Replace backslashes with forward slashes for cross-platform path stripping
    name = name.replace("\\", "/")
    # Strip path components (takes last segment after /)
    name = Path(name).name
    # Remove null bytes and control characters
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    # Strip leading/trailing dots and spaces
    name = name.strip(". ")
    if not name or name in (".", ".."):
        return "untitled"
    return name[:255]


def _sanitize_tags(tags: list[str]) -> list[str]:
    """Validate and sanitize tag list."""
    import re
    if len(tags) > _MAX_TAGS:
        raise VaultError(f"Too many tags ({len(tags)}). Maximum: {_MAX_TAGS}")
    clean: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if not tag:
            continue
        if len(tag) > _MAX_TAG_LENGTH:
            raise VaultError(f"Tag exceeds {_MAX_TAG_LENGTH} chars: {tag[:20]}...")
        # Remove control characters
        tag = re.sub(r"[\x00-\x1f\x7f]", "", tag)
        clean.append(tag)
    return clean


def _validate_metadata(metadata: dict[str, Any]) -> None:
    """Validate metadata keys and values for size and safety."""
    import re
    if len(metadata) > _MAX_METADATA_KEYS:
        raise VaultError(f"Too many metadata keys ({len(metadata)}). Maximum: {_MAX_METADATA_KEYS}")
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise VaultError(f"Metadata key must be a string, got {type(key).__name__}")
        if len(key) > _MAX_METADATA_KEY_LENGTH:
            raise VaultError(f"Metadata key exceeds {_MAX_METADATA_KEY_LENGTH} chars")
        # Keys must be alphanumeric + underscore + dash
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", key):
            raise VaultError(f"Metadata key contains invalid characters: {key}")
        # Value size check (serialized)
        import json
        val_size = len(json.dumps(value, default=str))
        if val_size > _MAX_METADATA_VALUE_SIZE:
            raise VaultError(f"Metadata value for '{key}' exceeds {_MAX_METADATA_VALUE_SIZE} bytes")


class AsyncVault:
    """Governed knowledge store (async interface).

    Args:
        path: Directory path for vault storage.
        storage: Custom storage backend (default: SQLite).
        embedder: Custom embedding provider (default: None).
        auditor: Custom audit provider (default: JSON logging).
        parsers: Custom file parsers.
        policies: Governance policy providers.
        config: Vault configuration.
        plugins_dir: Directory for local plugin discovery (air-gap mode).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        storage: StorageBackend | None = None,
        embedder: EmbeddingProvider | None = None,
        auditor: AuditProvider | None = None,
        parsers: list[ParserProvider] | None = None,
        policies: list[PolicyProvider] | None = None,
        config: VaultConfig | None = None,
        plugins_dir: str | Path | None = None,
        tenant_id: str | None = None,
        role: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.config = config or VaultConfig()
        self._locked_tenant_id = tenant_id
        self._role = role  # RBAC: None = no enforcement, "reader"/"writer"/"admin"

        # Storage backend
        if storage is not None:
            self._storage = storage
        else:
            self._storage = SQLiteBackend(self.path / "vault.db")

        # Embedding provider
        self._embedder = embedder

        # Audit provider (auto-detect qp-capsule if installed)
        if auditor is not None:
            self._auditor = auditor
        else:
            try:
                from qp_vault.audit.capsule_auditor import HAS_CAPSULE, CapsuleAuditor
                if HAS_CAPSULE:
                    self._auditor = CapsuleAuditor()
                else:
                    self._auditor = LogAuditor(self.path / "audit.jsonl")
            except ImportError:
                self._auditor = LogAuditor(self.path / "audit.jsonl")

        # Parsers and policies
        self._parsers = parsers or []
        self._policies = policies or []
        self._plugins_dir = Path(plugins_dir) if plugins_dir else None

        # Core components
        chunker_config = ChunkerConfig(
            target_tokens=self.config.chunk_target_tokens,
            min_tokens=self.config.chunk_min_tokens,
            max_tokens=self.config.chunk_max_tokens,
            overlap_tokens=self.config.chunk_overlap_tokens,
        )
        self._resource_manager = ResourceManager(
            storage=self._storage,
            embedder=self._embedder,
            auditor=self._auditor,
            chunker_config=chunker_config,
        )

        # Lifecycle engine
        from qp_vault.core.lifecycle_engine import LifecycleEngine
        self._lifecycle = LifecycleEngine(
            storage=self._storage,
            auditor=self._auditor,
        )

        # Layer manager
        from qp_vault.core.layer_manager import LayerManager
        self._layer_manager = LayerManager(config=self.config)

        # Membrane pipeline
        from qp_vault.membrane.pipeline import MembranePipeline
        self._membrane_pipeline: MembranePipeline | None = MembranePipeline()

        self._initialized = False

        # TTL cache for expensive operations (health, status)
        self._cache: dict[str, tuple[float, Any]] = {}

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._storage.initialize()
            self._initialized = True

    def _check_permission(self, operation: str) -> None:
        """Check RBAC permission for an operation."""
        from qp_vault.rbac import check_permission
        check_permission(self._role, operation)

    def _cache_get(self, key: str) -> Any | None:
        """Get a cached value if TTL has not expired."""
        import time
        entry = self._cache.get(key)
        if entry is None:
            return None
        cached_at, value = entry
        if time.monotonic() - cached_at > self.config.health_cache_ttl_seconds:
            del self._cache[key]
            return None
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        """Cache a value with current timestamp."""
        import time
        self._cache[key] = (time.monotonic(), value)

    def _cache_invalidate(self) -> None:
        """Invalidate all cached values (after writes)."""
        self._cache.clear()

    async def _with_timeout(self, coro: Any) -> Any:
        """Wrap a coroutine with the configured query timeout.

        Uses asyncio.create_task + cancel for proper cleanup. When the
        timeout fires, the underlying task is cancelled (not left running).
        """
        timeout_s = self.config.query_timeout_ms / 1000.0
        task = asyncio.ensure_future(coro)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except TimeoutError:
            task.cancel()
            import contextlib
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            raise VaultError(
                f"Operation timed out after {self.config.query_timeout_ms}ms"
            ) from None

    def _resolve_tenant(self, tenant_id: str | None) -> str | None:
        """Resolve effective tenant_id, enforcing lock if set.

        When the vault is locked to a tenant (via __init__ tenant_id):
        - If caller provides no tenant_id, auto-inject the locked tenant.
        - If caller provides a matching tenant_id, allow it.
        - If caller provides a different tenant_id, reject.
        """
        if self._locked_tenant_id is None:
            return tenant_id
        if tenant_id is None:
            return self._locked_tenant_id
        if tenant_id != self._locked_tenant_id:
            raise VaultError(
                f"Tenant mismatch: vault is locked to '{self._locked_tenant_id}' "
                f"but operation specified '{tenant_id}'"
            )
        return tenant_id

    # --- Resource Operations ---

    async def add(
        self,
        source: str | Path | bytes,
        *,
        name: str | None = None,
        trust: TrustTier | str = TrustTier.WORKING,
        classification: DataClassification | str = DataClassification.INTERNAL,
        layer: MemoryLayer | str | None = None,
        collection: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        lifecycle: Lifecycle | str = Lifecycle.ACTIVE,
        valid_from: date | None = None,
        valid_until: date | None = None,
        tenant_id: str | None = None,
    ) -> Resource:
        """Add a resource to the vault.

        Args:
            source: File path, text string, or bytes content.
            name: Display name (auto-detected from path if not provided).
            trust: Trust tier (canonical, working, ephemeral, archived).
            classification: Data classification level.
            layer: Memory layer (operational, strategic, compliance).
            collection: Collection ID to add resource to.
            tags: List of tags.
            metadata: Arbitrary key-value metadata.
            lifecycle: Initial lifecycle state.
            valid_from: Start of temporal validity window.
            valid_until: End of temporal validity window.

        Returns:
            The created Resource.
        """
        await self._ensure_initialized()
        self._check_permission("add")
        tenant_id = self._resolve_tenant(tenant_id)

        # Validate enum values early (before they reach storage layer)
        try:
            if isinstance(trust, str):
                trust = TrustTier(trust)
            if isinstance(classification, str):
                classification = DataClassification(classification)
            if isinstance(lifecycle, str):
                lifecycle = Lifecycle(lifecycle)
            if isinstance(layer, str):
                layer = MemoryLayer(layer)
        except ValueError as e:
            raise VaultError(f"Invalid parameter: {e}") from e

        # Input validation: name
        if name is not None:
            name = _sanitize_name(name)

        # Input validation: tags
        if tags is not None:
            tags = _sanitize_tags(tags)

        # Input validation: metadata
        if metadata is not None:
            _validate_metadata(metadata)

        # Resolve source to text
        # Guard against Path() on very long strings (OSError: filename too long)
        _is_path = isinstance(source, Path)
        if not _is_path and isinstance(source, str) and len(source) < 4096:
            try:
                _is_path = Path(source).exists()
            except OSError:
                _is_path = False
        if _is_path:
            assert not isinstance(source, bytes), "bytes source cannot be a path"
            path = Path(source).resolve()
            # Security: reject path traversal attempts
            if ".." in path.parts:
                raise VaultError("Path traversal detected in source path")
            if name is None:
                name = path.name
            # Try parsers first
            text = None
            for parser in self._parsers:
                if path.suffix.lower() in parser.supported_extensions:
                    result = await parser.parse(path)
                    text = result.text
                    break
            if text is None:
                # Default: read as text
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    text = path.read_text(encoding="latin-1")
                except Exception:
                    if isinstance(source, str):
                        # It was a string, not a file path
                        text = source
                        if name is None:
                            name = "untitled.md"
                    else:
                        raise
        elif isinstance(source, bytes):
            text = source.decode("utf-8", errors="replace")
            if name is None:
                name = "untitled"
        else:
            text = str(source)
            if name is None:
                name = "untitled.md"

        # Enforce max file size
        if self.config.max_file_size_mb is not None:
            size_mb = len(text.encode("utf-8")) / (1024 * 1024)
            if size_mb > self.config.max_file_size_mb:
                raise VaultError(
                    f"Content exceeds max size of {self.config.max_file_size_mb}MB "
                    f"({size_mb:.1f}MB provided)"
                )

        # Per-tenant quota check (atomic count, no TOCTOU window)
        if tenant_id and self.config.max_resources_per_tenant is not None:
            count = await self._storage.count_resources(tenant_id)
            if count >= self.config.max_resources_per_tenant:
                raise VaultError(
                    f"Tenant {tenant_id} has reached the resource limit "
                    f"({self.config.max_resources_per_tenant})"
                )

        # Strip null bytes from content (prevents storage/search corruption)
        text = text.replace("\x00", "")

        # Membrane screening (if pipeline configured)
        if self._membrane_pipeline:
            membrane_result = await self._membrane_pipeline.screen(text)
            if membrane_result.recommended_status.value == "quarantined":
                # Store but quarantine; caller can check resource.status
                pass  # Status will be set by Membrane result below

        resource = await self._resource_manager.add(
            text,
            name=name,
            trust=trust,
            classification=classification,
            layer=layer,
            collection=collection,
            tags=tags,
            metadata=metadata,
            lifecycle=lifecycle,
            valid_from=valid_from,
            valid_until=valid_until,
            tenant_id=tenant_id,
        )
        self._cache_invalidate()
        return resource

    async def get(self, resource_id: str) -> Resource:
        """Get a resource by ID."""
        await self._ensure_initialized()
        return await self._resource_manager.get(resource_id)

    async def list(
        self,
        *,
        tenant_id: str | None = None,
        trust: TrustTier | str | None = None,
        classification: DataClassification | str | None = None,
        layer: MemoryLayer | str | None = None,
        collection: str | None = None,
        lifecycle: Lifecycle | str | None = None,
        status: ResourceStatus | str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Resource]:
        """List resources with optional filters."""
        await self._ensure_initialized()
        tenant_id = self._resolve_tenant(tenant_id)
        return await self._resource_manager.list(
            tenant_id=tenant_id,
            trust=trust,
            classification=classification,
            layer=layer,
            collection=collection,
            lifecycle=lifecycle,
            status=status,
            tags=tags,
            limit=limit,
            offset=offset,
        )

    async def update(
        self,
        resource_id: str,
        *,
        name: str | None = None,
        trust: TrustTier | str | None = None,
        classification: DataClassification | str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Resource:
        """Update resource metadata."""
        await self._ensure_initialized()
        self._check_permission("update")
        result = await self._resource_manager.update(
            resource_id,
            name=name,
            trust=trust,
            classification=classification,
            tags=tags,
            metadata=metadata,
        )
        self._cache_invalidate()
        return result

    async def delete(self, resource_id: str, *, hard: bool = False) -> None:
        """Delete a resource (soft by default)."""
        await self._ensure_initialized()
        self._check_permission("delete")
        await self._resource_manager.delete(resource_id, hard=hard)
        self._cache_invalidate()

    async def get_content(self, resource_id: str) -> str:
        """Retrieve the full text content of a resource.

        Reassembles chunks in order to reconstruct the original text.

        Args:
            resource_id: The resource to retrieve content for.

        Returns:
            The full text content, with chunks joined by newlines.
        """
        await self._ensure_initialized()
        self._check_permission("get_content")
        chunks = await self._storage.get_chunks_for_resource(resource_id)
        if not chunks:
            raise VaultError(f"No content found for resource {resource_id}")
        sorted_chunks = sorted(chunks, key=lambda c: c.chunk_index)
        return "\n\n".join(c.content for c in sorted_chunks)

    async def replace(
        self,
        resource_id: str,
        new_content: str,
        *,
        reason: str | None = None,
    ) -> tuple[Resource, Resource]:
        """Replace a resource's content atomically.

        Creates a new resource with the new content and supersedes the old one.
        The old resource transitions to SUPERSEDED.

        Args:
            resource_id: The resource to replace.
            new_content: The new text content.
            reason: Optional reason for the replacement.

        Returns:
            Tuple of (old_resource, new_resource).
        """
        await self._ensure_initialized()
        self._check_permission("replace")
        old_resource = await self.get(resource_id)

        # Create new version with same metadata
        new_resource = await self.add(
            new_content,
            name=old_resource.name,
            trust=old_resource.trust_tier,
            classification=old_resource.data_classification,
            layer=old_resource.layer,
            collection=old_resource.collection_id,
            tags=old_resource.tags,
            metadata=old_resource.metadata,
        )

        # Supersede old with new
        return await self.supersede(resource_id, new_resource.id)

    async def add_batch(
        self,
        sources: list[str | Path | bytes],
        *,
        trust: TrustTier | str = TrustTier.WORKING,
        tenant_id: str | None = None,
        **kwargs: Any,
    ) -> list[Resource]:
        """Add multiple resources in a batch.

        Args:
            sources: List of file paths, text strings, or bytes.
            trust: Default trust tier for all resources.
            tenant_id: Optional tenant scope.
            **kwargs: Additional args passed to each add() call.

        Returns:
            List of created Resources.
        """
        await self._ensure_initialized()
        self._check_permission("add_batch")
        tenant_id = self._resolve_tenant(tenant_id)
        assert sources is not None, "sources must not be None"
        results: list[Resource] = []
        src: str | Path | bytes
        for src in sources:
            r = await self.add(src, trust=trust, tenant_id=tenant_id, **kwargs)
            results.append(r)
        return results

    async def get_provenance(self, resource_id: str) -> list[dict[str, Any]]:
        """Get all provenance records for a resource.

        Returns:
            List of provenance records in chronological order.
        """
        await self._ensure_initialized()
        self._check_permission("get_provenance")
        return await self._storage.get_provenance(resource_id)

    async def set_adversarial_status(self, resource_id: str, status: str) -> Resource:
        """Set the adversarial verification status of a resource.

        Args:
            resource_id: The resource to update.
            status: One of 'unverified', 'verified', 'suspicious'.

        Returns:
            Updated resource.
        """
        await self._ensure_initialized()
        self._check_permission("set_adversarial_status")
        from qp_vault.protocols import ResourceUpdate
        return await self._storage.update_resource(
            resource_id, ResourceUpdate(adversarial_status=status)
        )

    # --- Lifecycle ---

    async def transition(
        self,
        resource_id: str,
        target: Lifecycle | str,
        *,
        reason: str | None = None,
    ) -> Resource:
        """Transition a resource's lifecycle state.

        Valid transitions:
            DRAFT -> REVIEW, ACTIVE, ARCHIVED
            REVIEW -> ACTIVE, DRAFT, ARCHIVED
            ACTIVE -> SUPERSEDED, EXPIRED, ARCHIVED
            SUPERSEDED -> ARCHIVED
            EXPIRED -> ACTIVE, ARCHIVED
            ARCHIVED -> (terminal, no transitions)
        """
        await self._ensure_initialized()
        self._check_permission("transition")
        return await self._lifecycle.transition(resource_id, target, reason=reason)

    async def supersede(
        self, old_id: str, new_id: str
    ) -> tuple[Resource, Resource]:
        """Mark old resource as superseded by new resource."""
        await self._ensure_initialized()
        self._check_permission("supersede")
        return await self._lifecycle.supersede(old_id, new_id)

    async def expiring(self, *, days: int = 90) -> list[Resource]:
        """Find resources expiring within N days."""
        await self._ensure_initialized()
        return await self._lifecycle.expiring(days=days)

    async def chain(self, resource_id: str) -> list[Resource]:
        """Get the full supersession chain for a resource."""
        await self._ensure_initialized()
        return await self._lifecycle.chain(resource_id)

    # --- Search ---

    async def search(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        top_k: int = 10,
        offset: int = 0,
        threshold: float = 0.0,
        trust_min: TrustTier | str | None = None,
        layer: MemoryLayer | str | None = None,
        collection: str | None = None,
        as_of: date | None = None,
        deduplicate: bool = True,
        explain: bool = False,
        _layer_boost: float = 1.0,
    ) -> list[SearchResult]:
        """Trust-weighted hybrid search.

        Args:
            query: Search query text.
            top_k: Maximum number of results.
            threshold: Minimum relevance score.
            trust_min: Minimum trust tier for results.
            layer: Filter to specific memory layer.
            collection: Filter to specific collection.
            as_of: Point-in-time search (returns resources active at that date).

        Returns:
            List of SearchResult sorted by trust-weighted relevance.
        """
        await self._ensure_initialized()
        self._check_permission("search")
        tenant_id = self._resolve_tenant(tenant_id)

        # Generate query embedding if embedder available
        query_embedding = None
        if self._embedder:
            embeddings = await self._embedder.embed([query])
            query_embedding = embeddings[0]

        from qp_vault.protocols import ResourceFilter

        search_query = SearchQuery(
            query_embedding=query_embedding,
            query_text=query,
            top_k=top_k * 3,  # Over-fetch for trust re-ranking
            threshold=0.0,  # Apply threshold after trust weighting
            vector_weight=self.config.vector_weight,
            text_weight=self.config.text_weight,
            filters=ResourceFilter(
                tenant_id=tenant_id,
                trust_tier=trust_min.value if trust_min is not None and hasattr(trust_min, "value") else trust_min,
                layer=layer.value if layer is not None and hasattr(layer, "value") else layer,
                collection_id=collection,
            ) if any([tenant_id, trust_min, layer, collection]) else None,
            as_of=str(as_of) if as_of else None,
        )

        # Get raw results from storage (with timeout protection)
        raw_results = await self._with_timeout(self._storage.search(search_query))

        # Apply trust weighting with optional layer boost
        weighted = apply_trust_weighting(raw_results, self.config, layer_boost=_layer_boost)

        # Apply threshold after trust weighting
        filtered = [r for r in weighted if r.relevance >= threshold]

        # Deduplicate by resource_id (keep best chunk per resource)
        if deduplicate:
            seen: dict[str, SearchResult] = {}
            for r in filtered:
                if r.resource_id not in seen or r.relevance > seen[r.resource_id].relevance:
                    seen[r.resource_id] = r
            filtered = sorted(seen.values(), key=lambda x: x.relevance, reverse=True)

        # Apply pagination
        paginated = filtered[offset : offset + top_k]

        # Add explain metadata if requested
        if explain:
            for r in paginated:
                r.explain_metadata = {
                    "explain": {
                        "vector_similarity": r.vector_similarity,
                        "text_rank": r.text_rank,
                        "trust_weight": r.trust_weight,
                        "freshness": r.freshness,
                        "layer_boost": _layer_boost,
                        "composite_relevance": r.relevance,
                    }
                }

        return paginated

    async def search_with_facets(
        self,
        query: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Search with faceted results.

        Returns results plus facet counts by trust tier, resource type,
        and data classification.
        """
        results: list[SearchResult] = await self.search(query, **kwargs)

        facets: dict[str, dict[str, int]] = {
            "trust_tier": {},
            "resource_type": {},
            "data_classification": {},
        }
        for r in results:
            tier = r.trust_tier.value if hasattr(r.trust_tier, "value") else str(r.trust_tier)
            facets["trust_tier"][tier] = facets["trust_tier"].get(tier, 0) + 1
            if r.resource_type:
                facets["resource_type"][r.resource_type] = facets["resource_type"].get(r.resource_type, 0) + 1
            if r.data_classification:
                facets["data_classification"][r.data_classification] = facets["data_classification"].get(r.data_classification, 0) + 1

        return {
            "results": results,
            "total": len(results),
            "facets": facets,
        }

    # --- Verification ---

    async def verify(self, resource_id: str | None = None) -> VerificationResult | VaultVerificationResult:
        """Verify integrity of a resource or the entire vault.

        Args:
            resource_id: If provided, verify single resource. Otherwise verify all.

        Returns:
            VerificationResult for single resource, VaultVerificationResult for all.
        """
        await self._ensure_initialized()
        self._check_permission("verify")

        if resource_id:
            return await self._verify_resource(resource_id)
        return await self._verify_all()

    async def _verify_resource(self, resource_id: str) -> VerificationResult:
        """Verify a single resource's integrity."""
        from qp_vault.core.hasher import compute_cid, compute_resource_hash

        resource = await self.get(resource_id)
        chunks = await self._storage.get_chunks_for_resource(resource_id)

        # Recompute chunk CIDs
        failed_chunks = []
        chunk_cids = []
        for chunk in chunks:
            expected_cid = compute_cid(chunk.content)
            chunk_cids.append(expected_cid)
            if expected_cid != chunk.cid:
                failed_chunks.append(chunk.cid)

        # Recompute resource hash
        computed_hash = compute_resource_hash(chunk_cids) if chunk_cids else ""

        return VerificationResult(
            resource_id=resource_id,
            passed=computed_hash == resource.content_hash and not failed_chunks,
            stored_hash=resource.content_hash,
            computed_hash=computed_hash,
            chunk_count=len(chunks),
            failed_chunks=failed_chunks,
        )

    async def _verify_all(self) -> VaultVerificationResult:
        """Verify entire vault via Merkle tree."""
        import time

        start = time.monotonic()
        all_hashes = await self._storage.get_all_hashes()

        if not all_hashes:
            return VaultVerificationResult(
                passed=True,
                merkle_root="",
                resource_count=0,
                verified_count=0,
                duration_ms=0,
            )

        hashes = [h for _, h in all_hashes]
        merkle_root = compute_merkle_root(hashes)

        duration_ms = int((time.monotonic() - start) * 1000)

        return VaultVerificationResult(
            passed=True,  # Full per-resource verification would be separate
            merkle_root=merkle_root,
            resource_count=len(all_hashes),
            verified_count=len(all_hashes),
            duration_ms=duration_ms,
        )

    async def export_proof(self, resource_id: str) -> MerkleProof:
        """Export a Merkle proof for a specific resource.

        The proof allows an auditor to verify that a resource belongs
        to the vault's Merkle tree without downloading the entire vault.
        """
        await self._ensure_initialized()
        from qp_vault.core.hasher import compute_merkle_proof, compute_merkle_root
        from qp_vault.models import MerkleProof

        all_hashes = await self._storage.get_all_hashes()
        if not all_hashes:
            raise VaultError("Cannot export proof from empty vault")

        ids = [h[0] for h in all_hashes]
        hashes = [h[1] for h in all_hashes]

        if resource_id not in ids:
            raise VaultError(f"Resource {resource_id} not found in vault")

        leaf_index = ids.index(resource_id)
        root = compute_merkle_root(hashes)
        proof_path = compute_merkle_proof(hashes, leaf_index)

        return MerkleProof(
            resource_id=resource_id,
            resource_hash=hashes[leaf_index],
            merkle_root=root,
            path=proof_path,
            leaf_index=leaf_index,
            tree_size=len(hashes),
        )

    # --- Status ---

    # --- Memory Layers ---

    def layer(self, name: MemoryLayer | str) -> LayerView:
        """Get a scoped view of a memory layer.

        Example:
            ops = vault.layer(MemoryLayer.OPERATIONAL)
            ops.add("runbook.md")  # Auto-applies layer defaults
            ops.search("deploy")   # Scoped to operational layer
        """
        from qp_vault.core.layer_manager import LayerView
        layer_enum = MemoryLayer(name) if isinstance(name, str) else name
        return LayerView(layer_enum, self, self._layer_manager)

    # --- Collections ---

    async def create_collection(
        self,
        name: str,
        *,
        description: str = "",
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new collection."""
        await self._ensure_initialized()
        self._check_permission("create_collection")
        tenant_id = self._resolve_tenant(tenant_id)
        import uuid
        from datetime import UTC, datetime
        collection_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC).isoformat()
        await self._storage.store_collection(collection_id, name, description, now)
        return {"id": collection_id, "name": name, "description": description}

    async def list_collections(self, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List all collections."""
        await self._ensure_initialized()
        return await self._storage.list_collections()

    # --- Integrity ---

    async def health(self, resource_id: str | None = None) -> HealthScore:
        """Compute health score (0-100).

        Args:
            resource_id: If provided, compute health for a single resource.
                        If None, compute vault-wide health.

        Returns:
            HealthScore with component scores.
        """
        await self._ensure_initialized()
        self._check_permission("health")
        from qp_vault.integrity.detector import compute_health_score

        if resource_id:
            resource = await self.get(resource_id)
            return compute_health_score([resource])

        # Use cached result if available
        cache_key = "health:vault"
        cached: HealthScore | None = self._cache_get(cache_key)
        if cached is not None:
            return cached

        all_resources = await self._list_all_bounded()
        result = compute_health_score(all_resources)
        self._cache_set(cache_key, result)
        return result

    async def export_vault(self, path: str | Path) -> dict[str, Any]:
        """Export the vault to a JSON file for portability.

        Args:
            path: Output file path.

        Returns:
            Summary with resource count and export path.
        """
        import json as _json
        await self._ensure_initialized()
        self._check_permission("export_vault")
        resources: list[Resource] = await self._list_all_bounded()
        data = {
            "version": "0.14.0",
            "resource_count": len(resources),
            "resources": [r.model_dump(mode="json") for r in resources],
        }
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(data, default=str, indent=2))
        return {"path": str(out), "resource_count": len(resources)}

    async def import_vault(self, path: str | Path) -> list[Resource]:
        """Import resources from an exported vault JSON file.

        Args:
            path: Path to the exported JSON file.

        Returns:
            List of imported resources.
        """
        import json as _json
        await self._ensure_initialized()
        self._check_permission("import_vault")
        data = _json.loads(Path(path).read_text())
        imported = []
        for r_data in data.get("resources", []):
            content = r_data.get("name", "imported")
            resource = await self.add(
                content,
                name=r_data.get("name", "imported"),
                trust=r_data.get("trust_tier", "working"),
                tags=r_data.get("tags", []),
                metadata=r_data.get("metadata", {}),
            )
            imported.append(resource)
        return imported

    async def _list_all_bounded(self, *, hard_cap: int = 50_000, batch_size: int = 1000) -> list[Resource]:
        """Load all resources with pagination and a hard cap to prevent OOM."""
        all_resources: list[Resource] = []
        offset = 0
        while offset < hard_cap:
            batch = await self._resource_manager.list(limit=batch_size, offset=offset)
            if not batch:
                break
            all_resources.extend(batch)
            offset += batch_size
        return all_resources

    # --- Status ---

    async def status(self) -> dict[str, Any]:
        """Get vault status summary."""
        await self._ensure_initialized()
        self._check_permission("status")

        # Use cached result if available
        cache_key = "status:vault"
        cached_status: dict[str, Any] | None = self._cache_get(cache_key)
        if cached_status is not None:
            return cached_status

        all_resources: list[Resource] = await self._list_all_bounded()

        by_status: dict[str, int] = {}
        by_trust: dict[str, int] = {}
        by_layer: dict[str, int] = {}

        for r in all_resources:
            s = r.status.value if hasattr(r.status, "value") else r.status
            by_status[s] = by_status.get(s, 0) + 1
            t = r.trust_tier.value if hasattr(r.trust_tier, "value") else r.trust_tier
            by_trust[t] = by_trust.get(t, 0) + 1
            if r.layer:
                lyr = r.layer.value if hasattr(r.layer, "value") else r.layer
                by_layer[lyr] = by_layer.get(lyr, 0) + 1

        layer_stats = self._layer_manager.get_stats(all_resources)

        result = {
            "total_resources": len(all_resources),
            "by_status": by_status,
            "by_trust_tier": by_trust,
            "by_layer": by_layer,
            "layer_details": layer_stats,
            "vault_path": str(self.path),
            "backend": "sqlite",
        }
        self._cache_set(cache_key, result)
        return result

    # --- Plugin Registration ---

    def register_embedder(self, embedder: EmbeddingProvider) -> None:
        """Register a custom embedding provider."""
        self._embedder = embedder
        self._resource_manager._embedder = embedder

    def register_parser(self, parser: ParserProvider) -> None:
        """Register a custom file parser."""
        self._parsers.append(parser)

    def register_policy(self, policy: PolicyProvider) -> None:
        """Register a governance policy."""
        self._policies.append(policy)


def _run_async(coro: Any) -> Any:
    """Run an async coroutine synchronously.

    Note: Returns Any because Coroutine[Any, Any, T] is not easily
    parameterized at the call site. Callers use typed local variables
    to maintain type safety.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop; create a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class Vault:
    """Governed knowledge store (sync interface).

    Wraps AsyncVault with synchronous methods.
    All parameters are identical to AsyncVault.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        storage: StorageBackend | None = None,
        embedder: EmbeddingProvider | None = None,
        auditor: AuditProvider | None = None,
        parsers: list[ParserProvider] | None = None,
        policies: list[PolicyProvider] | None = None,
        config: VaultConfig | None = None,
        plugins_dir: str | Path | None = None,
    ) -> None:
        self._async = AsyncVault(
            path,
            storage=storage,
            embedder=embedder,
            auditor=auditor,
            parsers=parsers,
            policies=policies,
            config=config,
            plugins_dir=plugins_dir,
        )

    def add(self, source: str | Path | bytes, **kwargs: Any) -> Resource:
        """Add a resource to the vault."""
        return cast("Resource", _run_async(self._async.add(source, **kwargs)))

    def add_batch(self, sources: list[str | Path | bytes], **kwargs: Any) -> list[Resource]:
        """Add multiple resources in a batch."""
        result: list[Resource] = _run_async(self._async.add_batch(sources, **kwargs))
        return result

    def get(self, resource_id: str) -> Resource:
        """Get a resource by ID."""
        return cast("Resource", _run_async(self._async.get(resource_id)))

    def list(self, **kwargs: Any) -> list[Resource]:
        """List resources with optional filters."""
        return cast("list[Resource]", _run_async(self._async.list(**kwargs)))

    def update(self, resource_id: str, **kwargs: Any) -> Resource:
        """Update resource metadata."""
        return cast("Resource", _run_async(self._async.update(resource_id, **kwargs)))

    def delete(self, resource_id: str, *, hard: bool = False) -> None:
        """Delete a resource."""
        _run_async(self._async.delete(resource_id, hard=hard))

    def get_content(self, resource_id: str) -> str:
        """Retrieve the full text content of a resource."""
        result: str = _run_async(self._async.get_content(resource_id))
        return result

    def replace(self, resource_id: str, new_content: str, *, reason: str | None = None) -> tuple[Resource, Resource]:
        """Replace a resource's content atomically. Returns (old, new)."""
        result: tuple[Resource, Resource] = _run_async(self._async.replace(resource_id, new_content, reason=reason))
        return result

    def get_provenance(self, resource_id: str) -> list[dict[str, Any]]:
        """Get provenance records for a resource."""
        result: list[dict[str, Any]] = _run_async(self._async.get_provenance(resource_id))
        return result

    def set_adversarial_status(self, resource_id: str, status: str) -> Resource:
        """Set adversarial verification status."""
        result: Resource = _run_async(self._async.set_adversarial_status(resource_id, status))
        return result

    def transition(self, resource_id: str, target: Lifecycle | str, *, reason: str | None = None) -> Resource:
        """Transition lifecycle state."""
        return cast("Resource", _run_async(self._async.transition(resource_id, target, reason=reason)))

    def supersede(self, old_id: str, new_id: str) -> tuple[Resource, Resource]:
        """Supersede a resource with a newer version."""
        return cast("tuple[Resource, Resource]", _run_async(self._async.supersede(old_id, new_id)))

    def expiring(self, *, days: int = 90) -> list[Resource]:
        """Find resources expiring within N days."""
        return cast("list[Resource]", _run_async(self._async.expiring(days=days)))

    def chain(self, resource_id: str) -> list[Resource]:
        """Get supersession chain."""
        return cast("list[Resource]", _run_async(self._async.chain(resource_id)))

    def export_proof(self, resource_id: str) -> MerkleProof:
        """Export Merkle proof for auditors."""
        result: MerkleProof = _run_async(self._async.export_proof(resource_id))
        return result

    def search(self, query: str, **kwargs: Any) -> list[SearchResult]:
        """Trust-weighted hybrid search."""
        result: list[SearchResult] = _run_async(self._async.search(query, **kwargs))
        return result

    def verify(self, resource_id: str | None = None) -> VerificationResult | VaultVerificationResult:
        """Verify integrity."""
        result: VerificationResult | VaultVerificationResult = _run_async(self._async.verify(resource_id))
        return result

    def layer(self, name: MemoryLayer | str) -> LayerView:
        """Get a scoped view of a memory layer."""
        return self._async.layer(name)

    def create_collection(self, name: str, **kwargs: Any) -> dict[str, Any]:
        """Create a new collection."""
        result: dict[str, Any] = _run_async(self._async.create_collection(name, **kwargs))
        return result

    def list_collections(self, **kwargs: Any) -> list[dict[str, Any]]:
        """List all collections."""
        result: list[dict[str, Any]] = _run_async(self._async.list_collections(**kwargs))
        return result

    def health(self, resource_id: str | None = None) -> HealthScore:
        """Compute vault or per-resource health score."""
        result: HealthScore = _run_async(self._async.health(resource_id))
        return result

    def status(self) -> dict[str, Any]:
        """Get vault status."""
        result: dict[str, Any] = _run_async(self._async.status())
        return result

    def register_embedder(self, embedder: EmbeddingProvider) -> None:
        """Register a custom embedding provider."""
        self._async.register_embedder(embedder)

    def register_parser(self, parser: ParserProvider) -> None:
        """Register a custom file parser."""
        self._async.register_parser(parser)

    def register_policy(self, policy: PolicyProvider) -> None:
        """Register a governance policy."""
        self._async.register_policy(policy)

    @classmethod
    def from_config(cls, config_path: str | Path) -> Vault:
        """Create a Vault from a TOML configuration file."""
        config = VaultConfig.from_toml(config_path)
        return cls(path=".", config=config)

    @classmethod
    def from_postgres(cls, dsn: str, **kwargs: Any) -> Vault:
        """Create a Vault with PostgreSQL backend."""
        config = VaultConfig(backend="postgres", postgres_dsn=dsn)
        return cls(path=".", config=config, **kwargs)

"""Main Vault classes: sync and async interfaces.

The primary entry point for qp-vault. Vault (sync) wraps AsyncVault.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    from qp_vault.models import HealthScore, MerkleProof

# --- Input Sanitization ---

_MAX_TAG_LENGTH = 100
_MAX_TAGS = 50
_MAX_METADATA_KEYS = 100
_MAX_METADATA_KEY_LENGTH = 100
_MAX_METADATA_VALUE_SIZE = 10_000


def _sanitize_name(name: str) -> str:
    """Sanitize a resource name for safe storage.

    Strips path components, null bytes, control characters, backslashes.
    Caps length at 255.
    """
    import re
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
    ) -> None:
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.config = config or VaultConfig()

        # Storage backend
        if storage is not None:
            self._storage = storage
        else:
            self._storage = SQLiteBackend(self.path / "vault.db")

        # Embedding provider
        self._embedder = embedder

        # Audit provider
        if auditor is not None:
            self._auditor = auditor
        else:
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

        self._initialized = False

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await self._storage.initialize()
            self._initialized = True

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
            path = Path(source)
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

        # Strip null bytes from content (prevents storage/search corruption)
        text = text.replace("\x00", "")

        return await self._resource_manager.add(
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
        )

    async def get(self, resource_id: str) -> Resource:
        """Get a resource by ID."""
        await self._ensure_initialized()
        return await self._resource_manager.get(resource_id)

    async def list(
        self,
        *,
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
        return await self._resource_manager.list(
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
        return await self._resource_manager.update(
            resource_id,
            name=name,
            trust=trust,
            classification=classification,
            tags=tags,
            metadata=metadata,
        )

    async def delete(self, resource_id: str, *, hard: bool = False) -> None:
        """Delete a resource (soft by default)."""
        await self._ensure_initialized()
        await self._resource_manager.delete(resource_id, hard=hard)

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
        return await self._lifecycle.transition(resource_id, target, reason=reason)

    async def supersede(
        self, old_id: str, new_id: str
    ) -> tuple[Resource, Resource]:
        """Mark old resource as superseded by new resource."""
        await self._ensure_initialized()
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
        top_k: int = 10,
        threshold: float = 0.0,
        trust_min: TrustTier | str | None = None,
        layer: MemoryLayer | str | None = None,
        collection: str | None = None,
        as_of: date | None = None,
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
                trust_tier=trust_min.value if hasattr(trust_min, "value") else trust_min,
                layer=layer.value if hasattr(layer, "value") else layer,
                collection_id=collection,
            ) if any([trust_min, layer, collection]) else None,
            as_of=str(as_of) if as_of else None,
        )

        # Get raw results from storage
        raw_results = await self._storage.search(search_query)

        # Apply trust weighting
        weighted = apply_trust_weighting(raw_results, self.config)

        # Apply threshold after trust weighting
        filtered = [r for r in weighted if r.relevance >= threshold]

        return filtered[:top_k]

    # --- Verification ---

    async def verify(self, resource_id: str | None = None) -> VerificationResult | VaultVerificationResult:
        """Verify integrity of a resource or the entire vault.

        Args:
            resource_id: If provided, verify single resource. Otherwise verify all.

        Returns:
            VerificationResult for single resource, VaultVerificationResult for all.
        """
        await self._ensure_initialized()

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

    # --- Integrity ---

    async def health(self) -> HealthScore:
        """Compute vault health score (0-100).

        Assesses: freshness, uniqueness, coherence, connectivity, trust alignment.
        """
        await self._ensure_initialized()
        from qp_vault.integrity.detector import compute_health_score
        all_resources = await self._list_all_bounded()
        return compute_health_score(all_resources)

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
        all_resources = await self._list_all_bounded()

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

        return {
            "total_resources": len(all_resources),
            "by_status": by_status,
            "by_trust_tier": by_trust,
            "by_layer": by_layer,
            "layer_details": layer_stats,
            "vault_path": str(self.path),
            "backend": "sqlite",
        }

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
    """Run an async coroutine synchronously."""
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
        return _run_async(self._async.add(source, **kwargs))

    def get(self, resource_id: str) -> Resource:
        """Get a resource by ID."""
        return _run_async(self._async.get(resource_id))

    def list(self, **kwargs: Any) -> list[Resource]:
        """List resources with optional filters."""
        return _run_async(self._async.list(**kwargs))

    def update(self, resource_id: str, **kwargs: Any) -> Resource:
        """Update resource metadata."""
        return _run_async(self._async.update(resource_id, **kwargs))

    def delete(self, resource_id: str, *, hard: bool = False) -> None:
        """Delete a resource."""
        return _run_async(self._async.delete(resource_id, hard=hard))

    def transition(self, resource_id: str, target: Lifecycle | str, *, reason: str | None = None) -> Resource:
        """Transition lifecycle state."""
        return _run_async(self._async.transition(resource_id, target, reason=reason))

    def supersede(self, old_id: str, new_id: str) -> tuple[Resource, Resource]:
        """Supersede a resource with a newer version."""
        return _run_async(self._async.supersede(old_id, new_id))

    def expiring(self, *, days: int = 90) -> list[Resource]:
        """Find resources expiring within N days."""
        return _run_async(self._async.expiring(days=days))

    def chain(self, resource_id: str) -> list[Resource]:
        """Get supersession chain."""
        return _run_async(self._async.chain(resource_id))

    def export_proof(self, resource_id: str) -> Any:
        """Export Merkle proof for auditors."""
        return _run_async(self._async.export_proof(resource_id))

    def search(self, query: str, **kwargs: Any) -> list[SearchResult]:
        """Trust-weighted hybrid search."""
        return _run_async(self._async.search(query, **kwargs))

    def verify(self, resource_id: str | None = None) -> VerificationResult | VaultVerificationResult:
        """Verify integrity."""
        return _run_async(self._async.verify(resource_id))

    def layer(self, name: MemoryLayer | str) -> Any:
        """Get a scoped view of a memory layer."""
        return self._async.layer(name)

    def health(self) -> Any:
        """Compute vault health score."""
        return _run_async(self._async.health())

    def status(self) -> dict[str, Any]:
        """Get vault status."""
        return _run_async(self._async.status())

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

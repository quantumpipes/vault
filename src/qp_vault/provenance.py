# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Content provenance: cryptographic attestation of document origin.

Every document entering the Vault gets a provenance record binding the
document hash, uploader identity, upload method, and timestamp. Records
are signed with Ed25519 (+ optional ML-DSA-65) so provenance cannot be
forged or tampered with after creation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from qp_vault.models import ContentProvenance

if TYPE_CHECKING:
    from qp_vault.enums import UploadMethod


class ContentProvenanceService:
    """Creates, verifies, and queries provenance attestations.

    Args:
        signing_fn: Async callable that signs bytes and returns a hex signature.
                    Signature scheme must be Ed25519 or ML-DSA-65.
        verify_fn: Async callable that verifies (message_bytes, signature_hex)
                   and returns True if valid.
    """

    def __init__(
        self,
        signing_fn: Any | None = None,
        verify_fn: Any | None = None,
    ) -> None:
        self._signing_fn = signing_fn
        self._verify_fn = verify_fn
        self._records: dict[str, ContentProvenance] = {}
        self._by_resource: dict[str, list[str]] = {}

    async def create_attestation(
        self,
        resource_id: str,
        uploader_id: str,
        method: UploadMethod,
        original_hash: str,
        source_description: str = "",
    ) -> ContentProvenance:
        """Create a signed provenance attestation for a document.

        Args:
            resource_id: Vault resource ID.
            uploader_id: Identity of the uploader (user ID or system ID).
            method: How the document entered the Vault.
            original_hash: SHA3-256 hash of the original file content.
            source_description: Human-readable description of the source.

        Returns:
            Signed ContentProvenance record.
        """
        provenance_id = str(uuid4())
        now = datetime.now(tz=UTC)

        provenance = ContentProvenance(
            id=provenance_id,
            resource_id=resource_id,
            uploader_id=uploader_id,
            upload_method=method,
            source_description=source_description,
            original_hash=original_hash,
            created_at=now,
        )

        # Create canonical representation for signing
        canonical = self._canonical_bytes(provenance)

        if self._signing_fn is not None:
            signature = await self._signing_fn(canonical)
            provenance = provenance.model_copy(
                update={
                    "provenance_signature": signature,
                    "signature_verified": True,
                }
            )

        # Store in memory (production: persisted via storage backend)
        self._records[provenance_id] = provenance
        self._by_resource.setdefault(resource_id, []).append(provenance_id)

        return provenance

    async def verify_attestation(self, provenance: ContentProvenance) -> bool:
        """Verify that a provenance record's signature is valid.

        Args:
            provenance: The record to verify.

        Returns:
            True if the signature is valid, False otherwise.
        """
        if not provenance.provenance_signature:
            return False

        if self._verify_fn is None:
            return False

        canonical = self._canonical_bytes(provenance)
        return await self._verify_fn(canonical, provenance.provenance_signature)

    async def get_chain(self, resource_id: str) -> list[ContentProvenance]:
        """Get all provenance records for a resource, ordered by creation time.

        Args:
            resource_id: Vault resource ID.

        Returns:
            List of provenance records in chronological order.
        """
        record_ids = self._by_resource.get(resource_id, [])
        records = [self._records[rid] for rid in record_ids if rid in self._records]
        return sorted(records, key=lambda r: r.created_at)

    async def get_by_uploader(self, uploader_id: str) -> list[ContentProvenance]:
        """Get all provenance records created by a specific uploader.

        Args:
            uploader_id: The uploader to filter by.

        Returns:
            List of provenance records.
        """
        return [
            r for r in self._records.values()
            if r.uploader_id == uploader_id
        ]

    async def get_by_method(self, method: UploadMethod) -> list[ContentProvenance]:
        """Get all provenance records with a specific upload method.

        Args:
            method: The upload method to filter by.

        Returns:
            List of provenance records.
        """
        return [
            r for r in self._records.values()
            if r.upload_method == method
        ]

    @staticmethod
    def _canonical_bytes(provenance: ContentProvenance) -> bytes:
        """Create deterministic canonical bytes for signing.

        Excludes the signature field itself to avoid circular dependency.
        Uses sorted JSON keys for deterministic output.
        """
        canonical = {
            "id": provenance.id,
            "resource_id": provenance.resource_id,
            "uploader_id": provenance.uploader_id,
            "upload_method": provenance.upload_method,
            "source_description": provenance.source_description,
            "original_hash": provenance.original_hash,
            "created_at": provenance.created_at.isoformat(),
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def compute_hash(content: bytes) -> str:
        """Compute SHA3-256 hash of content for provenance attestation.

        Args:
            content: Raw file bytes.

        Returns:
            Hex-encoded SHA3-256 digest.
        """
        return hashlib.sha3_256(content).hexdigest()

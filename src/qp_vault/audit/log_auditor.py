"""JSON logging fallback auditor.

Writes VaultEvents as JSON lines to a file. Used when qp-capsule
is not installed. Provides basic audit trail without cryptographic
guarantees.

File I/O is offloaded to a thread executor to avoid blocking the
event loop in async contexts.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from qp_vault.models import VaultEvent


def _write_event(log_path: Path, line: str) -> None:
    """Write a single JSON line to the audit log (runs in thread)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


class LogAuditor:
    """Audit provider that writes events as JSON lines.

    Each event is appended to {vault_path}/audit.jsonl as a single line.
    File I/O runs in a thread executor to avoid blocking async code.
    """

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path

    async def record(self, event: VaultEvent) -> str:
        """Record a vault event to the JSON lines log.

        Returns:
            A unique event ID.
        """
        event_id = str(uuid.uuid4())
        record = {
            "event_id": event_id,
            "event_type": event.event_type.value if hasattr(event.event_type, "value") else event.event_type,
            "resource_id": event.resource_id,
            "resource_name": event.resource_name,
            "resource_hash": event.resource_hash,
            "actor": event.actor,
            "timestamp": event.timestamp.isoformat(),
            "details": event.details,
        }

        line = json.dumps(record, default=str) + "\n"

        # Offload blocking file I/O to thread executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _write_event, self.log_path, line)

        return event_id

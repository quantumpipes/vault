# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Real-time event streaming for vault mutations.

Allows agents and consumers to subscribe to vault events
and react in real-time to knowledge changes.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qp_vault.models import VaultEvent


class VaultEventStream:
    """Real-time event stream for vault mutations.

    Consumers subscribe and receive VaultEvents as they occur.
    Supports multiple concurrent subscribers.

    Usage:
        stream = VaultEventStream()
        vault = AsyncVault("./knowledge", auditor=stream)

        # Subscribe in an async context
        async for event in stream.subscribe():
            print(f"{event.event_type}: {event.resource_name}")
    """

    def __init__(self, *, buffer_size: int = 1000) -> None:
        self._subscribers: list[asyncio.Queue[VaultEvent]] = []
        self._history: deque[VaultEvent] = deque(maxlen=buffer_size)

    async def record(self, event: VaultEvent) -> str:
        """Record an event and broadcast to all subscribers.

        Implements AuditProvider protocol so it can be used as auditor.
        """
        import uuid
        event_id = str(uuid.uuid4())
        self._history.append(event)

        # Broadcast to all subscribers (drop if slow)
        import contextlib
        for queue in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

        return event_id

    async def subscribe(self, *, replay: bool = False) -> Any:
        """Subscribe to the event stream.

        Args:
            replay: If True, replay recent history before live events.

        Yields:
            VaultEvent objects as they occur.
        """
        queue: asyncio.Queue[VaultEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)

        try:
            # Replay history if requested
            if replay:
                for event in self._history:
                    yield event

            # Stream live events
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers.remove(queue)

    @property
    def history(self) -> list[VaultEvent]:
        """Get recent event history."""
        return list(self._history)

    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._subscribers)

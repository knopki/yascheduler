"""Async queue with message deduplication."""
# FILE: yascheduler/application/queue.py
# VERSION: 1.9.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Deduplicating async queue for producer-consumer scheduling loops.
#   SCOPE: Deduplicating async queue (UniqueQueue) and typed message (UMessage) for producer-consumer scheduling loops.
#   DEPENDS: none
#   LINKS: M-QUEUE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   UniqueQueue - Async queue that skips duplicate messages by ID
#   UMessage - Typed message with ID and payload
#   TUMsgId - TypeVar for message ID (bound Hashable)
#   TUMsgPayload - TypeVar for message payload
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - Added asyncio.Lock to UniqueQueue.put() for check-then-act race window.
#   PREVIOUS_CHANGE: v1.8.0 - Migrated UMessage from attrs to stdlib dataclasses; id-only __eq__/__hash__ with eq=False.
# END_CHANGE_SUMMARY

import asyncio
from collections import deque
from collections.abc import Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

TUMsgId = TypeVar("TUMsgId", bound=Hashable)
TUMsgPayload = TypeVar("TUMsgPayload")


@dataclass(frozen=True, eq=False)
class UMessage(Generic[TUMsgId, TUMsgPayload]):
    """Async queue message."""

    __slots__ = ("id", "payload")
    id: TUMsgId
    payload: TUMsgPayload

    # START_BLOCK_DEFINE_ID_ONLY_EQUALITY
    def __eq__(self, other: object) -> bool:
        """Equality check by message ID only."""
        if not isinstance(other, UMessage):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on message ID."""
        return hash(self.id)

    # END_BLOCK_DEFINE_ID_ONLY_EQUALITY


class UniqueQueue(asyncio.Queue, Generic[TUMsgId, TUMsgPayload]):
    """Async queue with message deduplication."""

    name: str
    _put_lock: asyncio.Lock
    _queue: deque[UMessage[TUMsgId, TUMsgPayload]]
    _done_pending: set[UMessage[TUMsgId, TUMsgPayload]]

    def __init__(
        self,
        name: str,
        *argv: object,
        maxsize: int = 0,
        **kwargs: object,
    ) -> None:
        """Initialise the queue with deduplication support."""
        self.name = name
        self._put_lock = asyncio.Lock()
        self._done_pending = set()
        super().__init__(maxsize, *argv, **kwargs)

    def _get(self) -> UMessage[TUMsgId, TUMsgPayload]:
        item = self._queue.popleft()
        self._done_pending.add(item)
        return item

    async def get(self) -> UMessage[TUMsgId, TUMsgPayload]:
        """Return and track the next message from the queue."""
        return await super().get()

    async def put(self, item: UMessage[TUMsgId, TUMsgPayload]) -> None:
        """Enqueue a message; skip if already present or done."""
        async with self._put_lock:
            # skip already added
            if item in self._queue or item in self._done_pending:
                return
            await super().put(item)

    def task_done(self) -> None:
        """``task_done()`` is not supported; use ``item_done()``."""
        msg = "task_done() not implemented, use item_done()"
        raise NotImplementedError(msg)

    def item_done(self, item: UMessage) -> None:
        """Indicate that a enqueued task is complete."""
        self._done_pending.remove(item)
        super().task_done()

    def psize(self) -> int:
        """Return number of items not done but not in queue.."""
        return len(self._done_pending)

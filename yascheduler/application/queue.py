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
"""Async queue with message deduplication"""

import asyncio
from collections import deque
from collections.abc import Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

TUMsgId = TypeVar("TUMsgId", bound=Hashable)
TUMsgPayload = TypeVar("TUMsgPayload")


@dataclass(frozen=True, eq=False)
class UMessage(Generic[TUMsgId, TUMsgPayload]):
    """Async queue message"""

    __slots__ = ("id", "payload")
    id: TUMsgId
    payload: TUMsgPayload

    # START_BLOCK_DEFINE_ID_ONLY_EQUALITY
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UMessage):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    # END_BLOCK_DEFINE_ID_ONLY_EQUALITY


class UniqueQueue(asyncio.Queue, Generic[TUMsgId, TUMsgPayload]):
    """Async queue with message deduplication"""

    name: str
    _put_lock: asyncio.Lock
    _queue: deque[UMessage[TUMsgId, TUMsgPayload]]
    _done_pending: set[UMessage[TUMsgId, TUMsgPayload]]

    def __init__(
        self, name: str, *argv: object, maxsize: int = 0, **kwargs: object
    ) -> None:  # noqa: ANN002,ANN003
        self.name = name
        self._put_lock = asyncio.Lock()
        self._done_pending = set()
        super().__init__(maxsize, *argv, **kwargs)

    def _get(self) -> UMessage[TUMsgId, TUMsgPayload]:
        item = self._queue.popleft()
        self._done_pending.add(item)
        return item

    async def get(self) -> UMessage[TUMsgId, TUMsgPayload]:
        return await super().get()

    async def put(self, item: UMessage[TUMsgId, TUMsgPayload]) -> None:
        async with self._put_lock:
            # skip already added
            if item in self._queue or item in self._done_pending:
                return
            await super().put(item)

    def task_done(self) -> None:
        raise NotImplementedError("task_done() not implemented, use item_done()")

    def item_done(self, item: UMessage) -> None:
        """Indicate that a enqueued task is complete."""
        self._done_pending.remove(item)
        super().task_done()

    def psize(self) -> int:
        """Number of items not done but not in queue."""
        return len(self._done_pending)

"""Async queue with message deduplication."""
# region MODULE_CONTRACT
# PURPOSE: Ensure each message ID is processed at most once per lifecycle so producer-consumer loops never double-process a task event.
# SCOPE: UniqueQueue (deduplicating async queue) and UMessage (typed message) for producer-consumer scheduling loops.
# INVARIANTS: Dedup is by message ID, not payload — two messages with same ID but different payloads are treated as duplicates.
# KEYWORDS: queue, dedup, producer, consumer, async, UniqueQueue, UMessage
# endregion MODULE_CONTRACT

import asyncio
from collections import deque
from collections.abc import Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

TUMsgId = TypeVar("TUMsgId", bound=Hashable)
TUMsgPayload = TypeVar("TUMsgPayload")

__all__ = [
    "UMessage",
    "UniqueQueue",
]


# region CLASS_UMessage
# PURPOSE: Enable UniqueQueue deduplication by identity — decouple message payload from identity so two messages with the same content but different IDs are treated as distinct events.
# INVARIANTS: `__eq__` and `__hash__` consult `id` only.
@dataclass(frozen=True, eq=False)
class UMessage(Generic[TUMsgId, TUMsgPayload]):
    """Async queue message."""

    __slots__ = ("id", "payload")
    id: TUMsgId
    payload: TUMsgPayload

    # region BLOCK_define_id_only_equality
    def __eq__(self, other: object) -> bool:
        """Equality check by message ID only."""
        if not isinstance(other, UMessage):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on message ID."""
        return hash(self.id)

    # endregion BLOCK_define_id_only_equality


# endregion CLASS_UMessage


# region CLASS_UniqueQueue
# PURPOSE: Prevent the daemon from processing the same task event twice across overlapping producer-consumer cycles.
# INVARIANTS: Dedup is keyed on `UMessage.id`; two messages with equal `id` are duplicates regardless of `payload`.
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

    # region METHOD_put
    # PURPOSE: Guarantee at-most-once delivery per message ID — skip duplicates already queued or processed so subsequent producer cycles do not re-enqueue the same event.
    async def put(self, item: UMessage[TUMsgId, TUMsgPayload]) -> None:
        """Enqueue a message; skip if already present or done."""
        async with self._put_lock:
            # skip already added
            if item in self._queue or item in self._done_pending:
                return
            await super().put(item)

    # endregion METHOD_put

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


# endregion CLASS_UniqueQueue

# FILE: yascheduler/application/queue.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Deduplicating async queue for producer-consumer scheduling loops.
#   SCOPE: UniqueQueue class, UMessage dataclass.
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
#   LAST_CHANGE: v1.7.0 - Relocated from yascheduler/queue.py; same contents.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
# FIXME: use dataclasses instead of attrs
"""Async queue with message deduplication"""

import asyncio
from collections import deque
from collections.abc import Hashable
from typing import Generic, TypeVar

from attrs import define, field

TUMsgId = TypeVar("TUMsgId", bound=Hashable)
TUMsgPayload = TypeVar("TUMsgPayload")


@define(frozen=True)
class UMessage(Generic[TUMsgId, TUMsgPayload]):
    """Async queue message"""

    id: TUMsgId = field()
    payload: TUMsgPayload = field(hash=False)


class UniqueQueue(asyncio.Queue, Generic[TUMsgId, TUMsgPayload]):
    """Async queue with message deduplication"""

    name: str
    _queue: deque[UMessage[TUMsgId, TUMsgPayload]]
    _done_pending: set[UMessage[TUMsgId, TUMsgPayload]]

    # START_CONTRACT: __init__
    #   PURPOSE: Initialize queue with name and maxsize
    #   INPUTS: { name: str - queue identifier } | { maxsize: int - maximum queue size, default 0 (unlimited) }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Initializes internal queue state and done_pending set
    #   LINKS: M-QUEUE
    # END_CONTRACT: __init__
    def __init__(
        self, name: str, *argv: object, maxsize: int = 0, **kwargs: object
    ) -> None:  # noqa: ANN002,ANN003
        self.name = name
        self._done_pending = set()
        super().__init__(maxsize, *argv, **kwargs)

    def _get(self) -> UMessage[TUMsgId, TUMsgPayload]:
        item = self._queue.popleft()
        self._done_pending.add(item)
        return item

    # START_CONTRACT: get
    #   PURPOSE: Get next message from queue; tracks retrieved items in done_pending set for completion tracking
    #   INPUTS: { None }
    #   OUTPUTS: { UMessage - the next message from the queue }
    #   SIDE_EFFECTS: Removes item from queue and adds to done_pending set
    #   LINKS: M-QUEUE
    # END_CONTRACT: get
    async def get(self) -> UMessage[TUMsgId, TUMsgPayload]:
        return await super().get()

    # START_CONTRACT: put
    #   PURPOSE: Put message into queue, skip if ID already in seen set or queue
    #   INPUTS: { item: UMessage - message to enqueue }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Appends item to queue if not duplicate
    #   LINKS: M-QUEUE
    # END_CONTRACT: put
    async def put(self, item: UMessage[TUMsgId, TUMsgPayload]) -> None:
        # skip already added
        if item in self._queue or item in self._done_pending:
            return
        await super().put(item)

    # START_CONTRACT: task_done
    #   PURPOSE: Mark task as done (not implemented, use item_done instead)
    #   INPUTS: { None }
    #   OUTPUTS: { None - always raises NotImplementedError }
    #   SIDE_EFFECTS: Raises NotImplementedError
    #   LINKS: M-QUEUE
    # END_CONTRACT: task_done
    def task_done(self) -> None:
        raise NotImplementedError("task_done() not implemented, use item_done()")

    # START_CONTRACT: item_done
    #   PURPOSE: Indicate a specific enqueued task is complete
    #   INPUTS: { item: UMessage - the completed message }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Removes item from done_pending set, decrements unfinished task counter
    #   LINKS: M-QUEUE
    # END_CONTRACT: item_done
    def item_done(self, item: UMessage) -> None:
        """Indicate that a enqueued task is complete."""
        self._done_pending.remove(item)
        super().task_done()

    # START_CONTRACT: psize
    #   PURPOSE: Return number of pending items (not done but not in queue)
    #   INPUTS: { None }
    #   OUTPUTS: { int - number of items in done_pending set }
    #   SIDE_EFFECTS: None
    #   LINKS: M-QUEUE
    # END_CONTRACT: psize
    def psize(self) -> int:
        """Number of items not done but not in queue."""
        return len(self._done_pending)

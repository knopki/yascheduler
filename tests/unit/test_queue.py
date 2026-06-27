# FILE: tests/unit/test_queue.py
# VERSION: 1.2.0
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for UniqueQueue and UMessage covering deduplication, item lifecycle, and edge cases.
#   SCOPE: put/get, deduplication, item_done tracking, psize, task_done NotImplementedError.
#   DEPENDS: M-QUEUE
#   LINKS: M-QUEUE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   queue - fixture returning a UniqueQueue instance
#   msg - helper creating a UMessage with default id and payload
#   test_put_get - put then get returns original message
#   test_deduplication - duplicate put is silently skipped
#   test_item_done_tracking - get adds to pending, item_done removes it
#   test_item_done_allows_requeue - after item_done the same message can be re-queued
#   test_psize_after_get - psize reflects in-flight items
#   test_task_done_raises - task_done raises NotImplementedError
#   test_dedup_by_id - two messages with equal id dedup regardless of payload
#   test_dedup_first_wins - on duplicate id the first-inserted message is retained
#   test_unhashable_payload - unhashable payload is accepted through full lifecycle
#   test_put_race_full_queue - concurrent puts on full queue deduplicate under lock
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Added test_put_race_full_queue covering concurrent-put dedup under lock (check-then-act race fix).
#   PREVIOUS_CHANGE: v1.1.0 - Added test_dedup_by_id, test_dedup_first_wins, test_unhashable_payload pinning the id-only dedup invariant (payload excluded from __eq__/__hash__).
# END_CHANGE_SUMMARY

import asyncio

import pytest
import pytest_asyncio

from yascheduler.application.queue import UMessage, UniqueQueue


# START_CONTRACT: queue
#   PURPOSE: Fixture returning a UniqueQueue instance named "test".
#   INPUTS: { None }
#   OUTPUTS: { UniqueQueue - fresh queue instance }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: queue
@pytest_asyncio.fixture
async def queue() -> UniqueQueue:
    return UniqueQueue(name="test")


# START_CONTRACT: msg
#   PURPOSE: Helper creating a UMessage with default id and payload.
#   INPUTS: { msg_id: str - message ID (default "a"), payload: str - message payload (default "data") }
#   OUTPUTS: { UMessage - constructed message }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: msg
def msg(msg_id: str = "a", payload: str = "data") -> UMessage:
    return UMessage(id=msg_id, payload=payload)


# START_CONTRACT: test_put_get
#   PURPOSE: Verify that a message put into the queue can be retrieved via get returning the same message.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_put_get
async def test_put_get(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    result = await queue.get()
    assert result == m


# START_CONTRACT: test_deduplication
#   PURPOSE: Verify that putting the same message twice results in queue size 1 (deduplication).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_deduplication
async def test_deduplication(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    await queue.put(m)
    assert queue.qsize() == 1


# START_CONTRACT: test_item_done_tracking
#   PURPOSE: Verify that get adds to pending count and item_done removes it.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_item_done_tracking
async def test_item_done_tracking(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    got = await queue.get()
    assert queue.psize() == 1
    queue.item_done(got)
    assert queue.psize() == 0


# START_CONTRACT: test_item_done_allows_requeue
#   PURPOSE: Verify that after item_done the same message can be re-queued.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_item_done_allows_requeue
async def test_item_done_allows_requeue(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    got = await queue.get()
    queue.item_done(got)
    await queue.put(m)
    assert queue.qsize() == 1


# START_CONTRACT: test_psize_after_get
#   PURPOSE: Verify that psize reflects in-flight items after get.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_psize_after_get
async def test_psize_after_get(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    await queue.get()
    assert queue.psize() == 1


# START_CONTRACT: test_task_done_raises
#   PURPOSE: Verify that task_done raises NotImplementedError.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_task_done_raises
async def test_task_done_raises(queue: UniqueQueue) -> None:
    with pytest.raises(NotImplementedError, match="task_done"):
        queue.task_done()


# START_CONTRACT: test_dedup_by_id
#   PURPOSE: Verify that two UMessage instances with equal id dedup regardless of payload (id-only invariant).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_dedup_by_id
async def test_dedup_by_id(queue: UniqueQueue) -> None:
    await queue.put(UMessage(id="a", payload="x"))
    await queue.put(UMessage(id="a", payload="y"))
    assert queue.qsize() == 1


# START_CONTRACT: test_dedup_first_wins
#   PURPOSE: Verify that on a duplicate id the first-inserted message is retained (first-wins, not last-wins).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_dedup_first_wins
async def test_dedup_first_wins(queue: UniqueQueue) -> None:
    await queue.put(UMessage(id="a", payload="x"))
    await queue.put(UMessage(id="a", payload="y"))
    got = await queue.get()
    assert got.payload == "x"


# START_CONTRACT: test_unhashable_payload
#   PURPOSE: Verify that an unhashable payload (dict) is accepted through construct/put/get/item_done without raising.
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_unhashable_payload
# START_CONTRACT: test_put_race_full_queue
#   PURPOSE: Verify that concurrent puts of the same item on a full queue do not produce duplicates (check-then-act race fix).
#   INPUTS: { None }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: test_put_race_full_queue
async def test_put_race_full_queue() -> None:
    """Reproduce the check-then-act race: two concurrent put(Y) on a full maxsize=1 queue.

    With the fix (_put_lock), only one Y is ever enqueued — the second coroutine
    re-checks the dedup under the lock after the first completes.
    """
    q: UniqueQueue = UniqueQueue(name="test", maxsize=1)
    a = UMessage(id="a", payload="A")
    y = UMessage(id="y", payload="Y")

    await q.put(a)  # queue is now full (maxsize=1)

    # Track how many times _put is called (actual enqueue, not just put() entry)
    put_count: int = 0
    orig_put = q._put

    def counting_put(item: UMessage) -> None:  # type: ignore[type-arg]
        nonlocal put_count
        put_count += 1
        orig_put(item)

    q._put = counting_put  # type: ignore[assignment,method-assign]

    async def put_y() -> None:
        await q.put(y)

    task1 = asyncio.create_task(put_y())
    task2 = asyncio.create_task(put_y())

    # Yield control so both tasks start; task1 suspends in super().put() (queue full),
    # task2 blocks at _put_lock (task1 holds it).
    await asyncio.sleep(0)

    # Drain: get A wakes task1's putter -> task1 enqueues Y -> lock released
    # task2 acquires lock -> re-checks -> Y already in queue -> returns early
    got_a = await q.get()
    assert got_a == a
    got_y = await q.get()
    assert got_y == y

    await asyncio.gather(task1, task2)

    # Queue empty — no duplicate Y
    assert q.qsize() == 0
    # Exactly one _put call succeeded (the other was dedup'd under lock)
    assert put_count == 1

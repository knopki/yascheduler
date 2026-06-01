# FILE: tests/unit/test_queue.py
# VERSION: 1.0.0
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
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial queue unit tests
# END_CHANGE_SUMMARY

import pytest

from yascheduler.queue import UMessage, UniqueQueue


# START_CONTRACT: queue
#   PURPOSE: Fixture returning a UniqueQueue instance named "test".
#   INPUTS: { None }
#   OUTPUTS: { UniqueQueue - fresh queue instance }
#   SIDE_EFFECTS: None
#   LINKS: M-QUEUE
# END_CONTRACT: queue
@pytest.fixture
def queue():
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
async def test_put_get(queue) -> None:
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
async def test_deduplication(queue) -> None:
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
async def test_item_done_tracking(queue) -> None:
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
async def test_item_done_allows_requeue(queue) -> None:
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
async def test_psize_after_get(queue) -> None:
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
async def test_task_done_raises(queue) -> None:
    with pytest.raises(NotImplementedError, match="task_done"):
        queue.task_done()

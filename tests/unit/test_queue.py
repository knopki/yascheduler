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


@pytest.fixture
def queue():
    return UniqueQueue(name="test")


def msg(msg_id: str = "a", payload: str = "data") -> UMessage:
    return UMessage(id=msg_id, payload=payload)


async def test_put_get(queue):
    m = msg()
    await queue.put(m)
    result = await queue.get()
    assert result == m


async def test_deduplication(queue):
    m = msg()
    await queue.put(m)
    await queue.put(m)
    assert queue.qsize() == 1


async def test_item_done_tracking(queue):
    m = msg()
    await queue.put(m)
    got = await queue.get()
    assert queue.psize() == 1
    queue.item_done(got)
    assert queue.psize() == 0


async def test_item_done_allows_requeue(queue):
    m = msg()
    await queue.put(m)
    got = await queue.get()
    queue.item_done(got)
    await queue.put(m)
    assert queue.qsize() == 1


async def test_psize_after_get(queue):
    m = msg()
    await queue.put(m)
    await queue.get()
    assert queue.psize() == 1


async def test_task_done_raises(queue):
    with pytest.raises(NotImplementedError, match="task_done"):
        queue.task_done()

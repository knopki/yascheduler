# region MODULE_CONTRACT
# PURPOSE: Unit tests for UniqueQueue and UMessage covering deduplication, item lifecycle, and edge cases.
# SCOPE: put/get, deduplication, item_done tracking, psize, task_done NotImplementedError.
# KEYWORDS: UniqueQueue, UMessage, deduplication, psize
# endregion MODULE_CONTRACT

import asyncio

import pytest
import pytest_asyncio

from yascheduler.application.queue import UMessage, UniqueQueue


@pytest_asyncio.fixture
async def queue() -> UniqueQueue:
    return UniqueQueue(name="test")


def msg(msg_id: str = "a", payload: str = "data") -> UMessage:
    return UMessage(id=msg_id, payload=payload)


async def test_put_get(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    result = await queue.get()
    assert result == m


async def test_deduplication(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    await queue.put(m)
    assert queue.qsize() == 1


async def test_item_done_tracking(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    got = await queue.get()
    assert queue.psize() == 1
    queue.item_done(got)
    assert queue.psize() == 0


async def test_item_done_allows_requeue(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    got = await queue.get()
    queue.item_done(got)
    await queue.put(m)
    assert queue.qsize() == 1


async def test_psize_after_get(queue: UniqueQueue) -> None:
    m = msg()
    await queue.put(m)
    await queue.get()
    assert queue.psize() == 1


async def test_task_done_raises(queue: UniqueQueue) -> None:
    with pytest.raises(NotImplementedError, match="task_done"):
        queue.task_done()


async def test_dedup_by_id(queue: UniqueQueue) -> None:
    await queue.put(UMessage(id="a", payload="x"))
    await queue.put(UMessage(id="a", payload="y"))
    assert queue.qsize() == 1


async def test_dedup_first_wins(queue: UniqueQueue) -> None:
    await queue.put(UMessage(id="a", payload="x"))
    await queue.put(UMessage(id="a", payload="y"))
    got = await queue.get()
    assert got.payload == "x"


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


@pytest.mark.asyncio
async def test_dedup_on_node_id_not_ip() -> None:
    """Two UMessages with distinct NodeId but the same ip are both kept (NodeId-keyed dedup).

    UniqueQueue dedups on UMessage.id; with id == node.node_id (strictly unique
    SERIAL PK) two distinct nodes sharing an ip do NOT collapse to one entry —
    the rekey from ip (non-unique post migration 003) to NodeId is strictly
    stronger and prevents silent VM/row leaks.
    """
    from yascheduler.domain.model import Node, NodeId

    q: UniqueQueue[NodeId, Node] = UniqueQueue("deallocate_test", maxsize=10)

    node_a = Node(node_id=NodeId(1), hostname="10.0.0.9", ncpus=2, cloud="aws")
    node_b = Node(node_id=NodeId(2), hostname="10.0.0.9", ncpus=2, cloud="aws")

    await q.put(UMessage(node_a.node_id, node_a))
    await q.put(UMessage(node_b.node_id, node_b))

    assert q.qsize() == 2

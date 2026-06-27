## Context

`UniqueQueue` extends `asyncio.Queue` with message deduplication by ID. Its `put()` method does a check-then-act:

```python
async def put(self, item):
    if item in self._queue or item in self._done_pending:  # check (sync)
        return
    await super().put(item)                                 # act (may await)
```

When the queue is full, `super().put()` suspends via `await putter` (see `asyncio.Queue.put` — creates a Future, appends to `_putters`, awaits it). This creates a window where another coroutine can pass the same check before the first completes, enqueuing a duplicate.

Three of four orchestrator queues (`allocate_q`, `consume_q`, `deallocate_q`) have `maxsize=1` from `domain/settings.py`. At `maxsize=1`, the queue is full as soon as it has one item, so every `put` to a non-empty queue hits the suspend path — exposing the race window if concurrent puts ever occur.

## Goals / Non-Goals

**Goals:**
- Eliminate the race: `put()` must never enqueue a duplicate under any concurrency pattern
- Zero change to public API: callers use `put()` and `get()` the same way
- Minimal code change surface: one field + one method body

**Non-Goals:**
- Changing the single-producer-per-queue architecture in the orchestrator (the race is currently latent — a single coroutine calling `put` sequentially per `_create_producer_consumers` loop at `orchestrator.py:607` cannot hit it)
- Performance optimization for wide queues or many concurrent producers (3 of 4 queues have `maxsize=1`, each has one producer — contention structurally impossible)
- Replacing `asyncio.Queue` or changing queue architecture
- Thread safety (asyncio is single-threaded cooperative multitasking; lock is for coroutine-level mutual exclusion, not thread safety)

## Decisions

### Why fix a currently-latent race?

The race is **not reachable in production today**: each orchestrator queue has exactly one producer coroutine (`_create_producer_consumers` at `orchestrator.py:601-607`), calling `await queue.put(msg)` sequentially in a `async for` loop — no concurrent puts.

However, `UniqueQueue` is a reusable primitive in `yascheduler.application.queue`. Its class contract (documented: "skips duplicate messages by ID") is violated under concurrent put, regardless of whether current callers trigger it. The fix is defensive:
- Makes the class contract actually hold
- Prevents future bugs if concurrent put patterns are introduced
- Negligible cost: one `asyncio.Lock` per instance, used once per put cycle

### Lock over Inflight-set over `_put`-override

Four approaches were evaluated:

| Approach | Correct? | Complexity | Notes |
|---|---|---|---|
| **A: `asyncio.Lock`** in `put()` | ✅ Check+act atomically serialized | Low — 3 lines, std primitive | Serializes all puts, but with 1 producer per queue, zero practical contention |
| **B: Inflight set** (`_inflight` + `try/finally`) | ✅ Prevents duplicate suspension | Medium — 5 lines, extra set | Over-engineering for current workload |
| **C: Override `_put`** with dedup check | ❌ Breaks `put_nowait`/`join` accounting | High — deep `asyncio.Queue` internals | `put_nowait` increments `_unfinished_tasks` and wakes `_getters` regardless of whether `_put` actually stores the item; `join()` accounting breaks, consumers get spurious wakeups |
| **D: One-shot producer** (no concurrent put) | ✅ Architectural elimination | High — requires redesigning producers | Fixes symptom not cause; fragile to future changes |

**Decision: Option A (Lock)**.

Rationale:
- 3 of 4 queues have `maxsize=1` + single-producer loop → put calls are serial by producer iteration. Lock adds zero real contention beyond what queue full already imposes.
- Simplest correct fix. Fewer lines → less surface for new bugs.
- `asyncio.Lock` is stdlib, well-understood, cannot be forgotten in a `finally` (unlike inflight-set `discard`).

### Lock granularity: per-instance, not global

Each `UniqueQueue` instance gets its own `asyncio.Lock()` in `__init__` (not a class-level attribute — that would share one lock across all four queues). This keeps queues independent — contention on `allocate_q` never blocks `consume_q` puts.

### Test approach: concurrent put race

To prove the fix, the test must reproduce the exact scenario where two concurrent put coroutines are suspended inside `super().put()` while the queue is full. In asyncio, both tasks reach suspension when they `await` the putter future.

Test recipe:
1. Fill queue to `maxsize=1` with an item A
2. Create two concurrent coroutines trying to `put(Y)`:
   - t1: `put(Y)` → passes dedup check → `super().put(Y)` → full → `await putter` (SUSPENDED)
   - t2: `put(Y)` → passes dedup check (Y not in queue yet) → `super().put(Y)` → full → `await putter` (SUSPENDED)
   - Both now in `self._putters`, Y not yet enqueued
3. Consumer does `get()` → gets A → `_wakeup_next(self._putters)` → t1 resumes → `put_nowait(Y)` → Y enters queue
4. Consumer does `get()` → gets Y → `_wakeup_next(self._putters)` → t2 resumes → `put_nowait(Y)` → **duplicate Y** enters queue (race)

With fix (Lock): t2 blocks at `async with self._lock` before check, never reaching `_putters`. After t1 completes put, t2 acquires lock, re-checks, finds Y in `_queue`, returns early — t2 never reaches `super().put()`. Only one Y enqueued.

**Verification:**
- With fix: after two `get()` calls (A then Y), `q.qsize() == 0` and a counter of successful puts == 1
- Without fix: after two `get()` calls, a third `get()` returns Y again (duplicate); successful put count == 2

## Risks / Trade-offs

- **[Performance]** Lock serializes all `put` calls. Acceptable: 3 of 4 queues have `maxsize=1`, each has one producer, so contention is structurally impossible in practice. The `conn_machine_q` (maxsize=10) has one producer iterating sequentially — no parallel put sources.
- **[Deadlock]** `asyncio.Lock` is not reentrant, but `put` doesn't call itself or any internal method that calls `put`. No deadlock risk.
- **[Oversight in test]** Async race tests can be flaky if not properly synchronized. Mitigation: use explicit synchronization (events/futures) to guarantee both coroutines reach the race window, not `asyncio.sleep`-based heuristics.
- **[Future refactor]** If `put()` ever grows internal `async` calls besides `super().put()`, the lock must remain the outermost wrapper. Enforced by keeping the `async with` at method entry.

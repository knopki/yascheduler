## Why

`UniqueQueue.put` has a check-then-act race: duplicate items can be enqueued when the queue is full. Under full queue one coroutine suspends in `await super().put()` after passing the dedup check; another coroutine can pass the same check before the first completes, producing a duplicate. The bug affects all four orchestrator queues, especially `allocate_q`, `consume_q`, and `deallocate_q` which have `maxsize=1`.

This is a correctness bug — duplicates break the contract of `UniqueQueue` as a deduplicating queue and can cause the same task to be processed twice.

## What Changes

- Add `asyncio.Lock` to `UniqueQueue` to serialize the check-and-act in `put()`
- Add unit tests for concurrent put race under full queue
- No API changes, no new dependencies, no behavior changes for callers

## Capabilities

### New Capabilities

None — pure internal bug fix, no new capability introduced.

### Modified Capabilities

- `testing-unit`: Add concurrent-put scenario to the existing `UniqueQueue` requirement — dedup SHALL hold under concurrent `put()` on a full queue
- `testing-infrastructure`: Extend `UniqueQueue unit tests` requirement with a concurrent-put test case

## Impact

- `yascheduler/application/queue.py` — `UniqueQueue` class, one lock field + `put` method change
- `tests/unit/test_queue.py` — new tests for concurrent put race
- No public API or caller-visible contract changes
- No config or dependency changes

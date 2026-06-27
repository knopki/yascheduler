## Context

`Orchestrator._create_producer_consumers`
(`yascheduler/application/orchestrator.py:511-546`) runs each of the 4
daemon loops (connect / allocate / consume / deallocate) as a
producer-coroutine + N worker-coroutines pair:

```
async def _create_producer_consumers(self, queue, producer, consumer, n=1):
    async def worker():                      # 518
        while not self._cancellation_event.is_set():
            msg = await queue.get()          # 520  ← blocks indefinitely
            try: await consumer(msg)
            finally: queue.item_done(msg)

    workers = {asyncio.create_task(worker()) for _ in range(n)}   # 526-528
    try:
        while not self._cancellation_event.is_set():
            end_time = datetime.now() + timedelta(seconds=self._sleep_interval)
            try:
                async for msg in producer():     # 534  ← can raise
                    await queue.put(msg)
            finally:
                await _asleep_until(end_time)    # 537
    except asyncio.CancelledError:               # 538  ← ONLY catch
        if not queue.empty():
            await queue.join()
        for task in workers: task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
```

The producer coroutine is wrapped in `asyncio.create_task(...)` and added
to `self._bg_jobs` (lines 610/620/632/640). The worker tasks are NOT —
they live only in the local `workers: set`, lost on frame exit.

`start()` (596) ends with `_shutdown_barrier()` (586-587) =
`gather(*self._bg_jobs, return_exceptions=True)`. `return_exceptions=True`
means gather does not raise on a failed member and waits for all members,
so a dead producer coroutine does not crash the orchestrator — the other
loops keep running. `_print_stats` (185-222) is its own `bg_job` with the
same structural defect (DB + gateway reads inside its loop, no
`try/except`).

The consumers already follow a "swallow + log + keep alive" convention:
`_allocator_consumer` (344-363) wraps `allocate_task(...)` in
`try/except Exception as err: self._log.error(...)`, and its contract
comment says "swallow exceptions to keep the worker alive";
`_deallocator_consumer` (474-486) does the same. This design lifts that
convention one level up to the producer.

## Goals / Non-Goals

**Goals:**
- A producer that raises a non-`CancelledError` exception (DB timeout,
  gateway read error, `deallocate_nodes` write error) SHALL be logged
  and the loop SHALL continue on the next `_sleep_interval` tick. No
  silent subsystem death; self-healing from transient failures.
- `CancelledError` (graceful shutdown) SHALL still reach the existing
  `except asyncio.CancelledError` path so the worker drain (`queue.join`
  + cancel + `gather`) is preserved byte-for-byte.
- Worker tasks SHALL be reachable by `stop()`'s cancel cascade even if
  the parent coroutine exits via a `BaseException` that `except Exception`
  does not catch (`SystemExit`, `KeyboardInterrupt`).
- `_print_stats` SHALL get the same resilience treatment.

**Non-Goals:**
- A consecutive-failure counter / circuit breaker that escalates a
  permanently-failing producer to a terminal state. That is a separate
  behavior change (new operator-facing semantics) and gets its own
  proposal. The log line stays the operator signal, consistent with
  existing consumer-error logging.
- Persisting producer health across daemon restarts. The daemon restart
  itself is the recovery; no in-memory or DB state is introduced.
- Hardening `_await_first_machine` (557-577) — it has a 30s
  `asyncio.wait` timeout and explicit pending-task cleanup (571-576), so
  it cannot hang forever and is not part of the silent-death pattern.
- Changing the producer/consumer signatures, the queue contract, or the
  `_sleep_interval` tick. No public API change.

## Decisions

### Decision 1: Resilient producer via `try/except Exception` (not `finally`)

**Choice**: wrap `async for msg in producer():` in `try/except Exception`
inside the existing `while not cancellation_event.is_set():` loop. On a
caught `Exception`, log and fall through to the existing `finally: await
_asleep_until(end_time)` (537) so the next cycle retries after the normal
sleep interval.

```python
while not self._cancellation_event.is_set():
    end_time = datetime.now() + timedelta(seconds=self._sleep_interval)
    try:
        async for msg in producer():
            await queue.put(msg)
    except Exception as err:                       # NEW
        self._log.error(
            "[Orchestrator][_create_producer_consumers][PRODUCER_ERROR] "
            "queue=%s err=%s", queue.name, err
        )
    finally:
        await _asleep_until(end_time)
```

**Rationale**:
- `asyncio.CancelledError` is a `BaseException` (not `Exception`) since
  Python 3.8, so it propagates past `except Exception` and is caught by
  the existing `except asyncio.CancelledError` (538). Graceful-shutdown
  worker drain is unchanged.
- `self._sleep_interval` is `min(e.sleep_interval for e in engines)`,
  default ~10s, so recovery latency is bounded by one tick — same order
  as the producer's natural polling cadence.
- Architecturally symmetric with `_allocator_consumer` (361-362) and
  `_deallocator_consumer` (485-486), which already swallow-and-log to
  keep the worker alive. This lifts the convention to the producer level.

**Alternatives considered**:

- **A. Move worker cancel/gather into `finally`.** Rejected: it would run
  on EVERY producer error under Decision 1, cancelling workers that
  Decision 1 is keeping alive — actively harmful. Decision 1 supersedes A
  for the alive case; Decision 2 covers the dead case. Also, `finally`
  would run on graceful `CancelledError` exit too, duplicating the drain
  logic that already lives in `except CancelledError`.
- **B (original). `except Exception` only, no worker registration.**
  Rejected alone: leaves workers unreachable by `stop()` if the parent
  exits via `SystemExit`/`KeyboardInterrupt` (`BaseException`, not
  `Exception`). Adopted WITH Decision 2.
- **C. External watchdog that restarts failed producer coroutines.**
  Rejected: overengineering for a single-event-loop daemon; introduces a
  new subsystem, new failure modes, and duplicates what Decision 1
  achieves in ~5 lines.

### Decision 2: Register workers in `self._bg_jobs` (not a separate set)

**Choice**: add each worker task to `self._bg_jobs` (in addition to the
parent coroutine). `stop()` (651-665) already iterates `self._bg_jobs`
and cancels + awaits each.

**Rationale**:
- Workers ARE background jobs — they run for the daemon's lifetime.
  Reusing `self._bg_jobs` is the minimal change; no new field, no new
  iteration in `stop()`.
- `stop()` does `task.cancel()` then `await task` inside `try/except
  CancelledError: pass` (657-660). A worker blocked on `queue.get()`
  receives `CancelledError`, propagates it out of `worker()`, and is
  awaited cleanly. This matches the existing `except CancelledError`
  drain path's behavior (544-546), just triggered by `stop()` instead.
- The `return_exceptions=True` in `_shutdown_barrier`'s `gather`
  (586-587) already tolerates workers that exit with `CancelledError`.

**Alternatives considered**:
- **Separate `self._workers: set[asyncio.Task]` set.** Rejected: keeps
  producer-coroutines and workers separated for observability, but adds
  a new field, a new cancel loop in `stop()`, and a new `gather` — more
  surface for no behavioral gain. The `self._bg_jobs` reuse is strictly
  simpler.
- **Do nothing (Decision 1 alone).** Rejected: Decision 1 covers
  `Exception`, but a `BaseException` (`SystemExit`/`KeyboardInterrupt`)
  would still orphan workers. Decision 2 is cheap insurance.

### Decision 3: Same `try/except Exception` for `_print_stats`

**Choice**: wrap the body of `_print_stats` (185-222) in
`try/except Exception as err: self._log.error(...)`.

**Rationale**: `_print_stats` is a standalone `bg_job` (602) with the
identical silent-death defect — a DB read error or `gateway.list_connected()`
error kills the stats loop silently, and the daemon loses its primary
observability signal right when something is going wrong (the error that
killed stats likely indicates a broader problem). The same
swallow-and-continue treatment keeps stats alive across transient errors.

**Non-goal**: restructuring `_print_stats` to share a helper with the
producer loop. The two loops have different bodies (one yields messages,
one logs counts); a shared abstraction would not pull its weight (YAGNI).

## Risks / Trade-offs

- **Masking chronic producer failures** → a producer that errors on every
  cycle (e.g. DB permanently unreachable) now loops forever logging the
  same error every `_sleep_interval` instead of dying loudly. Mitigation:
  the log line is the operator signal, same as existing consumer-error
  logging; log volume from a 10s tick is bounded. A follow-up change can
  add a consecutive-failure counter that escalates, but that is a new
  behavior worth its own proposal (Non-Goal).
- **Worker registered in `_bg_jobs` double-cancels on `stop()`** →
  `stop()` (655-660) cancels the parent coroutine; the parent's `except
  CancelledError` (538) ALSO cancels workers (544-546). With Decision 2,
  workers are in `_bg_jobs`, so `stop()` cancels them directly too.
  Double-cancel is idempotent in asyncio (second `cancel()` is a no-op on
  an already-cancelled task). `await task` after double-cancel returns
  `CancelledError`, caught by `except CancelledError: pass` (659). No
  observable behavior change; verified by the worker-cancellation test.
- **`return_exceptions=True` in `_shutdown_barrier` hides worker exit
  errors** → unchanged from today; workers exit with `CancelledError`
  during shutdown, which `return_exceptions=True` swallows. This is the
  desired behavior for graceful shutdown.
- **Decision 2 increases `_bg_jobs` size** → from 5 (4 producers + stats)
  to 5 + sum(workers_num across 4 loops). `stop()`'s cancel loop is O(N)
  in the number of jobs; the increase is bounded by configured
  concurrency limits (default 1 per loop). Negligible.

## Migration Plan

No data migration. Deployment is a code rollout:

1. Merge the change; producers now swallow-and-recover; workers are
   registered in `_bg_jobs`.
2. Existing daemons with a silently-dead subsystem: a rolling restart
   picks up the new code AND restarts the dead subsystem. No special
   operator action.
3. Rollback: revert the commit; old behavior (silent death on producer
   error) resumes. No DB residue, no config change.

## Open Questions

- None outstanding. The brief's open questions are all resolved:
  consecutive-failure counter → Non-Goal; `_await_first_machine` →
  Non-Goal; worker registration location → Decision 2 (`self._bg_jobs`);
  test surface → Impact section of proposal + tasks.
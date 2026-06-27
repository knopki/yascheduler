# Explore Brief — fix-orchestrator-producer-silent-death

## Problem (confirmed)

A producer error that is NOT `asyncio.CancelledError` exits
`_create_producer_consumers` (`orchestrator.py:511-546`) because the only
`except` clause is `except asyncio.CancelledError` (538). The orphaned worker
tasks (526-528), blocked on `await queue.get()` (520), are not in
`self._bg_jobs` (only the parent coroutine is, via 610/620/632/640) and the
local `workers: set` reference is lost on frame exit — but the event loop
keeps a strong reference to live `asyncio.Task`s, so they persist as zombies
until the loop closes. `stop()` (651-665) only cancels `self._bg_jobs`, so it
never reaches the zombies; the workers only die when the loop itself is torn
down (after `stop()`).

`start()` (596) does NOT crash: `_shutdown_barrier` (586-587) calls
`gather(*self._bg_jobs, return_exceptions=True)`. `return_exceptions=True`
keeps gather alive across one failed task, so the other loops keep running
and `_print_stats` keeps writing logs → the daemon looks alive while one or
more subsystems (allocate / consume / connect / deallocate) silently died.

All 4 producers raise non-Cancelled exceptions on real failures:

| Producer                        | Failure sources                                                |
| ------------------------------- | -------------------------------------------------------------- |
| `_allocator_producer` (322)       | `_clouds_get_capacity`→`uow.nodes.list_all()`; `uow.tasks.list_by_status({TO_DO})` |
| `_connect_machine_producer` (224) | `uow.nodes.list_enabled()`                                       |
| `_task_consumer_producer` (365)   | `uow.tasks.list_by_status({RUNNING})`                            |
| `_deallocator_producer` (444)     | `deallocate_nodes(...)` (DB r/w); `gateway.list_connected()`     |

A single transient SQL timeout kills the subsystem until daemon restart.

`_print_stats` (185-222) has the same structural defect (it reads DB and
gateway counts inside its own loop) — also dies silently on a DB error.

## Rejected alternatives

- **A. Move worker cancel/gather to `finally`.** Fixes zombies, does NOT fix
  silent death (subsystem still dead until daemon restart). Redundant once B
  is adopted, since the resilient producer keeps the parent coroutine alive
  and the `except CancelledError` path stays intact for graceful shutdown.
- **E. External watchdog / health-check that restarts failed producers.**
  Overengineering for a daemon with one event loop; introduces a new
  subsystem, new failure modes, and duplicates what B achieves in ~5 lines.

## Selected approach

**B. Resilient producer loop**: wrap `async for msg in producer()` in
`try/except Exception` inside the existing `while not
cancellation_event.is_set()` loop. `asyncio.CancelledError` is a
`BaseException` (not `Exception`) since Python 3.8, so it propagates past
the `except Exception` and is caught by the existing `except
CancelledError` (538) → graceful worker drain unchanged. On a caught
`Exception`, log and fall through to the existing `finally: await
_asleep_until(end_time)` (536-537) → next cycle retries. Self-healing: a
transient DB blip is recovered on the next `_sleep_interval` tick.

**Plus C (defensive, cheap)**: register worker tasks in `self._bg_jobs` (or a
dedicated `self._workers` set tracked across the instance) so `stop()`'s
cancel cascade reaches them even if some future code path lets the parent
coroutine exit without cancelling them. Belt-and-suspenders against B ever
regressing.

**Why not B alone for workers**: B keeps the parent coroutine alive, so
zombies aren't created in the normal case. But if a future change re-raises
something non-Exception/non-Cancelled (e.g. `SystemExit`, `KeyboardInterrupt`
— both `BaseException`), the parent would die and B's `except Exception`
wouldn't catch it. Registering workers gives `stop()` a guaranteed reach.

**Why not A + B**: A's `finally` cancel/gather would run on EVERY producer
error under B, cancelling workers that B is trying to keep alive — actively
harmful. B supersedes A for the alive case; C covers the dead case.

## Scope of the fix

- Primary target: `_create_producer_consumers` (4 producer-consumer loops).
- Secondary target: `_print_stats` — same structural defect, same fix shape
  (try/except Exception around the DB/gateway reads, log and let the loop
  continue). It's a standalone bg_job, not a producer-consumer, but the
  silent-death pattern is identical.

## Cross-module data flow (unchanged)

```
start() (596)
  ├─ _bg_jobs.add(_print_stats)                       ← secondary fix
  ├─ _bg_jobs.add(_create_producer_consumers(conn))   ← primary fix
  ├─ _await_first_machine()
  ├─ _bg_jobs.add(_create_producer_consumers(alloc))  ← primary fix
  ├─ _bg_jobs.add(_create_producer_consumers(consume))← primary fix
  ├─ _bg_jobs.add(_create_producer_consumers(dealloc))← primary fix
  └─ _shutdown_barrier()  ← gather(*_bg_jobs, return_exceptions=True)

_create_producer_consumers(queue, producer, consumer, n)
  workers = {create_task(worker()) × n}   ← register in self._bg_jobs (fix C)
  while not cancellation_event.is_set():
    end_time = now + sleep_interval
    try:
      async for msg in producer():       ← wrap in try/except Exception (fix B)
        await queue.put(msg)
    except Exception as err:             ← NEW
      log.error(...)
    finally:
      await _asleep_until(end_time)
  except CancelledError:                  ← unchanged (graceful drain)
    queue.join(); cancel workers; gather

stop() (651-665)
  cancellation_event.set()
  for task in _bg_jobs: cancel + await    ← now reaches workers too (fix C)
```

## Mapping to existing patterns

- `_allocator_consumer` (344-363) already wraps `allocate_task(...)` in
  `try/except Exception as err: self._log.error(...)` — contract comment says
  "swallow exceptions to keep the worker alive". B applies the SAME pattern
  one level up, to the producer. Architecturally symmetric.
- `_deallocator_consumer` (474-486) does the same. Two precedents in the
  same file → B is consistent with established convention.

## Open questions

1. Whether to also harden `_await_first_machine` (557-577) — it has a 30s
   timeout via `asyncio.wait` and its own pending-task cleanup, so it's
   structurally safer; out of scope for this change unless review flags it.
2. Whether a producer that errors on every single cycle (e.g. DB
   permanently gone) should eventually escalate beyond logging. YAGNI for
   this change — the log line is the operator signal, same as existing
   consumer-error logging. A follow-up could add a consecutive-failure
   counter that flips to a hard-fail after N cycles, but that's a new
   behavior worth its own proposal.
3. Where to register workers for fix C: reuse `self._bg_jobs` (simplest,
   `stop()` already iterates it) vs a separate `self._workers` set (keeps
   producer-coroutines and workers cleanly separated for observability).
   Leaning toward `self._bg_jobs` for minimal change — workers ARE
   background jobs. Confirm in design.
4. Test surface: `_create_producer_consumers` and `worker` have ⚠️ no
   covering tests (per codegraph). This change should add the first unit
   tests for the producer-error-resilience behavior.
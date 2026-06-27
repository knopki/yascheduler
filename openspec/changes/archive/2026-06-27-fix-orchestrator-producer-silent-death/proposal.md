## Why

A producer error inside `_create_producer_consumers`
(`yascheduler/application/orchestrator.py:511-546`) that is not an
`asyncio.CancelledError` exits the parent coroutine: the only `except`
clause (line 538) catches `CancelledError` alone. The orphaned worker tasks
(blocked on `await queue.get()` at line 520) are not registered in
`self._bg_jobs` (only the parent coroutine is, via lines 610/620/632/640),
the local `workers: set` reference is lost on frame exit, and the event
loop retains live `asyncio.Task`s as zombies. `start()`
(`_shutdown_barrier`, line 586-587) uses `gather(*self._bg_jobs,
return_exceptions=True)`, so the orchestrator does not crash — the other
loops keep running and `_print_stats` keeps writing logs. The daemon looks
alive while one or more subsystems (allocate / consume / connect /
deallocate) silently died until manual restart.

All four producers raise non-`CancelledError` exceptions on real failures
(DB timeout in `list_by_status` / `list_enabled` / `list_all`,
`gateway.list_connected()` error, `deallocate_nodes` write error), so a
single transient SQL timeout is enough to kill a subsystem for the
daemon's lifetime.

## What Changes

- Wrap the `async for msg in producer():` call inside
  `_create_producer_consumers` in a `try/except Exception` so a producer
  failure is logged and the loop continues on the next `_sleep_interval`
  tick (self-healing). `asyncio.CancelledError` is a `BaseException` (not
  `Exception`) since Python 3.8, so graceful shutdown still propagates to
  the existing `except CancelledError` (line 538) and the worker drain
  stays unchanged.
- Register worker tasks created in `_create_producer_consumers` in
  `self._bg_jobs` (in addition to the parent coroutine) so `stop()`'s
  cancel cascade (lines 655-660) reaches them even if the parent exits
  via a `BaseException` that `except Exception` does not catch
  (`SystemExit`, `KeyboardInterrupt`). Defensive belt-and-suspenders
  against future regressions.
- Apply the same `try/except Exception` resilience to `_print_stats`
  (lines 185-222), which has the identical silent-death defect (it reads
  DB and gateway counts inside its own standalone `bg_job` loop).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `orchestrator`: add a "Producer error resilience" requirement covering
  the `try/except Exception` recovery contract in
  `_create_producer_consumers` and `_print_stats`, plus the worker-task
  registration in `self._bg_jobs` so `stop()` cancels them. Adds
  scenarios for transient producer error recovery, `CancelledError`
  graceful-shutdown preservation, and worker cancellation on shutdown.

## Impact

- **Code**:
  - `yascheduler/application/orchestrator.py` —
    `_create_producer_consumers` gains `try/except Exception` around the
    `async for msg in producer():` block and registers workers in
    `self._bg_jobs`; `_print_stats` gains `try/except Exception` around
    its body. `Orchestrator.__init__` is unchanged (the existing
    `self._bg_jobs: set[asyncio.Task[None]]` is reused).
- **Public surface**: none. No CLI, INI, DB-schema, AiiDA-plugin, or
  `class Yascheduler` public API change. The fix is internal to
  `Orchestrator`'s private methods.
- **Dependencies / schema**: none. No migration, no new dependency.
- **Callers**: `start()` / `stop()` are the only callers of the affected
  private methods; their signatures are unchanged.
- **Tests**: unit tests for producer-error recovery (producer raises
  `Exception` → loop continues next tick; producer raises
  `CancelledError` → graceful drain path preserved) and for worker
  cancellation on `stop()`. `_create_producer_consumers` and `worker`
  currently have no covering tests (per codegraph); this change adds the
  first.
- **GRACE-lite**: `M-APPLICATION-ORCHESTRATOR` annotations updated for
  the resilient producer behavior and worker registration; no new module
  record, no new `CrossLink` (no new inter-module dependency — the fix is
  intra-module). `CHANGE_SUMMARY` entry added.
- **Out of scope**: adding a consecutive-failure counter that escalates
  a permanently-failing producer to a hard-fail / terminal state — that
  is a separate behavior change worth its own proposal. The log line
  remains the operator signal, consistent with existing consumer-error
  logging in `_allocator_consumer` / `_deallocator_consumer`.
- **Out of scope**: hardening `_await_first_machine` (lines 557-577) — it
  has a 30s timeout via `asyncio.wait` and its own pending-task cleanup,
  so it is structurally safer; not touched.
- **Relationship to active changes**: `fix-never-connected-node-leak`
  modifies `_connect_machine_consumer` and adds `abandon_node.py`;
  `fix-download-rmtree-data-loss` and `schema-migrations` touch disjoint
  files. None of them modify `_create_producer_consumers`'s error
  handling or `_print_stats`, so this change does not conflict.
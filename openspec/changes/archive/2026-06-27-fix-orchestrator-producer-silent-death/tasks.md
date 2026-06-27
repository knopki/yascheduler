## 1. Resilient producer in `_create_producer_consumers`

- [x] 1.1 In `yascheduler/application/orchestrator.py`, wrap the `async for msg in producer():` block inside `_create_producer_consumers` (currently lines 534-535) in a `try/except Exception as err:` that logs `"[Orchestrator][_create_producer_consumers][PRODUCER_ERROR] queue=%s err=%s", queue.name, err` and falls through to the existing `finally: await _asleep_until(end_time)` (line 537) so the next cycle retries. Place a `START_BLOCK_PRODUCER_RESILIENCE` / `END_BLOCK_PRODUCER_RESILIENCE` marker pair around the new try/except
- [x] 1.2 Verify the existing `except asyncio.CancelledError` (line 538) still catches `CancelledError` — confirm `asyncio.CancelledError` is NOT caught by the new `except Exception` (it is a `BaseException` since Python 3.8, and the repo requires `>=3.9` per `pyproject.toml`); add a one-line code comment above `except Exception` noting this so a future reader does not "broaden" it to `except BaseException`
- [x] 1.3 Add a `START_CONTRACT: Orchestrator._create_producer_consumers` block (if missing) or update the existing one to document the resilience behavior in PURPOSE/SIDE_EFFECTS/LINKS; ensure the contract states that `CancelledError` propagates past `except Exception` to the graceful-drain `except CancelledError`

## 2. Register workers in `self._bg_jobs`

- [x] 2.1 In `_create_producer_consumers`, after `workers.add(asyncio.create_task(worker()))` (lines 527-528), add each worker to `self._bg_jobs` so `stop()`'s cancel cascade (lines 655-660) reaches them; keep the local `workers: set` for the `except CancelledError` drain path (lines 544-546) unchanged — both the local set and `self._bg_jobs` now reference the workers, which is safe (double-cancel is idempotent in asyncio)
- [x] 2.2 Add a `START_BLOCK_REGISTER_WORKERS` / `END_BLOCK_REGISTER_WORKERS` marker pair around the worker-registration loop
- [x] 2.3 Verify `stop()` (lines 651-665) needs NO change — it already iterates `self._bg_jobs` and does `task.cancel()` + `await task` inside `except asyncio.CancelledError: pass`; confirm a worker blocked on `await queue.get()` receives `CancelledError` and is awaited cleanly

## 3. Resilient `_print_stats`

- [x] 3.1 In `_print_stats` (lines 185-222), wrap the body that reads DB and gateway counts in a `try/except Exception as err:` that logs `"[Orchestrator][_print_stats][ERROR] err=%s", err` and lets the loop continue on its next tick; preserve the existing `await asyncio.sleep(...)` cadence
- [x] 3.2 Add a `START_BLOCK_STATS_RESILIENCE` / `END_BLOCK_STATS_RESILIENCE` marker pair around the try/except
- [x] 3.3 Update the existing `START_CONTRACT: Orchestrator._print_stats` block (if present) or add one documenting that transient errors are logged and the loop continues

## 4. GRACE-lite module markup

- [x] 4.1 In `orchestrator.py`, update `START_MODULE_CONTRACT` to mention the producer-error resilience and worker registration in SCOPE; update `START_MODULE_MAP` if any new exported symbol appears (none expected — changes are to existing private methods)
- [x] 4.2 Add a `START_CHANGE_SUMMARY` entry for this change (e.g. `LAST_CHANGE: v6.3.0 - Producer-error resilience: _create_producer_consumers and _print_stats now catch Exception, log, and continue on next tick; workers registered in self._bg_jobs so stop() cancels them. CancelledError still reaches the graceful-drain path.`); move the current `LAST_CHANGE` to `PREVIOUS_CHANGE`
- [x] 4.3 Bump `VERSION` in the `orchestrator.py` file header per repo convention (current is `6.2.0` → `6.3.0`)
- [x] 4.4 Update `docs/knowledge-graph.xml`: add `<fn-_create_producer_consumers PURPOSE="Run resilient producer-consumer loop with worker registration" />` (or update the existing annotation if present) and `<fn-_print_stats PURPOSE="Periodic stats with transient-error resilience" />` annotations to `M-APPLICATION-ORCHESTRATOR`; no new module record, no new `CrossLink` (the fix is intra-`M-APPLICATION-ORCHESTRATOR`, no new inter-module dependency)
- [x] 4.5 Run `python3 scripts/grace_check.py` and confirm exit 0

## 5. Unit tests — producer resilience

- [x] 5.1 Create `tests/unit/test_orchestrator_producer_resilience.py` (or extend an existing `tests/unit/test_orchestrator*.py` if present) with a `FILE` / `VERSION` / `START_MODULE_CONTRACT` / `START_MODULE_MAP` header per GRACE-lite (DEPENDS: M-APPLICATION-ORCHESTRATOR; LINKS: M-QUEUE)
- [x] 5.2 Add `test_producer_exception_continues_loop`: stub `producer()` to raise `RuntimeError` on first call and yield a message on second call; assert the loop continues, the second producer invocation runs, and the error was logged (use `caplog`)
- [x] 5.3 Add `test_producer_cancellederror_preserves_drain`: stub `producer()` to raise `asyncio.CancelledError`; assert the existing `except CancelledError` drain path fires (`queue.join()` called, workers cancelled) and the producer-error `except Exception` did NOT swallow it
- [x] 5.4 Add `test_workers_registered_in_bg_jobs`: after constructing an `Orchestrator` and starting one `_create_producer_consumers` pair, assert `self._bg_jobs` contains both the parent coroutine task AND the worker tasks (count = 1 + `workers_num`)
- [x] 5.5 Add `test_stop_cancels_workers`: start a producer-consumer pair with a producer that never yields and a consumer that never returns; call `stop()`; assert all worker tasks are cancelled (`.cancelled()` is True or they raised `CancelledError`)
- [x] 5.6 Add `test_double_cancel_is_idempotent`: trigger both `stop()`'s cancel and the parent's `except CancelledError` drain cancel on the same worker; assert no `RuntimeError` / `InvalidStateError` is raised and the worker is awaited exactly once

## 6. Unit tests — stats resilience

- [x] 6.1 Add `test_print_stats_exception_continues_loop`: stub `uow.tasks.count_by_status()` (or `gateway.list_connected()`) to raise `RuntimeError` on first call and succeed on second; assert the stats loop continues to its next tick and the error was logged
- [x] 6.2 Add `test_print_stats_cancellederror_still_propagates`: stub a DB read to raise `asyncio.CancelledError`; assert the `CancelledError` propagates out of `_print_stats` (not swallowed by `except Exception`) so the shutdown path is preserved

## 7. Static checks and validation

- [x] 7.1 `uv run ruff check .` passes
- [x] 7.2 `uv run ruff format --check .` passes
- [x] 7.3 `uv run lint-imports` passes
- [x] 7.4 `uv run zuban check` passes
- [x] 7.5 `uv run pytest -m unit` passes (focused on the new `test_orchestrator_producer_resilience` and stats-resilience tests)
- [x] 7.6 `openspec validate fix-orchestrator-producer-silent-death --json` reports `valid: true`
- [x] 7.7 `openspec validate --all --json` passes (no regressions to the existing `orchestrator` spec from the ADDED requirement)
- [x] 7.8 Run `rg "except BaseException" yascheduler/application/orchestrator.py` and confirm zero matches (enforces that the new `except Exception` was not accidentally broadened — the spec's "producer-error handler SHALL NOT run on graceful shutdown" scenario)
- [x] 7.9 Run `rg "_bg_jobs" yascheduler/application/orchestrator.py` and confirm workers are added to `self._bg_jobs` inside `_create_producer_consumers` (enforces the spec's "Workers are cancelled on shutdown" scenario)
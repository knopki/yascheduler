## ADDED Requirements

### Requirement: Orchestrator.stop is idempotent and exception-safe

`Orchestrator.stop()` (`yascheduler/application/orchestrator.py`) SHALL be idempotent: the cleanup body SHALL execute exactly once across concurrent, interleaved, or repeated invocations (e.g. a signal handler calling `stop()` followed by a `try/finally` in `run_daemon` calling `stop()` again, or two signals arriving).

A `_stopped` boolean guard SHALL be initialized to `False` in `__init__`. At the top of `stop()`, the guard SHALL be checked and set with no `await` between the check and the set (atomic in single-threaded asyncio). If the guard is already `True`, `stop()` SHALL return immediately without re-running the cleanup body.

`Orchestrator.stop()` SHALL be exception-safe across two failure modes:

1. **Background job pre-death.** When awaiting a cancelled background job in the per-task loop, `stop()` SHALL catch both `asyncio.CancelledError` (graceful shutdown, existing behavior) and `Exception` (a job that died with a non-`CancelledError` before shutdown, e.g. a `pg8000.Error` from a DB outage). `asyncio.CancelledError` is a `BaseException` (not `Exception`) since Python 3.8, and the repo requires `>=3.9`, so the two `except` clauses SHALL be distinct and non-overlapping. A non-`CancelledError` exception from a dead background job SHALL be logged and SHALL NOT abort the cleanup chain.

2. **Cleanup step isolation.** Each cleanup step — `await self._clouds.stop()`, `await self._gateway.disconnect_all()`, and the `http_session.close()` block — SHALL be wrapped in its own `try/except Exception` so a failure in one step (logged at `warning`) does not skip the remaining steps. `self._http_session` SHALL be set to `None` after a successful or failed `close()` so a repeated invocation cannot close an already-closed session.

The existing graceful-shutdown drain semantics (the `for task in self._bg_jobs: task.cancel(); await task` loop and the `_cancellation_event.set()`) SHALL be preserved.

#### Scenario: stop() runs cleanup body exactly once
- **WHEN** `orch.stop()` is called twice (sequentially, interleaved at an await boundary, or from two independent coroutines on the same event loop)
- **THEN** the cleanup body (`_cancellation_event.set()`, cancel bg jobs, `clouds.stop()`, `gateway.disconnect_all()`, `http_session.close()`) executes exactly once; the second and subsequent invocations return immediately as a no-op

#### Scenario: signal handler then finally no-op
- **WHEN** a SIGTERM/SIGINT handler calls `orch.stop()` (first execution, body runs and closes resources) and `run_daemon`'s `finally` block subsequently calls `orch.stop()` again
- **THEN** the second invocation sees `_stopped == True` and returns immediately; `http_session.close()` is NOT called a second time on the already-closed session

#### Scenario: dead background job does not abort cleanup
- **WHEN** a background job in `self._bg_jobs` has already terminated with a non-`CancelledError` exception (e.g. `pg8000.Error`) before `orch.stop()` is called, and `stop()` awaits the cancelled (already-done) task
- **THEN** the `except Exception` clause catches the re-raised exception, logs it, and `stop()` proceeds to `self._clouds.stop()`, `self._gateway.disconnect_all()`, and `self._http_session.close()` — the cleanup chain is NOT aborted by the dead job

#### Scenario: CancelledError still reaches the graceful-drain path
- **WHEN** `orch.stop()` cancels a background job that is still running and the job raises `asyncio.CancelledError`
- **THEN** the existing `except asyncio.CancelledError: pass` clause catches it (the new `except Exception` does NOT catch `CancelledError` because it is a `BaseException`), and the graceful-drain semantics are preserved

#### Scenario: failing clouds.stop does not skip disconnect and http close
- **WHEN** `await self._clouds.stop()` raises an `Exception` during `orch.stop()`
- **THEN** the `try/except Exception` around `clouds.stop()` logs the failure at `warning`, and `stop()` proceeds to `await self._gateway.disconnect_all()` and the `http_session.close()` block — the SSH connections and HTTP session are still closed despite the cloud-step failure

#### Scenario: failing gateway.disconnect_all does not skip http close
- **WHEN** `await self._gateway.disconnect_all()` raises an `Exception` during `orch.stop()`
- **THEN** the `try/except Exception` around `gateway.disconnect_all()` logs the failure at `warning`, and `stop()` proceeds to the `http_session.close()` block — the HTTP session is still closed despite the gateway-step failure

#### Scenario: http_session nulled after close
- **WHEN** `orch.stop()` closes `self._http_session` (whether `close()` succeeds or raises)
- **THEN** `self._http_session` is set to `None` after the `close()` attempt, so a subsequent `stop()` invocation that somehow bypassed the `_stopped` guard (defense in depth) would see `None` and skip `close()`

#### Scenario: stop() called before start() is a safe no-op
- **WHEN** `orch.stop()` is called before `orch.start()` has been called (e.g. `make_daemon` returns and a signal arrives before `start()`)
- **THEN** the `_stopped` guard is set, `_cancellation_event.set()` runs, the empty `self._bg_jobs` loop is a no-op, `clouds.stop()`/`gateway.disconnect_all()`/`http_session.close()` run on empty/idle resources, and no error is raised

#### Scenario: interleaved stop() calls are serialized by the guard
- **WHEN** two coroutines on the same event loop both call `orch.stop()` and the first call has reached an `await` point inside the cleanup body (e.g. mid-`await self._clouds.stop()`) when the second call begins
- **THEN** the second call sees `_stopped == True` (the guard was set synchronously at the top of the first call, before any `await`) and returns immediately as a no-op, while the first call continues and completes the remaining cleanup steps; the cleanup body still executes exactly once
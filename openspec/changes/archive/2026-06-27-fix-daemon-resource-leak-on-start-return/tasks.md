## 1. Harden `Orchestrator.stop()` — guard + exception safety

- [x] 1.1 In `yascheduler/application/orchestrator.py` `Orchestrator.__init__` (after the `self._connect_failures: dict[str, float] = {}` line, currently line 141), add `self._stopped: bool = False` with a one-line comment noting it is the single-execution guard for `stop()` (set synchronously at the top of `stop()`, no `await` between check and set — atomic in single-threaded asyncio)
- [x] 1.2 In `Orchestrator.stop()` (currently lines 729-743), add the guard at the very top: `if self._stopped: return` then `self._stopped = True` on the next line, BEFORE `self._log.info("Stopping...")`. No `await` may appear between the check and the set. Wrap the guard in a `START_BLOCK_STOP_GUARD` / `END_BLOCK_STOP_GUARD` marker pair
- [x] 1.3 In the per-task loop of `stop()` (currently lines 733-738), add an `except Exception as e:` clause AFTER the existing `except asyncio.CancelledError: pass` that logs `self._log.debug("[Orchestrator][stop][BG_JOB_ENDED] %s", e)` — this catches a bg job that died with a non-CancelledError before shutdown (now includes worker tasks registered in `_bg_jobs` by the sibling change `fix-orchestrator-producer-silent-death`). Add a one-line code comment above `except Exception` noting that `CancelledError` is `BaseException` (not `Exception`) since Python 3.8 so the two clauses do not overlap (repo requires `>=3.9`). Wrap in `START_BLOCK_STOP_AWAIT_JOBS` / `END_BLOCK_STOP_AWAIT_JOBS`
- [x] 1.4 Wrap `await self._clouds.stop()` (currently line 740) in its own `try/except Exception as e:` logging `self._log.warning("[Orchestrator][stop][CLOUDS_STOP_FAILED] %s", e)`. Wrap in `START_BLOCK_STOP_CLOUDS` / `END_BLOCK_STOP_CLOUDS`
- [x] 1.5 Wrap `await self._gateway.disconnect_all()` (currently line 741) in its own `try/except Exception as e:` logging `self._log.warning("[Orchestrator][stop][DISCONNECT_ALL_FAILED] %s", e)`. Wrap in `START_BLOCK_STOP_GATEWAY` / `END_BLOCK_STOP_GATEWAY`
- [x] 1.6 Wrap the `if self._http_session is not None:` block (currently lines 742-743): `try: await self._http_session.close() except Exception as e: self._log.warning("[Orchestrator][stop][HTTP_CLOSE_FAILED] %s", e)` then `self._http_session = None` AFTER the try/except (set to None whether close succeeded or failed). Wrap in `START_BLOCK_STOP_HTTP` / `END_BLOCK_STOP_HTTP`
- [x] 1.7 Update the `START_CONTRACT: Orchestrator.stop` block (currently lines 723-728): change `SIDE_EFFECTS` to "Cancels bg jobs (tolerant of jobs that died with a non-CancelledError before shutdown — includes worker tasks registered in `_bg_jobs`), disconnects machines, stops clouds, closes http_session; idempotent — the cleanup body runs exactly once across concurrent/interleaved/repeated callers via a `_stopped` guard; each cleanup step is isolated so one failing step does not skip the others; `http_session` is nulled after close"; add a line to `LINKS` noting the guard + isolation contract

## 2. Wrap `run_daemon`'s `orch.start()` in `try/finally`

- [x] 2.1 In `yascheduler/entrypoints/cli/daemon_common.py` `run_daemon` (currently lines 121-123), replace the bare `await orch.start()` (wrapped in `START_BLOCK_START_ORCHESTRATOR` / `END_BLOCK_START_ORCHESTRATOR`) with a `try/finally` construct. Rename the markers to `START_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP` / `END_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP` so the entire `try/finally` (both `try: await orch.start()` and `finally: await orch.stop()`) is inside one marker pair — do not split the `try` body from its `finally` clause across marker boundaries. The result: `# START_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP` / `try:` / `    await orch.start()` / `finally:` / `    await orch.stop()` / `# END_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP`
- [x] 2.2 Update the `START_CONTRACT: run_daemon` block (lines 69-75): change `SIDE_EFFECTS` to add "guarantees `orch.stop()` runs on any exit path (normal `start()` return, `start()` exception, signal) via `try/finally` — the signal handler's `stop()` is the first execution; the `finally`'s `stop()` is a no-op (idempotent per the orchestrator contract)"; keep `OUTPUTS` as `None - runs the event loop until stopped`

## 3. GRACE-lite module markup

- [x] 3.1 In `orchestrator.py`, update `START_MODULE_CONTRACT` SCOPE to mention `stop()` idempotency and exception-safe cleanup; update `START_MODULE_MAP` if any new exported symbol appears (none expected — `_stopped` is private)
- [x] 3.2 In `orchestrator.py`, add a `START_CHANGE_SUMMARY` entry: `LAST_CHANGE: v<new> - stop() idempotent and exception-safe: _stopped guard for single execution, except Exception on await task (dead-job tolerance), per-step try/except isolation, http_session nulled after close.`; move the current `LAST_CHANGE` to `PREVIOUS_CHANGE`. Bump `VERSION` in the file header per repo convention
- [x] 3.3 In `daemon_common.py`, update `START_MODULE_CONTRACT` SCOPE to mention the `try/finally` cleanup guarantee; update `START_CHANGE_SUMMARY` with the new `LAST_CHANGE` and move the current one to `PREVIOUS_CHANGE`; bump `VERSION`
- [x] 3.4 Update `docs/knowledge-graph.xml` `M-APPLICATION-ORCHESTRATOR` `<annotations>`: update `fn-stop` PURPOSE to "Idempotent exception-safe cleanup: single-execution guard, per-step isolation, http_session nulling"; update `M-DAEMON-COMMON` `<annotations>` `fn-run_daemon` PURPOSE to mention the `try/finally` cleanup guarantee. No new module record, no new `CrossLink` (changes are intra-module)
- [x] 3.5 Run `python3 scripts/grace_check.py` and confirm exit 0

## 4. Unit tests — `Orchestrator.stop()` idempotency and exception safety

- [x] 4.1 Create `tests/unit/test_orchestrator_stop_idempotent.py` with a `FILE` / `VERSION` / `START_MODULE_CONTRACT` / `START_MODULE_MAP` header per GRACE-lite (DEPENDS: M-APPLICATION-ORCHESTRATOR; LINKS: M-DOMAIN-PORTS, M-CLOUD-PROVISIONER)
- [x] 4.2 `test_stop_runs_cleanup_body_once`: call `orch.stop()` twice sequentially; assert via mocks that `clouds.stop()`, `gateway.disconnect_all()`, and `http_session.close()` were each called exactly once and `http_session` was nulled after the first call
- [x] 4.3 `test_stop_interleaved_calls_serialized_by_guard`: call `orch.stop()` from two coroutines on the same loop where the first call's `clouds.stop()` mock awaits once before completing; assert the second call returns as a no-op (cleanup steps called exactly once total) and the first call completes all cleanup steps
- [x] 4.4 `test_stop_dead_bg_job_does_not_abort_cleanup`: add a task to `_bg_jobs` that has already terminated with `RuntimeError` (use `asyncio.create_task` on a coroutine that raises); call `stop()`; assert the re-raised `RuntimeError` is caught (logged at debug), and `clouds.stop()`/`disconnect_all()`/`http_session.close()` are still called
- [x] 4.5 `test_stop_cancellederror_preserves_drain`: add a running task to `_bg_jobs` that raises `CancelledError` on cancel; call `stop()`; assert the existing `except CancelledError` path fires and the task is awaited cleanly (no `RuntimeError` from the new `except Exception`)
- [x] 4.6 `test_stop_failing_clouds_stop_does_not_skip_rest`: mock `clouds.stop()` to raise `RuntimeError`; call `stop()`; assert `gateway.disconnect_all()` and `http_session.close()` are still called and `http_session` is nulled
- [x] 4.7 `test_stop_failing_disconnect_all_does_not_skip_http`: mock `gateway.disconnect_all()` to raise; call `stop()`; assert `http_session.close()` is still called and `http_session` is nulled
- [x] 4.8 `test_stop_before_start_is_safe_noop`: call `orch.stop()` on a freshly-constructed orchestrator with empty `_bg_jobs` and a mock `http_session`; assert no error is raised, the guard is set, and the cleanup steps run on empty/idle resources
- [x] 4.9 `test_stop_http_session_nulled_after_close`: call `stop()` with a mock `http_session`; assert `self._http_session is None` after `stop()` returns regardless of whether `close()` succeeded or raised

## 5. Unit tests — `run_daemon` try/finally cleanup guarantee

- [x] 5.1 Create `tests/unit/test_daemon_common_cleanup.py` (or extend an existing `tests/unit/test_daemon_common*.py` if present) with a GRACE-lite header (DEPENDS: M-DAEMON-COMMON; LINKS: M-APPLICATION-ORCHESTRATOR)
- [x] 5.2 `test_start_returns_normally_calls_stop`: stub `orch.start()` to return immediately (no signal); assert `orch.stop()` was called exactly once by the `finally` block, and resources (mock `http_session`) were closed
- [x] 5.3 `test_start_raises_still_calls_stop`: stub `orch.start()` to raise `RuntimeError`; assert `orch.stop()` was called by the `finally` block (cancelling any early bg jobs) and the `RuntimeError` propagates out of `run_daemon` after cleanup
- [x] 5.4 `test_signal_handler_then_finally_is_noop`: simulate a signal arrival (call the registered signal handler) during `orch.start()`, then let `start()` return; assert `orch.stop()` was called exactly once with the cleanup body running once (the handler's call ran the body, the `finally`'s call was a no-op) — `http_session.close()` called exactly once
- [x] 5.5 `test_make_daemon_success_start_raises_cleans_early_jobs`: stub `make_daemon` to return an orchestrator with a mock `http_session` and `orch.start()` to raise after adding one early bg job to `_bg_jobs`; assert the `finally`'s `stop()` cancels the early job and closes the `http_session`

## 6. Static checks and validation

- [x] 6.1 `uv run ruff check .` passes
- [x] 6.2 `uv run ruff format --check .` passes
- [x] 6.3 `uv run lint-imports` passes
- [x] 6.4 `uv run zuban check` passes
- [x] 6.5 `uv run pytest -m unit` passes (focused on the new `test_orchestrator_stop_idempotent` and `test_daemon_common_cleanup` tests)
- [x] 6.6 `openspec validate fix-daemon-resource-leak-on-start-return --json` reports `valid: true`
- [x] 6.7 `openspec validate --all --json` passes (no regressions to existing `daemon-common` or `orchestrator` specs from the ADDED requirements)
- [x] 6.8 Run `rg "except BaseException" yascheduler/application/orchestrator.py yascheduler/entrypoints/cli/daemon_common.py` and confirm zero matches (enforces that `except Exception` was not accidentally broadened — preserves the "CancelledError still reaches the graceful-drain path" scenario)
- [x] 6.9 Run `rg "_stopped" yascheduler/application/orchestrator.py` and confirm the guard is declared in `__init__`, checked and set at the top of `stop()` with no `await` between check and set (enforces the idempotency scenario)
- [x] 6.10 Run `rg "http_session = None" yascheduler/application/orchestrator.py` and confirm the nulling is present after the close block (enforces the "http_session nulled after close" scenario)
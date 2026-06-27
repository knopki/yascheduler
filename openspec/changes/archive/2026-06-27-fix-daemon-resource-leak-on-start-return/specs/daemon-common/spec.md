## ADDED Requirements

### Requirement: Daemon shutdown cleanup guarantee

`run_daemon` (`yascheduler/entrypoints/cli/daemon_common.py`) SHALL guarantee that the cleanup body of `orch.stop()` executes exactly once on every exit path: normal return of `orch.start()`, an exception raised by `orch.start()`, or a signal-driven shutdown where the SIGTERM/SIGINT handler calls `orch.stop()` first and the subsequent `finally` block calls it again as a no-op. The `orch.stop()` function itself may be called more than once (e.g. signal handler then `finally`), but only the first call executes the cleanup body; subsequent calls return immediately as a no-op per the `orchestrator` capability's idempotency requirement.

The `await orch.start()` call SHALL be wrapped in a `try/finally` block whose `finally` clause awaits `orch.stop()`. The signal-handling registration (SIGTERM/SIGINT) SHALL remain unchanged and SHALL still call `orch.stop()` from the handler; the `finally` is the safety net for the non-signal exit paths.

`run_daemon` SHALL NOT swallow exceptions from `orch.start()`: a `start()` exception SHALL propagate out of `run_daemon` after the `finally` cleanup runs (re-raising is the default `try/finally` behavior; no `except` clause is added).

#### Scenario: start() returns normally triggers cleanup
- **WHEN** `orch.start()` returns normally (e.g. every background job terminated with a non-`CancelledError` exception and `_shutdown_barrier`'s `gather(..., return_exceptions=True)` completed)
- **THEN** the `finally` block awaits `orch.stop()`, which closes SSH connections, the HTTP session, and cloud clients, and `run_daemon` returns cleanly without leaking resources

#### Scenario: start() raises triggers cleanup
- **WHEN** `orch.start()` raises an exception
- **THEN** the `finally` block awaits `orch.stop()` (cancelling any early background jobs already added to `_bg_jobs`) before the exception propagates out of `run_daemon`

#### Scenario: signal handler runs stop() then finally is a no-op
- **WHEN** a SIGTERM/SIGINT is received while `orch.start()` is running and the signal handler calls `orch.stop()` (first execution, body runs)
- **THEN** `orch.start()` subsequently returns, the `finally` block awaits `orch.stop()` again, and the second invocation is a no-op (no double close of the HTTP session, no double disconnect) because `Orchestrator.stop()` is idempotent per the `orchestrator` capability

#### Scenario: make_daemon succeeds and start() raises still cleans up early jobs
- **WHEN** `make_daemon` returns an `Orchestrator` with an open `http_session` and `orch.start()` raises after adding only some background jobs (e.g. `_print_stats` and the connect-machine coordinator) to `_bg_jobs`
- **THEN** the `finally` block's `orch.stop()` cancels those early jobs and closes the `http_session` that `make_daemon` created, preventing a leak of the early jobs and the HTTP session
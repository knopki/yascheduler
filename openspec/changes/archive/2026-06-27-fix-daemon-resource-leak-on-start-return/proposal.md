## Why

`run_daemon` (`yascheduler/entrypoints/cli/daemon_common.py:76-123`) ends with a bare `await orch.start()` and no `try/finally`. The only resource-cleanup path is `Orchestrator.stop()` (`orchestrator.py:686-700`), which is invoked exclusively by the SIGTERM/SIGINT handler. When `start()` returns normally — which happens when every background job terminates with a non-`CancelledError` exception (e.g. a persistent DB outage makes every producer and `_print_stats` raise `pg8000.Error`; `_shutdown_barrier` swallows them via `gather(..., return_exceptions=True)`) — `run_daemon` exits without calling `stop()`, leaking open `asyncssh` connections, the `aiohttp.ClientSession` created in `_setup_domain_events`, and cloud provider clients. The same defect class also breaks the signal path when a background job has already died with an exception before SIGTERM arrives: `stop()`'s `await task` re-raises the original exception, which `except asyncio.CancelledError` does not catch, so `clouds.stop()`, `gateway.disconnect_all()`, and `http_session.close()` are skipped. A single DB outage that kills the subsystems and is followed by `systemctl stop` leaks every resource.

## What Changes

- Wrap `await orch.start()` in `run_daemon` with `try/finally: await orch.stop()` so cleanup runs on every exit path (normal `start()` return, exception in `start()`, signal). The signal handler still calls `stop()` first; the `finally` becomes a no-op on that path.
- Make `Orchestrator.stop()` idempotent and exception-safe so a second invocation (signal + finally, or two signals) is a safe no-op and a single failing cleanup step does not skip the remaining steps:
  - Add a `_stopped` guard flag (set synchronously, no `await` between check and set — atomic in single-threaded asyncio) so the body runs exactly once across concurrent/interleaved/repeated callers.
  - Catch `Exception` (in addition to `asyncio.CancelledError`) when awaiting cancelled background jobs so a job that died with a non-`CancelledError` before shutdown does not abort the cleanup chain.
  - Wrap each cleanup step (`clouds.stop()`, `gateway.disconnect_all()`, `http_session.close()`) in its own `try/except Exception` so one failing step cannot skip the others.
  - Null `self._http_session` after closing so a repeated call cannot close an already-closed session.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `daemon-common`: add a requirement that `run_daemon` SHALL guarantee `orch.stop()` on any exit path via `try/finally`; add scenarios for `orch.start()` returning normally, `orch.start()` raising, and the signal handler running `stop()` first with the `finally` becoming a no-op.
- `orchestrator`: add a requirement that `stop()` SHALL be idempotent and exception-safe (single-execution guard, isolated cleanup steps, background-job exception tolerance, `http_session` nulling); add scenarios for double/interleaved `stop()`, dead-job-then-signal, partial cleanup-step failure, and `start()` raising.

## Impact

- **Code**:
  - `yascheduler/entrypoints/cli/daemon_common.py` — `run_daemon` wraps `await orch.start()` in `try/finally: await orch.stop()`; update the `run_daemon` contract `SIDE_EFFECTS` and `START_BLOCK_START_ORCHESTRATOR`/`END_BLOCK` markers.
  - `yascheduler/application/orchestrator.py` — `Orchestrator.__init__` adds `self._stopped = False`; `stop()` gains the guard, the `except Exception` on `await task`, per-step `try/except`, and `http_session` nulling; update the `stop` contract `SIDE_EFFECTS`/`LINKS`.
- **No public API change**: `run_daemon` and `Orchestrator.stop` keep their existing signatures; the change hardens existing contracts rather than introducing new ones. No new dependencies.
- **Tests**: focused unit tests for `run_daemon`'s `finally` and `stop()`'s idempotency/exception-safety; the entire `stop()` cleanup chain (`clouds.stop()`, `gateway.disconnect_all()`, `http_session.close()`) currently lacks test coverage (codegraph reports `⚠️ no covering tests found` for `disconnect_all`), so this change adds the first coverage of the cleanup chain.
- **Composes with, but does not duplicate, `fix-orchestrator-producer-silent-death`**: that change registers worker tasks in `self._bg_jobs` so `stop()`'s cancel cascade reaches them; this change ensures `stop()` itself runs and tolerates exceptions in any job (including the now-registered workers). The two changes are orthogonal — one fixes "workers never cancelled on shutdown", the other fixes "stop() never runs / aborts midway".
## ADDED Requirements

### Requirement: Producer error resilience

The orchestrator SHALL catch non-`CancelledError` exceptions raised by a
producer coroutine inside `_create_producer_consumers` and SHALL log the
error and continue the producer-consumer loop on the next `_sleep_interval`
tick, so that a transient failure in a producer's dependency (DB query in
`list_by_status` / `list_enabled` / `list_all`, `gateway.list_connected()`
read, `deallocate_nodes` write) does not silently kill the subsystem for
the daemon's lifetime.

The orchestrator SHALL preserve the existing `except asyncio.CancelledError`
graceful-shutdown path: `CancelledError` (a `BaseException`, not
`Exception`, since Python 3.8) SHALL propagate past the producer-error
`except Exception` clause and reach the `except CancelledError` block, which
drains the queue and cancels the workers. The producer-error handler SHALL
NOT run on graceful shutdown.

The orchestrator SHALL register the worker tasks created in
`_create_producer_consumers` in `self._bg_jobs` (in addition to the parent
producer coroutine) so that `stop()`'s cancel cascade reaches the workers
even if the parent coroutine exits via a `BaseException` that the
producer-error `except Exception` does not catch (`SystemExit`,
`KeyboardInterrupt`). Cancelling an already-cancelled worker SHALL be a
no-op (idempotent), so the double-cancel from both `stop()` and the parent's
`except CancelledError` drain SHALL produce no observable error.

The `_print_stats` background job SHALL catch non-`CancelledError`
exceptions from its DB and gateway reads, log the error, and continue the
stats loop on its next tick, so the daemon's primary observability signal
survives transient errors.

#### Scenario: Transient producer error does not kill the loop

- **WHEN** a producer coroutine inside `_create_producer_consumers` raises an `Exception` (e.g. a DB timeout in `uow.tasks.list_by_status`)
- **THEN** the orchestrator logs the error and the producer-consumer loop continues on the next `_sleep_interval` tick, re-invoking the producer

#### Scenario: CancelledError preserves graceful shutdown drain

- **WHEN** the producer coroutine receives `asyncio.CancelledError` during shutdown
- **THEN** the `CancelledError` propagates past the producer-error `except Exception` clause to the existing `except asyncio.CancelledError` block, which drains the queue (`queue.join()`) and cancels the workers

#### Scenario: Workers are cancelled on shutdown

- **WHEN** `stop()` cancels the tasks in `self._bg_jobs` and the worker tasks were registered in `self._bg_jobs` by `_create_producer_consumers`
- **THEN** each worker blocked on `await queue.get()` receives `CancelledError`, propagates it out of `worker()`, and is awaited cleanly by `stop()`'s `await task` (inside `except CancelledError: pass`)

#### Scenario: Double-cancel of workers is idempotent

- **WHEN** a worker is cancelled both by `stop()` (via `self._bg_jobs`) and by the parent coroutine's `except CancelledError` drain (via `for task in workers: task.cancel()`)
- **THEN** the second `cancel()` is a no-op on the already-cancelled task and the worker is awaited exactly once without error

#### Scenario: Stats loop survives transient errors

- **WHEN** `_print_stats` raises an `Exception` from its DB or gateway reads
- **THEN** the orchestrator logs the error and the stats loop continues on its next tick instead of silently dying
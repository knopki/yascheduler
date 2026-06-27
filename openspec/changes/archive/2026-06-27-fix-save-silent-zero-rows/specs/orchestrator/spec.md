## MODIFIED Requirements

### Requirement: Producer error resilience

The orchestrator SHALL catch non-`CancelledError` exceptions raised by a
producer coroutine inside `_create_producer_consumers` and SHALL log the
error and continue the producer-consumer loop on the next `_sleep_interval`
tick, so that a transient failure in a producer's dependency (DB query in
`list_by_status` / `list_enabled` / `list_all`, `gateway.list_connected()`
read, `deallocate_nodes` write) does not silently kill the subsystem for
the daemon's lifetime.

The orchestrator SHALL ALSO catch non-`CancelledError` exceptions raised by
a consumer coroutine inside the `_create_producer_consumers` inner
`worker()`. The worker SHALL wrap `await consumer(msg)` in a
`try/except Exception` that logs the error and continues the worker loop.
The existing `finally: queue.item_done(msg)` SHALL be preserved so the
queue item is still dequeued when the consumer raises. A consumer
exception (e.g. `TaskRowNotFoundError` raised by the task-abandon path
when the target row was concurrently deleted) SHALL NOT silently kill the
worker `asyncio.Task` and reduce queue throughput; it SHALL be logged and
the worker SHALL continue processing subsequent messages. This is
symmetric to the producer-error handling above and to the
allocator-consumer's existing `try/except Exception` wrap.

The orchestrator SHALL preserve the existing `except asyncio.CancelledError`
graceful-shutdown path: `CancelledError` (a `BaseException`, not
`Exception`, since Python 3.8) SHALL propagate past the producer-error and
consumer-error `except Exception` clauses and reach the
`except CancelledError` block, which drains the queue and cancels the
workers. The producer-error and consumer-error handlers SHALL NOT run on
graceful shutdown.

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

#### Scenario: Transient consumer error does not kill the worker

- **WHEN** the consumer callable passed to `_create_producer_consumers` raises an `Exception` (e.g. `TaskRowNotFoundError` from the task-abandon path when the target row was concurrently deleted) while processing a queue message
- **THEN** the orchestrator logs the error, the queue item is dequeued via the `finally: queue.item_done(msg)` block, and the worker continues processing subsequent messages from the queue (the worker `asyncio.Task` is NOT killed)

#### Scenario: CancelledError preserves graceful shutdown drain

- **WHEN** the producer coroutine receives `asyncio.CancelledError` during shutdown
- **THEN** the `CancelledError` propagates past the producer-error `except Exception` clause to the existing `except asyncio.CancelledError` block, which drains the queue (`queue.join()`) and cancels the workers

#### Scenario: Consumer CancelledError preserves graceful shutdown drain

- **WHEN** the consumer callable inside the `worker()` receives `asyncio.CancelledError` during shutdown
- **THEN** the `CancelledError` propagates past the worker's `except Exception` clause (because `CancelledError` is a `BaseException`, not `Exception`, since Python 3.8) to the `finally: queue.item_done(msg)` block and onward to the existing `except asyncio.CancelledError` drain path, preserving graceful shutdown

#### Scenario: Workers are cancelled on shutdown

- **WHEN** `stop()` cancels the tasks in `self._bg_jobs` and the worker tasks were registered in `self._bg_jobs` by `_create_producer_consumers`
- **THEN** each worker blocked on `await queue.get()` receives `CancelledError`, propagates it out of `worker()`, and is awaited cleanly by `stop()`'s `await task` (inside `except CancelledError: pass`)

#### Scenario: Double-cancel of workers is idempotent

- **WHEN** a worker is cancelled both by `stop()` (via `self._bg_jobs`) and by the parent coroutine's `except CancelledError` drain (via `for task in workers: task.cancel()`)
- **THEN** the second `cancel()` is a no-op on the already-cancelled task and the worker is awaited exactly once without error

#### Scenario: Stats loop survives transient errors

- **WHEN** `_print_stats` raises an `Exception` from its DB or gateway reads
- **THEN** the orchestrator logs the error and the stats loop continues on its next tick instead of silently dying
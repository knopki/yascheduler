# Orchestrator

## Purpose

Orchestrator class that manages concurrent producer-consumer loops for
connecting machines, allocating tasks, consuming results, and deallocating
idle cloud nodes.

## Requirements

### Requirement: Orchestrator manages producer-consumer loops

The system SHALL provide an `Orchestrator` class that runs 4 producer-consumer
loops. The `Orchestrator` SHALL accept `uow_factory: Callable[[],
AbstractUnitOfWork]`, `repository: MachineRepository` and `operations:
MachineOperations` (Protocol types for all code paths), `clouds: CloudProvisioner` (Protocol type), `allocation_tracker:
AllocationTracker`, `active_clouds: Sequence[CloudConfig]` (domain Protocol
type), and `allocation_lock: asyncio.Lock`. The orchestrator SHALL own the
tracker, the filtered cloud config list, and the lock — constructing them once
and injecting them into use cases.

The `Orchestrator` SHALL NOT import `AllSSHRetryExc` or `backoff` from
`yascheduler.infra` at runtime. The `Orchestrator` SHALL NOT apply
`@backoff.on_exception` decorators — all retry logic SHALL live in the
adapter.

The `Orchestrator` SHALL type `self._repository` as `MachineRepository` and
`self._operations` as `MachineOperations` (Protocols). The orchestrator's
`_start_task_on_machine` SHALL be a thin wrapper that resolves `ncpus` via UoW
(falling back to `operations.get_cpu_cores(session)`) and delegates the actual
upload + spawn to `operations.start_task_on_machine(session, ...)`. The
orchestrator SHALL NOT contain any reference to adapter-specific methods
(`get_sftp`, `get_path`, `get_quote`, `run_full`).

The orchestrator SHALL NOT read `self._clouds.configs` — the filtered
`active_clouds` list is injected at construction. The orchestrator SHALL
NOT hold `adapters` or `configs` dicts — provider selection is delegated
to the `clouds.select_provider` port method.

The `Orchestrator.__init__` SHALL NOT accept a `config: Config` parameter.
The `Config` aggregate lives in `yascheduler.entrypoints` and SHALL NOT be
imported by `yascheduler.application`. The orchestrator SHALL accept
`local_settings: LocalSettings` and `remote_defaults: RemoteDefaults` (both
from `yascheduler.domain`) and store them as `self._local_settings` and
`self._remote_defaults`. The `list_private_keys_fn: Callable[[Path],
Sequence[PurePath]]` callable (introduced in P1) SHALL be retained. The
orchestrator SHALL NOT hold an `self._config` reference.

#### Scenario: Orchestrator starts all loops
- **WHEN** `await orchestrator.start()` is called
- **THEN** all 4 loops begin executing concurrently, using `uow_factory` for all persistence queries, `repository` for all SSH collection operations, and `operations` for all per-machine SSH operations

#### Scenario: Graceful shutdown
- **WHEN** `await orchestrator.stop()` is called
- **THEN** all loops receive cancellation, pending queue items are drained, and connections are closed via `repository.disconnect_all()`

#### Scenario: No adapter imports at runtime
- **WHEN** `orchestrator.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: Task deployment delegated to operations
- **WHEN** the orchestrator allocates a task to a machine
- **THEN** the orchestrator resolves a `session` via `repository.get_session(ip)`, resolves `ncpus` via UoW, and calls `operations.start_task_on_machine(session, engine, task, ncpus, self._remote_defaults.engines_dir)` — never touches `get_sftp`, `get_path`, or `get_quote` directly

#### Scenario: Orchestrator does not import Config
- **WHEN** `orchestrator.py` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears (TYPE_CHECKING or runtime); the orchestrator imports `LocalSettings` and `RemoteDefaults` from `yascheduler.domain` under TYPE_CHECKING

#### Scenario: Orchestrator constructed with unpacked settings
- **WHEN** `Orchestrator(...)` is constructed by the composition root
- **THEN** the call passes `local_settings=` and `remote_defaults=` keyword arguments (instances of `LocalSettings` and `RemoteDefaults`), not a `Config` aggregate; the `list_private_keys_fn` callable is passed as before; `repository=` and `operations=` are passed as separate keyword arguments (not a single `gateway=`)

### Requirement: Allocate loop

The system SHALL poll TO_DO tasks via UoW and dispatch to the
`allocate_task` use case with configured concurrency limits. The producer
SHALL load domain `Task` objects from `TaskRepository.list_by_status`. The
producer SHALL compute cloud capacity via the inline `_clouds_get_capacity`
method (UoW read of `uow.nodes.list_all()` + `Counter` over
`active_clouds`). SSH collection operations SHALL use `MachineRepository`;
per-machine SSH operations SHALL use `MachineOperations`. The
`_allocator_consumer` SHALL NOT apply `@backoff.on_exception` — retry
logic lives in the adapter.

#### Scenario: Task allocated in order
- **WHEN** multiple TO_DO tasks exist
- **THEN** tasks are allocated up to the configured `allocate_limit` concurrently

#### Scenario: Cloud capacity computed inline
- **WHEN** `_allocator_producer` determines the task limit
- **THEN** `_clouds_get_capacity` opens a UoW, reads `uow.nodes.list_all()`, counts nodes per cloud, and returns `max(0, sum(max_nodes for c in active_clouds) - sum(current_counts for c in active_clouds))`

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. Queue messages SHALL
carry domain `Task` objects. Per-machine SSH operations SHALL use
`MachineOperations` with a `session` resolved via `repository.get_session(ip)`.

The orchestrator SHALL maintain an in-process `set[int]` of in-flight consume
task ids (`self._consuming`). The consume producer SHALL skip yielding a task
whose id is in `self._consuming`. The consume consumer SHALL add the task id to
`self._consuming` before awaiting `consume_task` and remove it in a `finally`
block so a failed consume does not permanently block re-yield.

#### Scenario: Consume task in-flight guard
- **WHEN** the consume producer is about to yield a task whose id is in `self._consuming`
- **THEN** the producer skips it and moves to the next RUNNING task

#### Scenario: Consume task id removed after completion
- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the consumer's `finally` block removes the task id from `self._consuming`, allowing a future producer cycle to yield the task again if it is still RUNNING

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned nodes via `MachineRepository` and `CloudProvisioner`. The
`_deallocator_consumer` SHALL call
`deallocate_node(node, repository, clouds, uow_factory)` directly with the
`Node` taken from `msg.payload` — it SHALL NOT open a UoW to read the node
via `uow.nodes.get(ip)` (the `Node` is already carried in the queue message,
eliminating the round-trip lookup). `deallocate_node` performs SSH
disconnect + disable + cloud delete + remove in two short UoWs bracketing
the pure cloud call. The orchestrator SHALL use `repository.list_connected()`
instead of `gateway.items()` for iterating connected machines.

The `_deallocate_q` queue SHALL be typed `UniqueQueue[NodeId, Node]`
(was `UniqueQueue[str, str]`). The producer SHALL yield
`UMessage(node.node_id, node)` for each `Node` returned by `deallocate_nodes`
— the message id is `node.node_id` (a `NodeId`, strictly unique `SERIAL PK`),
the payload is the `Node`. This rekeys the dedup from `ip` (non-unique post
migration 003 — duplicate IPs are valid behind different jump hosts) to
`NodeId` (strictly unique), so two distinct nodes sharing an IP are both
processed rather than one being silently dropped.

The `_deallocator_consumer` SHALL NOT perform its own SSH
`elif self._repository.contains(ip): await self._repository.disconnect(ip)`
fallback. SSH teardown is owned by `deallocate_node` (which calls
`repository.contains(node.ip)` + `repository.disconnect(node.ip)` internally
before the `if node.cloud:` guard). The consumer SHALL wrap
`deallocate_node` in a `try/except Exception` that logs `node_id`, `ip`, and
the error and continues (the worker-resilience wrapper in
`_create_producer_consumers` already catches consumer exceptions, but the
deallocator consumer keeps its own explicit error log with `node_id`/`ip`
fields for correlation, matching the prior behavior).

#### Scenario: Cloud node idle too long
- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB via `uow.nodes.disable(node.node_id)` and returns the `Node` (carrying `node_id`) for SSH cleanup and cloud deletion

#### Scenario: Deallocator uses list_connected
- **WHEN** `_deallocator_producer` iterates connected machines to build `idle_machines`
- **THEN** it uses `repository.list_connected()` and accesses `session.machine.ip` (and `session.machine.free_since`) directly

#### Scenario: Deallocator queue is keyed on NodeId
- **WHEN** `_deallocator_producer` enqueues disabled nodes
- **THEN** it yields `UMessage(node.node_id, node)` where `node.node_id` is a `NodeId` (the queue dedup key) and `node` is the full `Node` (the payload); the queue is `UniqueQueue[NodeId, Node]`

#### Scenario: Deallocator consumer takes Node from payload without DB lookup
- **WHEN** `_deallocator_consumer` processes a disabled node message
- **THEN** it takes `node = msg.payload` directly and calls `deallocate_node(node, self._repository, self._clouds, self._uow_factory)` — it SHALL NOT call `uow.nodes.get(ip)` to reconstruct the `Node`; the `Node` is already carried in the message

#### Scenario: Deallocator consumer does not duplicate SSH teardown
- **WHEN** `_deallocator_consumer` processes a node
- **THEN** it SHALL NOT call `self._repository.contains(node.ip)` or `self._repository.disconnect(node.ip)` directly; SSH teardown is owned by `deallocate_node`'s internal `repository.contains(node.ip)` + `repository.disconnect(node.ip)` calls (which run before the `if node.cloud:` guard)

#### Scenario: Deallocator consumer logs node_id and ip on error
- **WHEN** `deallocate_node(node, ...)` raises an `Exception` inside `_deallocator_consumer`
- **THEN** the consumer's `except Exception` block logs `node_id=%s ip=%s err=%s` (was `ip=%s err=%s` only) and the worker continues processing subsequent messages

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineRepository`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-IP connect-failure timer
(`dict[str, float]` mapping IP to the monotonic timestamp of the first
consecutive failure) in memory. On a successful `repository.connect(...)` for an
IP, the orchestrator SHALL pop that IP from the failure timer. For
cloud-provisioned nodes, on `MachineConnectionError`, the orchestrator SHALL
compare the elapsed monotonic age against the node's cloud `connect_grace`
(looked up from `self._config_clouds` by `prefix == node.cloud`).

The connect-machine producer SHALL yield all enabled nodes that are not
currently registered in the repository, regardless of `cloud`. Static
operator-managed nodes (`cloud is None`) SHALL be connected like cloud nodes.
On `MachineConnectionError` for a static node (`cloud is None`), the
orchestrator SHALL log a `CONNECT_RETRY_STATIC` warning and return early
BEFORE the grace-check — so static nodes retry indefinitely on every producer
cycle, never accumulate entries in the failure timer, and NEVER reach the
`abandon_node` use case. A transient SSH outage (e.g. after a daemon restart)
must not silently delete an operator's node row.

For cloud nodes (`cloud is not None`):

- If `age < connect_grace`, the orchestrator SHALL log the failure and return;
  the next producer cycle re-yields the node (retry behavior unchanged).
- If `age >= connect_grace`, the orchestrator SHALL call the `abandon_node`
  use case with the node, the repository, the operations, the cloud provisioner,
  the UoW factory, and the allocation tracker, then pop the IP from the failure
  timer. The `abandon_node` use case deletes the cloud VM, removes the
  `yascheduler_nodes` row, and discards the stuck task's entry from
  `AllocationTracker` so the task re-allocates on the next cycle.

The failure timer SHALL NOT be persisted across daemon restarts (in-memory
only). A restart resets the grace window for any IP that was mid-failure.

For nodes whose `node.cloud` is a non-None value that does not match any
`CloudConfig.prefix` in `self._config_clouds`, the orchestrator SHALL fall
back to a conservative default `connect_grace` of 120 seconds (matches the
slowest cloud default) so the abandon path still fires for misconfigured or
unknown clouds. This fallback does NOT apply to `cloud is None` (static
nodes), which are handled before the grace-check and never reach the abandon
path.

#### Scenario: New node connected
- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via `repository.connect(...)` and the session is registered

#### Scenario: Connection failure caught as domain error
- **WHEN** `repository.connect(...)` fails
- **THEN** the orchestrator catches `MachineConnectionError` and logs the error

#### Scenario: Connection failure within grace retries
- **WHEN** `repository.connect(...)` raises `MachineConnectionError` for an IP whose elapsed failure age is less than the node's cloud `connect_grace`
- **THEN** the orchestrator logs the failure and returns without calling `abandon_node`; the IP remains in the failure timer and the next producer cycle re-yields the node

#### Scenario: Connection failure past grace triggers abandon
- **WHEN** `repository.connect(...)` raises `MachineConnectionError` for an IP whose elapsed failure age is greater than or equal to the node's cloud `connect_grace`
- **THEN** the orchestrator calls `abandon_node(node, repository, operations, clouds, uow_factory, tracker)`, pops the IP from the failure timer, and the node is no longer yielded by subsequent producer cycles (its DB row is removed)

#### Scenario: Successful connect resets the failure timer
- **WHEN** `repository.connect(...)` succeeds for an IP that had a prior `MachineConnectionError` recorded in the failure timer
- **THEN** the orchestrator pops the IP from the failure timer and subsequent failures for that IP start a fresh grace window

#### Scenario: Unknown cloud falls back to conservative grace
- **WHEN** `repository.connect(...)` raises `MachineConnectionError` for a node whose `cloud` is a non-None value that does not match any `CloudConfig.prefix` in `self._config_clouds`
- **THEN** the orchestrator uses a `connect_grace` of 120 seconds for the age comparison

#### Scenario: Daemon restart resets failure timers
- **WHEN** the daemon restarts with an IP that was mid-failure (age had accumulated toward `connect_grace`)
- **THEN** the in-memory failure timer is empty on start and the IP's next `MachineConnectionError` starts a fresh grace window

### Requirement: Stats logging

The system SHALL periodically log queue sizes, node counts, and task counts
at a configurable interval. The orchestrator SHALL use `repository.list_connected()`
instead of `gateway.items()` for iterating connected machines.

#### Scenario: Stats printed every N seconds
- **WHEN** the orchestrator is running
- **THEN** usage statistics are logged at the configured interval

#### Scenario: Stats uses list_connected
- **WHEN** `_print_stats` iterates connected machines
- **THEN** it uses `repository.list_connected()` and accesses `session.machine.state` directly (not `state.machine.state`)

#### Scenario: Stats tolerates empty or partial count mappings
- **WHEN** `_print_stats` reads `nodes.count_by_status()` and the mapping lacks the `True` key (e.g. `yascheduler_nodes` is empty or has no enabled rows)
- **THEN** `_print_stats` SHALL use `Mapping.get(key, 0)` (or equivalent) for status-count lookups, log a normal stats line with zero counts, and SHALL NOT raise `KeyError` that would be caught by the stats-resilience `except Exception` path and spam the log every tick

### Requirement: Orchestrator concurrency limits

The system SHALL enforce configurable concurrency limits for each loop:
`conn_machine_limit`, `allocate_limit`, `consume_limit`, `deallocate_limit`.

#### Scenario: Allocation concurrency respected
- **WHEN** `allocate_limit=3` and 10 TO_DO tasks exist
- **THEN** at most 3 allocations proceed concurrently

### Requirement: Producer error resilience

The orchestrator SHALL catch non-`CancelledError` exceptions raised by a
producer coroutine inside `_create_producer_consumers` and SHALL log the
error and continue the producer-consumer loop on the next `_sleep_interval`
tick, so that a transient failure in a producer's dependency (DB query in
`list_by_status` / `list_enabled` / `list_all`, `repository.list_connected()`
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
exceptions from its DB and repository reads, log the error, and continue the
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

- **WHEN** `_print_stats` raises an `Exception` from its DB or repository reads
- **THEN** the orchestrator logs the error and the stats loop continues on its next tick instead of silently dying

### Requirement: Orchestrator.stop is idempotent and exception-safe

`Orchestrator.stop()` (`yascheduler/application/orchestrator.py`) SHALL be idempotent: the cleanup body SHALL execute exactly once across concurrent, interleaved, or repeated invocations (e.g. a signal handler calling `stop()` followed by a `try/finally` in `run_daemon` calling `stop()` again, or two signals arriving).

A `_stopped` boolean guard SHALL be initialized to `False` in `__init__`. At the top of `stop()`, the guard SHALL be checked and set with no `await` between the check and the set (atomic in single-threaded asyncio). If the guard is already `True`, `stop()` SHALL return immediately without re-running the cleanup body.

`Orchestrator.stop()` SHALL be exception-safe across two failure modes:

1. **Background job pre-death.** When awaiting a cancelled background job in the per-task loop, `stop()` SHALL catch both `asyncio.CancelledError` (graceful shutdown, existing behavior) and `Exception` (a job that died with a non-`CancelledError` exception before shutdown, e.g. a `pg8000.Error` from a DB outage). `asyncio.CancelledError` is a `BaseException` (not `Exception`) since Python 3.8, and the repo requires `>=3.9`, so the two `except` clauses SHALL be distinct and non-overlapping. A non-`CancelledError` exception from a dead background job SHALL be logged and SHALL NOT abort the cleanup chain.

2. **Cleanup step isolation.** Each cleanup step — `await self._clouds.stop()`, `await self._repository.disconnect_all()`, and the `http_session.close()` block — SHALL be wrapped in its own `try/except Exception` so a failure in one step (logged at `warning`) does not skip the remaining steps. `self._http_session` SHALL be set to `None` after a successful or failed `close()` so a repeated invocation cannot close an already-closed session.

The existing graceful-shutdown drain semantics (the `for task in self._bg_jobs: task.cancel(); await task` loop and the `_cancellation_event.set()`) SHALL be preserved.

#### Scenario: stop() runs cleanup body exactly once
- **WHEN** `orch.stop()` is called twice (sequentially, interleaved at an await boundary, or from two independent coroutines on the same event loop)
- **THEN** the cleanup body (`_cancellation_event.set()`, cancel bg jobs, `clouds.stop()`, `repository.disconnect_all()`, `http_session.close()`) executes exactly once; the second and subsequent invocations return immediately as a no-op

#### Scenario: signal handler then finally no-op
- **WHEN** a SIGTERM/SIGINT handler calls `orch.stop()` (first execution, body runs and closes resources) and `run_daemon`'s `finally` block subsequently calls `orch.stop()` again
- **THEN** the second invocation sees `_stopped == True` and returns immediately; `http_session.close()` is NOT called a second time on the already-closed session

#### Scenario: dead background job does not abort cleanup
- **WHEN** a background job in `self._bg_jobs` has already terminated with a non-`CancelledError` exception (e.g. `pg8000.Error`) before `orch.stop()` is called, and `stop()` awaits the cancelled (already-done) task
- **THEN** the `except Exception` clause catches the re-raised exception, logs it, and `stop()` proceeds to `self._clouds.stop()`, `self._repository.disconnect_all()`, and `self._http_session.close()` — the cleanup chain is NOT aborted by the dead job

#### Scenario: CancelledError still reaches the graceful-drain path
- **WHEN** `orch.stop()` cancels a background job that is still running and the job raises `asyncio.CancelledError`
- **THEN** the existing `except asyncio.CancelledError: pass` clause catches it (the new `except Exception` does NOT catch `CancelledError` because it is a `BaseException`), and the graceful-drain semantics are preserved

#### Scenario: failing clouds.stop does not skip disconnect and http close
- **WHEN** `await self._clouds.stop()` raises an `Exception` during `orch.stop()`
- **THEN** the `try/except Exception` around `clouds.stop()` logs the failure at `warning`, and `stop()` proceeds to `await self._repository.disconnect_all()` and the `http_session.close()` block — the SSH connections and HTTP session are still closed despite the cloud-step failure

#### Scenario: failing repository.disconnect_all does not skip http close
- **WHEN** `await self._repository.disconnect_all()` raises an `Exception` during `orch.stop()`
- **THEN** the `try/except Exception` around `repository.disconnect_all()` logs the failure at `warning`, and `stop()` proceeds to the `http_session.close()` block — the HTTP session is still closed despite the repository-step failure

#### Scenario: http_session nulled after close
- **WHEN** `orch.stop()` closes `self._http_session` (whether `close()` succeeds or raises)
- **THEN** `self._http_session` is set to `None` after the `close()` attempt, so a subsequent `stop()` invocation that somehow bypassed the `_stopped` guard (defense in depth) would see `None` and skip `close()`

#### Scenario: stop() called before start() is a safe no-op
- **WHEN** `orch.stop()` is called before `orch.start()` has been called (e.g. `make_daemon` returns and a signal arrives before `start()`)
- **THEN** the `_stopped` guard is set, `_cancellation_event.set()` runs, the empty `self._bg_jobs` loop is a no-op, `clouds.stop()`/`repository.disconnect_all()`/`http_session.close()` run on empty/idle resources, and no error is raised
#### Scenario: interleaved stop() calls are serialized by the guard

- **WHEN** two coroutines on the same event loop both call `orch.stop()` and the first call has reached an `await` point inside the cleanup body (e.g. mid-`await self._clouds.stop()`) when the second call begins
- **THEN** the second call sees `_stopped == True` (the guard was set synchronously at the top of the first call, before any `await`) and returns immediately as a no-op, while the first call continues and completes the remaining cleanup steps; the cleanup body still executes exactly once

### Requirement: Free-machine selection gated on DB-enabled nodes

The `allocate_task` use case SHALL only consider a machine allocatable
when its IP is enabled in `yascheduler_nodes`. The `_find_free_machines`
helper SHALL read `uow.nodes.list_enabled()` in the same Unit of Work it
opens for `uow.tasks.list_by_status({RUNNING})`, build
`enabled_ips = {n.ip for n in enabled_nodes}`, and filter
`MachineRepository.list_free(platforms)` down to sessions whose
`machine.ip` is in `enabled_ips` AND not in the busy-node IPs derived from
RUNNING tasks.

This restores the invariant that a machine is allocatable ONLY after its
DB row is `enabled=TRUE`. The DB row is flipped from `enabled=FALSE`
(the tmp-node inserted by `add_tmp` during provider selection) to
`enabled=TRUE` by `_persist_node_with_cleanup` after `clouds.allocate`
returns successfully — i.e. only after `_setup_vm` has completed
cloud-init, engine setup, and CPU detection.

The gate SHALL live in the use case, not in `MachineRepository`. The
`MachineRepository` Protocol (an infrastructure-layer SSH collection port)
SHALL NOT be coupled to `NodeRepository` (a persistence port). Joining the
two data sources is the use case's responsibility.

A side effect of this gate: a node that was disabled in DB but not yet
disconnected (the window between `deallocate_nodes.disable` and
`repository.disconnect`) also has a `FREE` session in the repository. The
previous filter (RUNNING tasks only) would let it through; the new gate
excludes it because its IP is no longer in `enabled_ips`. This closes a
second, latent registry-vs-DB desync window.

#### Scenario: Setup-in-flight tmp-node is invisible to the allocator

- **WHEN** `CloudProvisionerImpl._setup_vm` has called `machine_repository.connect(ip)` registering a `FREE` session, but `clouds.allocate` has not yet returned and `_persist_node_with_cleanup` has not yet set the DB row to `enabled=TRUE`
- **THEN** `_find_free_machines` excludes that session because `ip not in enabled_ips`, so no task is dispatched to the not-yet-setup node

#### Scenario: Multiple allocator workers do not pile onto the same setup-in-flight node

- **WHEN** two allocator workers run `_find_free_machines` concurrently while one setup-in-flight session is registered (DB row `enabled=FALSE`)
- **THEN** both workers exclude that session from `free_sessions`, neither attempts `_try_start_on_machine` on it, and no `MachineBusyError` pile-on occurs

#### Scenario: Enabled node is allocatable after setup completes

- **WHEN** `clouds.allocate` returned successfully and `_persist_node_with_cleanup` flipped the DB row to `enabled=TRUE`
- **THEN** on the next allocator tick `_find_free_machines` includes the session in `free_sessions` because its IP is now in `enabled_ips`

#### Scenario: Disabled-but-not-disconnected node is excluded

- **WHEN** a node's DB row was set to `enabled=FALSE` by `deallocate_nodes` but its SSH session has not yet been removed from `MachineRepository._sessions` (still `FREE`)
- **THEN** `_find_free_machines` excludes that session because its IP is no longer in `enabled_ips`, so no task is dispatched to a node being deallocated

#### Scenario: Gate lives in the use case, not the repository

- **WHEN** `MachineRepository.list_free` is inspected for any reference to `NodeRepository`, `list_enabled`, or persistence imports
- **THEN** none are present; the repository returns FREE sessions filtered only by platform, and the enabled-IP intersection is applied by `_find_free_machines` in the application layer

### Requirement: Free-machine loop isolates per-session failures

The `_allocate_free_machine` helper SHALL wrap each `_try_start_on_machine`
invocation in a `try/except Exception` so that a single stale or
transiently-unreachable session's exception is logged and the loop
continues to the next free session. If no free session succeeds, the
helper SHALL return `False` so the caller (`allocate_task`) proceeds to
the cloud-provisioning branch.

The `except` block SHALL log at `error` level with the task id, the
session ip, and the exception, and SHALL `continue` to the next session.
The `except` block SHALL NOT call `repository.disconnect` — a transient
SSH failure does not imply the session is dead, and the session's monitor
task manages its lifecycle. Stale sessions left by failed setup are
prevented at the source by the setup-failure disconnect in the
`cloud-provisioner` capability.

This is defense-in-depth: it ensures the cloud-provisioning branch is
reachable even if a free-machine iteration raises, so a task never spins
in TO_DO because one bad session aborted the whole loop.

#### Scenario: Stale session failure does not abort the loop

- **WHEN** `free_sessions` contains two sessions and the first raises `asyncssh.misc.ChannelOpenError` during `_try_start_on_machine` (e.g. a stale session pointing at a deleted VM)
- **THEN** the exception is caught, logged at `error` with task_id and ip, the loop continues to the second session, and the allocator does not propagate the exception out of `_allocate_free_machine`

#### Scenario: Cloud branch reached when all free sessions fail

- **WHEN** every session in `free_sessions` raises during `_try_start_on_machine` and none returns `True`
- **THEN** `_allocate_free_machine` returns `False`, `allocate_task` proceeds to the cloud-provisioning branch (the `if not engine.platforms` short-circuit then the `CLOUD_CRITICAL_SECTION`), and a new node may be provisioned for the task

#### Scenario: Per-session except does not disconnect

- **WHEN** `_try_start_on_machine` raises a transient SSH error for a legitimately-connected node
- **THEN** the `except` block logs and continues WITHOUT calling `repository.disconnect(session.ip)`; the session remains registered and its monitor task continues to manage its state

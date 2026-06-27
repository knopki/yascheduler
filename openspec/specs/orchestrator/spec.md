# Orchestrator

## Purpose

Orchestrator class that manages concurrent producer-consumer loops for
connecting machines, allocating tasks, consuming results, and deallocating
idle cloud nodes.

## Requirements

### Requirement: Orchestrator manages producer-consumer loops

The system SHALL provide an `Orchestrator` class that runs 4 producer-consumer
loops. The `Orchestrator` SHALL accept `uow_factory: Callable[[],
AbstractUnitOfWork]`, `gateway: MachineGateway` (Protocol type for all code
paths), `clouds: CloudProvisioner` (Protocol type), `allocation_tracker:
AllocationTracker`, `active_clouds: Sequence[CloudConfig]` (domain Protocol
type), and `allocation_lock: asyncio.Lock`. The orchestrator SHALL own the
tracker, the filtered cloud config list, and the lock — constructing them once
and injecting them into use cases.

The `Orchestrator` SHALL NOT import `AllSSHRetryExc` or `backoff` from
`yascheduler.infra` at runtime. The `Orchestrator` SHALL NOT apply
`@backoff.on_exception` decorators — all retry logic SHALL live in the
adapter.

The `Orchestrator` SHALL type `self._gateway` as `MachineGateway` (Protocol).
The orchestrator's `_start_task_on_machine` SHALL be a thin wrapper that
resolves `ncpus` via UoW (falling back to `gateway.get_cpu_cores()`) and
delegates the actual upload + spawn to `gateway.start_task_on_machine()`.
The orchestrator SHALL NOT contain any reference to adapter-specific
methods (`get_sftp`, `get_path`, `get_quote`, `run_full`).

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
- **THEN** all 4 loops begin executing concurrently, using `uow_factory` for all persistence queries and `gateway` for all SSH operations

#### Scenario: Graceful shutdown
- **WHEN** `await orchestrator.stop()` is called
- **THEN** all loops receive cancellation, pending queue items are drained, and connections are closed via gateway

#### Scenario: No adapter imports at runtime
- **WHEN** `orchestrator.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: Task deployment delegated to gateway
- **WHEN** the orchestrator allocates a task to a machine
- **THEN** the orchestrator resolves `ncpus` via UoW and calls `gateway.start_task_on_machine(machine, engine, task, ncpus, self._remote_defaults.engines_dir)` — never touches `get_sftp`, `get_path`, or `get_quote` directly

#### Scenario: Orchestrator does not import Config
- **WHEN** `orchestrator.py` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears (TYPE_CHECKING or runtime); the orchestrator imports `LocalSettings` and `RemoteDefaults` from `yascheduler.domain` under TYPE_CHECKING

#### Scenario: Orchestrator constructed with unpacked settings
- **WHEN** `Orchestrator(...)` is constructed by the composition root
- **THEN** the call passes `local_settings=` and `remote_defaults=` keyword arguments (instances of `LocalSettings` and `RemoteDefaults`), not a `Config` aggregate; the `list_private_keys_fn` callable is passed as before

### Requirement: Allocate loop

The system SHALL poll TO_DO tasks via UoW and dispatch to the
`allocate_task` use case with configured concurrency limits. The producer
SHALL load domain `Task` objects from `TaskRepository.list_by_status`. The
producer SHALL compute cloud capacity via the inline `_clouds_get_capacity`
method (UoW read of `uow.nodes.list_all()` + `Counter` over
`active_clouds`). SSH operations SHALL use `MachineGateway`. The
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
carry domain `Task` objects. SSH operations SHALL use `MachineGateway`.

The orchestrator SHALL maintain an in-process `set[int]` of in-flight consume
task ids (`self._consuming`). The consume producer SHALL skip yielding a task
whose id is in `self._consuming`. The consume consumer SHALL add the task id to
`self._consuming` before awaiting `consume_task` and remove it in a `finally`
block. Because both producer and consumer run in the same event loop, the
check/add/remove are atomic (no `await` between check and add).

The orchestrator SHALL treat the `consume_task` return value as a
finalisation signal: when `consume_task` returns `True` (finalised — task is
DONE, remote directory cleaned), the orchestrator SHALL discard the ip from
`self._occupancy_started`; when `consume_task` returns `False` (deferred —
task stays RUNNING for retry, remote directory preserved), the orchestrator
SHALL NOT discard the ip from `self._occupancy_started` so the next producer
cycle re-enters the consume block for the same task.

#### Scenario: Completed task consumed and finalised
- **WHEN** a RUNNING task's machine reports `state=FREE` and `consume_task` returns `True`
- **THEN** `consume_task` is called with `task_id` to download outputs, the task is finalised (DONE), and the orchestrator discards the ip from `_occupancy_started`

#### Scenario: Transient download failure defers and retries
- **WHEN** a RUNNING task's machine reports `state=FREE` and `consume_task` returns `False` (transient-only download errors)
- **THEN** the orchestrator does NOT discard the ip from `_occupancy_started`, the task stays RUNNING, and the next consume producer cycle re-yields the task for retry

#### Scenario: In-flight consume guard prevents concurrent consume
- **WHEN** a task is in-flight in `consume_task` (its id is in `self._consuming`) and the next producer cycle reads RUNNING tasks
- **THEN** the producer skips yielding the in-flight task id, preventing two workers from concurrently consuming the same task

#### Scenario: In-flight guard released after consume completes
- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the consumer's `finally` block removes the task id from `self._consuming`, allowing a future producer cycle to yield the task again if it is still RUNNING

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned IPs via `MachineGateway` and `CloudProvisioner`. The
`_deallocator_consumer` SHALL open a UoW to read the node, call
`deallocate_node(node, gateway, clouds, uow_factory)` which performs
disable + cloud delete + remove in two short UoWs bracketing the pure
cloud call. The orchestrator SHALL use `gateway.list_connected()` instead
of `gateway.items()` for iterating connected machines.

#### Scenario: Cloud node idle too long
- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB and returns its IP for SSH cleanup and cloud deletion

#### Scenario: Deallocator uses list_connected
- **WHEN** `_deallocator_producer` iterates connected machines
- **THEN** it uses `gateway.list_connected()` and accesses `machine.ip` directly

#### Scenario: Deallocator consumer brackets cloud delete with UoWs
- **WHEN** `_deallocator_consumer` processes a disabled node IP
- **THEN** it reads the node via UoW, calls `deallocate_node` which disables via UoW, calls `clouds.deallocate(cloud, ip)`, then removes via a second UoW

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineGateway`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-IP connect-failure timer
(`dict[str, float]` mapping IP to the monotonic timestamp of the first
consecutive failure) in memory. On a successful `gateway.connect(...)` for an
IP, the orchestrator SHALL pop that IP from the failure timer. On
`MachineConnectionError`, the orchestrator SHALL compare the elapsed monotonic
age against the node's cloud `connect_grace` (looked up from
`self._config_clouds` by `prefix == node.cloud`):

The connect-machine producer SHALL only yield enabled nodes whose `cloud` is
not None (cloud-provisioned nodes). Static operator-managed nodes
(`cloud is None`) SHALL NOT be yielded to the connect-machine consumer and
therefore SHALL NEVER reach the abandon path — the application has never
auto-removed static nodes and a transient SSH outage (e.g. after a daemon
restart) must not silently delete an operator's node row.

- If `age < connect_grace`, the orchestrator SHALL log the failure and return;
  the next producer cycle re-yields the node (retry behavior unchanged).
- If `age >= connect_grace`, the orchestrator SHALL call the `abandon_node`
  use case with the node, the gateway, the cloud provisioner, the UoW
  factory, and the allocation tracker, then pop the IP from the failure timer.
  The `abandon_node` use case deletes the cloud VM, removes the
  `yascheduler_nodes` row, and discards the stuck task's entry from
  `AllocationTracker` so the task re-allocates on the next cycle.

The failure timer SHALL NOT be persisted across daemon restarts (in-memory
only). A restart resets the grace window for any IP that was mid-failure.

For nodes whose `node.cloud` does not match any `CloudConfig.prefix` in
`self._config_clouds`, the orchestrator SHALL fall back to a conservative
default `connect_grace` of 120 seconds (matches the slowest cloud default) so
the abandon path still fires for misconfigured or unknown clouds.

#### Scenario: New node connected
- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via gateway and the machine is registered

#### Scenario: Connection failure caught as domain error
- **WHEN** `gateway.connect(...)` fails
- **THEN** the orchestrator catches `MachineConnectionError` and logs the error

#### Scenario: Connection failure within grace retries
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for an IP whose elapsed failure age is less than the node's cloud `connect_grace`
- **THEN** the orchestrator logs the failure and returns without calling `abandon_node`; the IP remains in the failure timer and the next producer cycle re-yields the node

#### Scenario: Connection failure past grace triggers abandon
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for an IP whose elapsed failure age is greater than or equal to the node's cloud `connect_grace`
- **THEN** the orchestrator calls `abandon_node(node, gateway, clouds, uow_factory, tracker)`, pops the IP from the failure timer, and the node is no longer yielded by subsequent producer cycles (its DB row is removed)

#### Scenario: Successful connect resets the failure timer
- **WHEN** `gateway.connect(...)` succeeds for an IP that had a prior `MachineConnectionError` recorded in the failure timer
- **THEN** the orchestrator pops the IP from the failure timer and subsequent failures for that IP start a fresh grace window

#### Scenario: Unknown cloud falls back to conservative grace
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for a node whose `cloud` does not match any `CloudConfig.prefix` in `self._config_clouds`
- **THEN** the orchestrator uses a `connect_grace` of 120 seconds for the age comparison

#### Scenario: Daemon restart resets failure timers
- **WHEN** the daemon restarts with an IP that was mid-failure (age had accumulated toward `connect_grace`)
- **THEN** the in-memory failure timer is empty on start and the IP's next `MachineConnectionError` starts a fresh grace window

#### Scenario: Non-cloud node excluded from abandon path
- **WHEN** an enabled node has `cloud is None` (a static operator-managed node) and is not currently registered in the gateway
- **THEN** the connect-machine producer SHALL NOT yield the node to the consumer, so it never reaches the grace timer, never reaches `abandon_node`, and its `yascheduler_nodes` row is never auto-removed by this change — even across daemon restarts or transient SSH outages

### Requirement: Stats logging

The system SHALL periodically log queue sizes, node counts, and task counts
at a configurable interval. The orchestrator SHALL use `gateway.list_connected()`
instead of `gateway.items()` for iterating connected machines.

#### Scenario: Stats printed every N seconds
- **WHEN** the orchestrator is running
- **THEN** usage statistics are logged at the configured interval

#### Scenario: Stats uses list_connected
- **WHEN** `_print_stats` iterates connected machines
- **THEN** it uses `gateway.list_connected()` and accesses `machine.state` directly (not `state.machine.state`)

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

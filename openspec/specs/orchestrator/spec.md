# Orchestrator

## Purpose

Orchestrator class that manages concurrent producer-consumer loops for
connecting machines, allocating tasks, consuming results, and deallocating
idle cloud nodes.

## Requirements

### Requirement: Orchestrator manages producer-consumer loops

The system SHALL provide an `Orchestrator` class that runs 4 producer-consumer
loops. The `Orchestrator` SHALL accept `uow_factory: Callable[[],
AbstractUnitOfWork]`, `repository: MachineRepository` (Protocol type),
`task_deployer: TaskDeployer`, `output_downloader: OutputDownloader`,
`occupancy_checker: OccupancyChecker` (concrete collaborator types),
`clouds: CloudProvisioner` (Protocol type), `allocation_tracker:
AllocationTracker`, `active_clouds: Sequence[CloudConfig]` (domain Protocol
type), and `allocation_lock: asyncio.Lock`. The orchestrator SHALL own the
tracker, the filtered cloud config list, and the lock — constructing them once
and injecting them into use cases.

The `Orchestrator` SHALL NOT import `AllSSHRetryExc` or `backoff` from
`yascheduler.infra` at runtime. The `Orchestrator` SHALL NOT apply
`@backoff.on_exception` decorators — all retry logic SHALL live in the
adapter.

The `Orchestrator` SHALL type `repository` as `MachineRepository`
(Protocol). The orchestrator's
`_start_task_on_machine` SHALL be a thin wrapper that resolves `ncpus` via
`uow.nodes.get_by_id(task.allocated_node_id)` (falling back to
`session.get_cpu_cores()` when the node is absent) and delegates
the actual upload + spawn to
`task_deployer.start_task_on_machine(session, ...)`.
The orchestrator SHALL NOT contain any reference to adapter-specific methods
(`get_sftp`, `get_path`, `get_quote`, `run_full`).

The orchestrator SHALL NOT read `clouds.configs` — the filtered
`active_clouds` list is injected at construction. The orchestrator SHALL
NOT hold `adapters` or `configs` dicts — provider selection is delegated
to the `clouds.select_provider` port method.

The `Orchestrator.__init__` SHALL NOT accept a `config: Config` parameter.
The `Config` aggregate lives in `yascheduler.entrypoints` and SHALL NOT be
imported by `yascheduler.application`. The orchestrator SHALL accept
`local_settings: LocalSettings` and `remote_defaults: RemoteDefaults` (both
from `yascheduler.domain`) and store them. The `list_private_keys_fn: Callable[[Path],
Sequence[PurePath]]` callable SHALL be retained. The
orchestrator SHALL NOT hold a `config` reference.

#### Scenario: Orchestrator starts all loops

- **WHEN** `await orchestrator.start()` is called
- **THEN** all 4 loops begin executing concurrently, using `uow_factory` for all persistence queries and `repository` for all SSH collection operations

#### Scenario: Graceful shutdown

- **WHEN** `await orchestrator.stop()` is called
- **THEN** all loops receive cancellation, pending queue items are drained, and connections are closed via `repository.disconnect_all()`

#### Scenario: No adapter imports at runtime

- **WHEN** `orchestrator.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: Task deployment delegated to TaskDeployer resolves session by allocated_node_id

- **WHEN** the orchestrator allocates a task to a machine
- **THEN** the orchestrator resolves a `session` via `repository.get_session(task.allocated_node_id)`, resolves `ncpus` via `uow.nodes.get_by_id(task.allocated_node_id)` (falling back to `session.get_cpu_cores()` when the node is absent), and calls `task_deployer.start_task_on_machine(session, engine, task, ncpus, remote_defaults.engines_dir)` — never touches `get_sftp`, `get_path`, or `get_quote` directly, never keys a session lookup by `ip`

#### Scenario: Orchestrator does not import Config

- **WHEN** `orchestrator.py` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears (TYPE_CHECKING or runtime); the orchestrator imports `LocalSettings` and `RemoteDefaults` from `yascheduler.domain` under TYPE_CHECKING

#### Scenario: Orchestrator constructed with unpacked settings and three collaborators

- **WHEN** `Orchestrator(...)` is constructed by the composition root
- **THEN** the call passes `local_settings=` and `remote_defaults=` keyword arguments (instances of `LocalSettings` and `RemoteDefaults`), not a `Config` aggregate; the `list_private_keys_fn` callable is passed as before; `repository=`, `task_deployer=`, `output_downloader=`, and `occupancy_checker=` are passed as separate keyword arguments

### Requirement: Allocate loop

The system SHALL poll TO_DO tasks via UoW and dispatch to the
`allocate_task` use case with configured concurrency limits. The producer
SHALL load domain `Task` objects from `TaskRepository.list_by_status`. The
producer SHALL compute cloud capacity via an inline method that opens a UoW,
reads `uow.nodes.list_all()`, and counts nodes per cloud with a `Counter` over
`active_clouds`. SSH collection operations SHALL use `MachineRepository`.
The orchestrator SHALL pass its `occupancy_checker` instance into each
`allocate_task` invocation. The consumer SHALL NOT apply
`@backoff.on_exception` — retry logic lives in the adapter.

#### Scenario: Task allocated in order
- **WHEN** multiple TO_DO tasks exist
- **THEN** tasks are allocated up to the configured `allocate_limit` concurrently

#### Scenario: Cloud capacity computed inline
- **WHEN** the allocator producer determines the task limit
- **THEN** it opens a UoW, reads `uow.nodes.list_all()`, counts nodes per cloud, and returns `max(0, sum(max_nodes for c in active_clouds) - sum(current_counts for c in active_clouds))`

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. Queue messages SHALL
carry domain `Task` objects. The orchestrator SHALL pass its
`output_downloader` instance into each `consume_task` invocation. The
`session` is resolved via `repository.get_session(task.allocated_node_id)`.

The orchestrator SHALL maintain an in-process `set[TaskId]` of in-flight consume
task ids. The consume producer SHALL skip yielding a task
whose id is in the in-flight set. The consume consumer SHALL add the task id to
the in-flight set before awaiting `consume_task` and remove it in a `finally`
block so a failed consume does not permanently block re-yield.

The orchestrator SHALL maintain an in-process `set[NodeId]` of node_ids whose
occupancy check has been started. On the first
consumer tick for a task, the orchestrator SHALL add `task.allocated_node_id`
to the occupancy-started set and call
`occupancy_checker.start_occupancy_check(session, engine)`. On finalised
consume, the orchestrator SHALL discard the node_id from the occupancy-started
set.

#### Scenario: Consume task in-flight guard

- **WHEN** the consume producer is about to yield a task whose id is in the in-flight set
- **THEN** the producer skips it and moves to the next RUNNING task

#### Scenario: Consume task id removed after completion

- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the consumer's `finally` block removes the task id from the in-flight set, allowing a future producer cycle to yield the task again if it is still RUNNING

#### Scenario: Session resolved by allocated_node_id

- **WHEN** the consume consumer runs for a task with `allocated_node_id=NodeId(7)`
- **THEN** it calls `repository.get_session(NodeId(7))` once at the top; if `None`, the `MACHINE_GONE` path runs; if a session is returned, it is threaded through the consumer body

#### Scenario: occupancy_started keyed by NodeId

- **WHEN** the consume consumer starts an occupancy check for a task with `allocated_node_id=NodeId(7)`
- **THEN** `NodeId(7)` is added to the occupancy-started set; on finalised consume, `NodeId(7)` is discarded

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned nodes via `MachineRepository` and `CloudProvisioner`. The
consumer SHALL call
`deallocate_node(node, repository, clouds, uow_factory)` directly with the
`Node` taken from the queue message payload — it SHALL NOT open a UoW to read
the node via `uow.nodes.get(ip)` (the `Node` is already carried in the queue
message, eliminating the round-trip lookup). `deallocate_node` performs SSH
disconnect + disable + cloud delete + remove in two short UoWs bracketing
the pure cloud call. The orchestrator SHALL use `repository.list_connected()`
instead of iterating connected machines directly.

The deallocate queue SHALL be typed `UniqueQueue[NodeId, Node]`.
The producer SHALL yield
`UMessage(node.node_id, node)` for each `Node` returned by `deallocate_nodes`
— the message id is `node.node_id` (a `NodeId`, strictly unique `SERIAL PK`),
the payload is the `Node`. This rekeys the dedup from `ip` (non-unique —
duplicate IPs are valid behind different jump hosts) to
`NodeId` (strictly unique), so two distinct nodes sharing an IP are both
processed rather than one being silently dropped.

The deallocate producer SHALL build `idle_machines: dict[NodeId, float]`
by iterating
`repository.list_connected()` and keying each FREE session by
`session.machine.node_id`. The `free_since`
monotonic timestamp is the value. This dict is passed to `deallocate_nodes`,
which matches it against `node.node_id`.

The deallocate consumer SHALL NOT perform its own SSH teardown
fallback. SSH teardown is owned by `deallocate_node` (which calls
`repository.contains(node.node_id)` + `repository.disconnect(node.node_id)`
internally before the `if node.cloud:` guard). The consumer SHALL wrap
`deallocate_node` in a `try/except Exception` that logs `node_id`, `ip`, and
the error and continues.

#### Scenario: Cloud node idle too long
- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB and returns the `Node` for SSH cleanup and cloud deletion

#### Scenario: Deallocator queue keyed on NodeId, consumer takes Node from payload
- **WHEN** the deallocate producer enqueues disabled nodes
- **THEN** it yields `UMessage(node.node_id, node)` where `node.node_id` is a `NodeId` (queue dedup key) and `node` is the full `Node` (payload); the consumer takes `node = msg.payload` directly without a DB round-trip lookup

#### Scenario: Deallocator consumer does not duplicate SSH teardown
- **WHEN** the deallocate consumer processes a node
- **THEN** it SHALL NOT call `repository.contains`/`repository.disconnect` directly; SSH teardown is owned by `deallocate_node`'s internal calls

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineRepository`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-node connect-failure timer
(`dict[NodeId, float]` mapping `node_id` to the monotonic timestamp of the
first consecutive failure) in memory. On a successful
`repository.connect(node, ...)` for a node, the orchestrator SHALL pop that
node's `node_id` from the failure timer. For cloud-provisioned nodes, on
`MachineConnectionError`, the orchestrator SHALL compare the elapsed monotonic
age against the node's cloud `connect_grace` (looked up from
`active_clouds` by `prefix == node.cloud`).

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
  use case with the node, the cloud provisioner, the UoW factory, and the
  allocation tracker, then pop the `node_id` from the failure timer. The
  `abandon_node` use case deletes the cloud VM, removes the
  `yascheduler_nodes` row, and discards the stuck task's entry from
  `AllocationTracker` so the task re-allocates on the next cycle.

The failure timer SHALL NOT be persisted across daemon restarts (in-memory
only). A restart resets the grace window for any node that was mid-failure.

For nodes whose `node.cloud` is a non-None value that does not match any
`CloudConfig.prefix` in `active_clouds`, the orchestrator SHALL fall
back to a conservative default `connect_grace` of 120 seconds (matches the
slowest cloud default) so the abandon path still fires for misconfigured or
unknown clouds. This fallback does NOT apply to `cloud is None` (static
nodes), which are handled before the grace-check and never reach the abandon
path.

#### Scenario: New node connected
- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via `repository.connect(node, ...)`

#### Scenario: Connection failure within grace retries, past grace triggers abandon
- **WHEN** `repository.connect(node, ...)` raises `MachineConnectionError` for a cloud node
- **THEN** if elapsed failure age < `connect_grace`, the orchestrator logs and returns (retry next cycle); if age >= `connect_grace`, the orchestrator calls `abandon_node` and pops the `node_id` from the failure timer

#### Scenario: Successful connect resets the failure timer
- **WHEN** `repository.connect(node, ...)` succeeds for a node that had a prior `MachineConnectionError`
- **THEN** the orchestrator pops the `node_id` from the failure timer

### Requirement: Stats logging

The system SHALL periodically log queue sizes, node counts, and task counts
at a configurable interval using `repository.list_connected()`.

#### Scenario: Stats tolerates empty or partial count mappings
- **WHEN** the stats logger reads `nodes.count_by_status()` and the mapping lacks the `True` key
- **THEN** it SHALL use `Mapping.get(key, 0)` and SHALL NOT raise `KeyError`

### Requirement: Orchestrator concurrency limits

The system SHALL enforce configurable concurrency limits for each loop:
`conn_machine_limit`, `allocate_limit`, `consume_limit`, `deallocate_limit`.

#### Scenario: Allocation concurrency respected
- **WHEN** `allocate_limit=3` and 10 TO_DO tasks exist
- **THEN** at most 3 allocations proceed concurrently

### Requirement: Producer error resilience

The orchestrator SHALL catch non-`CancelledError` exceptions raised by
producer and consumer coroutines, log
the error, and continue the loop on the next tick. A transient failure in a
producer's dependency (DB query, repository read) SHALL NOT silently kill
the subsystem for the daemon's lifetime. A consumer exception SHALL NOT
silently kill the worker `asyncio.Task` — the queue item is still dequeued
via `finally: queue.item_done(msg)` and the worker continues.

`CancelledError` (a `BaseException`) SHALL propagate past the `except
Exception` clauses to the graceful-shutdown drain path. Workers SHALL be
registered in a background-jobs registry so `stop()`'s cancel cascade reaches
them even if the parent coroutine exits via a `BaseException` that `except
Exception` does not catch. Cancelling an already-cancelled worker SHALL be
a no-op.

The stats background job SHALL catch non-`CancelledError`
exceptions from its reads, log, and continue on its next tick.

#### Scenario: Transient producer error does not kill the loop
- **WHEN** a producer coroutine raises an `Exception` (e.g. DB timeout)
- **THEN** the orchestrator logs the error and the loop continues on the next tick

#### Scenario: Transient consumer error does not kill the worker
- **WHEN** the consumer callable raises an `Exception` while processing a queue message
- **THEN** the orchestrator logs the error, the queue item is dequeued, and the worker continues

#### Scenario: CancelledError preserves graceful shutdown
- **WHEN** the producer or consumer receives `asyncio.CancelledError` during shutdown
- **THEN** `CancelledError` propagates past `except Exception` to the graceful-drain path

### Requirement: Orchestrator.stop is idempotent and exception-safe

`Orchestrator.stop()` SHALL be idempotent via a boolean guard
initialized to `False` in `__init__`, checked and set with no `await` between
them. If the guard is already `True`, `stop()` returns immediately.

`stop()` SHALL be exception-safe: each cleanup step (`clouds.stop()`,
`repository.disconnect_all()`, `http_session.close()`) SHALL be wrapped in
its own `try/except Exception` so a failure in one step does not skip the
remaining steps. The `http_session` SHALL be set to `None` after close.
Background jobs that died with a non-`CancelledError` exception before
shutdown SHALL be caught and logged without aborting the cleanup chain.

#### Scenario: stop() runs cleanup body exactly once
- **WHEN** `orch.stop()` is called twice
- **THEN** the cleanup body executes exactly once; the second invocation returns immediately

#### Scenario: failing cleanup step does not skip remaining steps
- **WHEN** `await clouds.stop()` raises an `Exception` during `orch.stop()`
- **THEN** the failure is logged at `warning`, and `stop()` proceeds to `repository.disconnect_all()` and `http_session.close()`

### Requirement: Free-machine selection gated on DB-enabled nodes

The `allocate_task` use case SHALL only consider a machine allocatable
when its `node_id` is enabled in `yascheduler_nodes`. The
free-machine selection helper SHALL read `uow.nodes.list_enabled()` in the
same Unit of Work it opens for `uow.tasks.list_by_status({RUNNING})`,
build `nodes_by_id = {n.node_id: n for n in enabled_nodes}`, and filter
`MachineRepository.list_free(platforms)` down to sessions whose
`machine.node_id` is in `nodes_by_id` AND not in the busy-node node_ids
derived from RUNNING tasks (`busy_node_ids = {t.allocated_node_id for t
in running_tasks if t.allocated_node_id}`).

This restores the invariant that a machine is allocatable ONLY after its
DB row is `enabled=TRUE`. The DB row is flipped from `enabled=FALSE`
(the tmp-node inserted during provider
selection) to `enabled=TRUE` by `allocate_task`'s persist step after
`clouds.allocate` returns successfully — i.e. only after cloud-init, engine
setup, and CPU detection have completed. The persist step
is a single `uow.nodes.update(node)` (the cloud adapter returns a `Node`
carrying `tmp_node_id` as its `node_id`; UPDATE flips enabled, sets
ip/ncpus).

The gate SHALL live in the use case, not in `MachineRepository`. The
`MachineRepository` Protocol (an infrastructure-layer SSH collection port)
SHALL NOT be coupled to `NodeRepository` (a persistence port). Joining the
two data sources is the use case's responsibility.

#### Scenario: Setup-in-flight tmp-node is invisible to the allocator
- **WHEN** a `FREE` session is registered under `tmp_node_id` but the DB row is still `enabled=FALSE`
- **THEN** the free-machine selection excludes that session because `tmp_node_id not in nodes_by_id`

#### Scenario: Enabled node is allocatable after setup completes
- **WHEN** `clouds.allocate` returned successfully and the persist step flipped the DB row to `enabled=TRUE`
- **THEN** on the next allocator tick the free-machine selection includes the session

#### Scenario: Gate lives in the use case, not the repository
- **WHEN** `MachineRepository.list_free` is inspected for persistence references
- **THEN** none are present; the enabled-node_id intersection is applied by the free-machine selection in the application layer

### Requirement: Free-machine loop isolates per-session failures

The free-machine selection helper SHALL wrap each per-session
invocation in a `try/except Exception` so a single stale session's exception
is logged and the loop continues to the next free session. If no free session
succeeds, the helper SHALL return `False` so the caller proceeds to the
cloud-provisioning branch. The `except` block SHALL NOT call
`repository.disconnect` — a transient SSH failure does not imply the session
is dead.

#### Scenario: Stale session failure does not abort the loop
- **WHEN** `free_sessions` contains two sessions and the first raises during per-session invocation
- **THEN** the exception is caught and logged, the loop continues to the second session, and the allocator does not propagate the exception

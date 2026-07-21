# Orchestrator

## Purpose

Orchestrator class that manages concurrent producer-consumer loops for
connecting machines, allocating tasks, consuming results, and deallocating
idle cloud nodes.
## Requirements
### Requirement: Orchestrator manages producer-consumer loops

The system SHALL provide an `Orchestrator` class that runs 4 producer-consumer
loops (connect machine, allocate, consume, deallocate). The orchestrator owns
the `AllocationTracker`, the filtered `active_clouds` list, and the
`allocation_lock`, constructing them once and injecting them into use cases.

The orchestrator's `_start_task_on_machine` SHALL resolve `ncpus` via
`uow.nodes.get_by_id(task.allocated_node_id)`: if the resolved `Node` exists
AND its `ncpus` is not `None`, the stored value is used; otherwise the
orchestrator falls back to `session.get_cpu_cores()` and delegates the upload +
spawn to `task_deployer.start_task_on_machine(session, ...)`.

Provider selection is delegated to `clouds.select_provider`.

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
- **THEN** the orchestrator resolves a `session` via `repository.get_session(task.allocated_node_id)`, resolves `ncpus` via `uow.nodes.get_by_id(task.allocated_node_id)` — using the stored value when `node.ncpus is not None`, falling back to `session.get_cpu_cores()` when the node is absent OR `node.ncpus is None` — and calls `task_deployer.start_task_on_machine(session, engine, task, ncpus, remote_defaults.engines_dir)`

#### Scenario: Orchestrator uses static ncpus when node carries a positive value

- **WHEN** the orchestrator deploys a task whose allocated `Node.ncpus == 8`
- **THEN** `session.get_cpu_cores()` is NOT called and `8` is passed to `task_deployer.start_task_on_machine`

#### Scenario: Orchestrator discovers ncpus when node carries None

- **WHEN** the orchestrator deploys a task whose allocated `Node.ncpus is None`
- **THEN** `session.get_cpu_cores()` is called (returning the session-cached value on cache hits) and its result is passed to `task_deployer.start_task_on_machine`

#### Scenario: Orchestrator constructed with unpacked settings and three collaborators

- **WHEN** `Orchestrator(...)` is constructed by the composition root
- **THEN** the call passes `local_settings=` and `remote_defaults=` keyword arguments (instances of `LocalSettings` and `RemoteDefaults`); the `list_private_keys_fn` callable is passed as before; `repository=`, `task_deployer=`, `output_downloader=`, and `occupancy_checker=` are passed as separate keyword arguments

### Requirement: Allocate loop

The system SHALL poll TO_DO tasks via UoW and dispatch to the
`allocate_task` use case with configured concurrency limits. The producer
SHALL compute cloud capacity via an inline method that opens a UoW,
reads `uow.nodes.list_all()`, and counts nodes per cloud over
`active_clouds`. The orchestrator SHALL pass its `occupancy_checker`
instance into each `allocate_task` invocation.

#### Scenario: Task allocated in order
- **WHEN** multiple TO_DO tasks exist
- **THEN** tasks are allocated up to the configured `allocate_limit` concurrently

#### Scenario: Cloud capacity computed inline
- **WHEN** the allocator producer determines the task limit
- **THEN** it opens a UoW, reads `uow.nodes.list_all()`, counts nodes per cloud, and returns `max(0, sum(max_nodes for c in active_clouds) - sum(current_counts for c in active_clouds))`

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. The orchestrator SHALL
pass its `output_downloader` instance into each `consume_task` invocation. The
`session` is resolved via `repository.get_session(task.allocated_node_id)`.

The orchestrator SHALL guard against concurrent re-consume of the same task
(within one daemon lifetime) and SHALL start an occupancy check exactly once
per allocated node across consume ticks.

#### Scenario: Consume task in-flight guard

- **WHEN** the consume producer is about to yield a task whose id is in the in-flight set
- **THEN** the producer skips it and moves to the next RUNNING task

#### Scenario: Consume task id removed after completion

- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the in-flight guard for that task id is released, allowing a future producer cycle to yield the task again if it is still RUNNING

#### Scenario: Session resolved by allocated_node_id

- **WHEN** the consume consumer runs for a task with `allocated_node_id=NodeId(7)`
- **THEN** it calls `repository.get_session(NodeId(7))` once at the top; if `None`, the machine-gone path runs; if a session is returned, it is threaded through the consumer body

#### Scenario: occupancy_started keyed by NodeId

- **WHEN** the consume consumer starts an occupancy check for a task with `allocated_node_id=NodeId(7)`
- **THEN** `NodeId(7)` is recorded as occupancy-started; on finalised consume, `NodeId(7)` is released

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned nodes via `MachineRepository` and `CloudProvisioner`. The consumer
SHALL call `deallocate_node(node, repository, clouds, uow_factory)` directly
with the `Node` taken from the queue message payload (no DB round-trip
lookup) and SHALL use `repository.list_connected()`.

#### Scenario: Cloud node idle too long
- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB and returns the `Node` for SSH cleanup and cloud deletion

#### Scenario: Deallocator queue keyed on NodeId, consumer takes Node from payload
- **WHEN** the deallocate producer enqueues disabled nodes
- **THEN** the queue dedup key is `node.node_id` (a `NodeId`), and the payload carries the full `Node` so the consumer takes it directly without a DB round-trip lookup

#### Scenario: Deallocator consumer wraps deallocate_node in try/except
- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` raises an `Exception` during the consumer's processing
- **THEN** the consumer logs `node_id`, `hostname` (when present), and the error, and continue to the next queued node without re-raising

#### Scenario: Deallocator consumer does not duplicate SSH teardown
- **WHEN** the deallocate consumer processes a node
- **THEN** it does NOT call `repository.contains`/`repository.disconnect` directly; SSH teardown is owned by `deallocate_node`'s internal calls

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineRepository`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

Static operator-managed nodes (`cloud is None`) SHALL retry indefinitely on
every producer cycle and SHALL NEVER reach the `abandon_node` use case. For
cloud nodes, the orchestrator SHALL apply the matching `CloudConfig`'s
`connect_grace` window: failures within grace retry, failures past grace
trigger `abandon_node`.

#### Scenario: New node connected

- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via `repository.connect(node, client_keys, ...)` with no `jump_host` / `jump_username` arguments (the repository reads them from `node`)

#### Scenario: Connection failure within grace retries, past grace triggers abandon

- **WHEN** `repository.connect(node, client_keys, ...)` raises `MachineConnectionError` for a cloud node
- **THEN** if elapsed failure age < `connect_grace`, the orchestrator emits a trace DEBUG record plus a narrative record and returns (retry next cycle); if age >= `connect_grace`, the orchestrator emits a trace DEBUG record plus a narrative record, calls `abandon_node` (which discards the tracker entry by node via `discard_by_node`), and releases the failure-timer entry for the `node_id`

#### Scenario: Static node connection failure retries indefinitely

- **GIVEN** a static node (`cloud is None`) raises `MachineConnectionError`
- **WHEN** the connect-machine producer handles the failure
- **THEN** a trace DEBUG record and a separate `warning(...)` narrative record are emitted
- **AND** the orchestrator returns early BEFORE the grace-check
- **AND** the node never reaches `abandon_node`

#### Scenario: Successful connect resets the failure timer

- **WHEN** `repository.connect(node, client_keys, ...)` succeeds for a node that had a prior `MachineConnectionError`
- **THEN** the failure-timer entry for that `node_id` is released

#### Scenario: Connect reads jump identity from Node

- **WHEN** the orchestrator calls `repository.connect(node, client_keys, connect_timeout=10, data_dir=..., engines_dir=..., tasks_dir=...)` for a node with `jump_host="bastion.example.com"`
- **THEN** no inline resolution loop runs (no iteration over `config.clouds`, no read of `config.remote.jump_host`), and the tunnel leg is built from `node.jump_host` / `node.jump_username` / `node.jump_port` inside the repository

### Requirement: Stats logging

The system SHALL periodically log queue sizes, node counts, and task counts
at a configurable interval using `repository.list_connected()`. When the
stats background job raises a non-`CancelledError` exception, the orchestrator
SHALL log the error and continue on the next tick.

#### Scenario: Stats tolerates empty or partial count mappings
- **WHEN** the stats logger reads `nodes.count_by_status()` and the mapping lacks the `True` key
- **THEN** it uses `Mapping.get(key, 0)` and does NOT raise `KeyError`

#### Scenario: Stats error is logged and job continues on next tick
- **GIVEN** the stats background job raises a non-`CancelledError` exception
- **WHEN** the error is logged
- **THEN** the stats job continues on the next tick

### Requirement: Orchestrator concurrency limits

The system SHALL enforce configurable concurrency limits for each loop:
`conn_machine_limit`, `allocate_limit`, `consume_limit`, `deallocate_limit`.

#### Scenario: Allocation concurrency respected
- **WHEN** `allocate_limit=3` and 10 TO_DO tasks exist
- **THEN** at most 3 allocations proceed concurrently

### Requirement: Producer error resilience

The orchestrator SHALL catch non-`CancelledError` exceptions raised by
producer and consumer coroutines, log the error, and continue the loop on the
next tick. A consumer exception SHALL NOT silently kill the worker
`asyncio.Task` — the queue item is still dequeued and the worker continues.

`CancelledError` (a `BaseException`) SHALL propagate past the `except
Exception` clauses to the graceful-shutdown drain path. The stats background
job SHALL catch non-`CancelledError` exceptions from its reads, log, and
continue on its next tick.

#### Scenario: Transient producer error does not kill the loop
- **WHEN** a producer coroutine raises an `Exception` (e.g. DB timeout)
- **THEN** the orchestrator emits a trace DEBUG record plus an `error(...)` narrative record, and the loop continues on the next tick

#### Scenario: Transient consumer error does not kill the worker
- **WHEN** the consumer callable raises an `Exception` while processing a queue message
- **THEN** the orchestrator emits a trace DEBUG record plus an `error(...)` narrative record, the queue item is dequeued, and the worker continues

#### Scenario: CancelledError preserves graceful shutdown
- **WHEN** the producer or consumer receives `asyncio.CancelledError` during shutdown
- **THEN** `CancelledError` propagates past `except Exception` to the graceful-drain path

### Requirement: Orchestrator.stop is idempotent and exception-safe

`Orchestrator.stop()` SHALL be idempotent: callable multiple times safely;
the second invocation returns immediately with no effect.

`stop()` SHALL be exception-safe: a failure in one cleanup step
(`clouds.stop()`, `repository.disconnect_all()`, `http_session.close()`)
SHALL NOT skip the remaining steps. A cleanup-step failure SHALL be logged.
Background jobs that died with a non-`CancelledError` exception before
shutdown SHALL be caught and logged without aborting the cleanup chain.

#### Scenario: stop() runs cleanup body exactly once
- **WHEN** `orch.stop()` is called twice
- **THEN** the cleanup body executes exactly once; the second invocation returns immediately

#### Scenario: failing cleanup step does not skip remaining steps
- **WHEN** `await clouds.stop()` raises an `Exception` during `orch.stop()`
- **THEN** the failure is logged, and `stop()` proceeds to `repository.disconnect_all()` and `http_session.close()`

### Requirement: Free-machine selection gated on DB-enabled nodes

The `allocate_task` use case SHALL only consider a machine allocatable
when its `node_id` is enabled in `yascheduler_nodes`. The free-machine
selection helper SHALL read `uow.nodes.list_enabled()` in the same Unit of
Work it opens for `uow.tasks.list_by_status({RUNNING})`, and filter
`MachineRepository.list_free(platforms)` down to sessions whose
`machine.node_id` is in the enabled set AND not in the busy-node node_ids
derived from RUNNING tasks.

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

The free-machine selection helper SHALL isolate per-session failures: a
single stale session's exception is caught and logged, and the loop continues
to the next free session. If no free session succeeds, the helper SHALL return
`False` so the caller proceeds to the cloud-provisioning branch.

#### Scenario: Stale session failure does not abort the loop
- **WHEN** `free_sessions` contains two sessions and the first raises during per-session invocation
- **THEN** the exception is caught and logged, the loop continues to the second session, and the allocator does not propagate the exception


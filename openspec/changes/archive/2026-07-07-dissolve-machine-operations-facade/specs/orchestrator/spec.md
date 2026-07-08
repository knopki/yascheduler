## MODIFIED Requirements

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

The `Orchestrator` SHALL type `self._repository` as `MachineRepository`
(Protocol). The orchestrator's `_start_task_on_machine` SHALL be a thin
wrapper that resolves `ncpus` via `uow.nodes.get_by_id(task.allocated_node_id)`
(falling back to `session.get_cpu_cores()` when the node is absent) and
delegates the actual upload + spawn to
`self._task_deployer.start_task_on_machine(session, ...)`. The orchestrator
SHALL NOT contain any reference to adapter-specific methods (`get_sftp`,
`get_path`, `get_quote`, `run_full`).

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
- **THEN** all 4 loops begin executing concurrently, using `uow_factory` for all persistence queries, `repository` for all SSH collection operations, and the three collaborators (`task_deployer`, `output_downloader`, `occupancy_checker`) for use-case-side per-machine SSH operations

#### Scenario: Graceful shutdown

- **WHEN** `await orchestrator.stop()` is called
- **THEN** all loops receive cancellation, pending queue items are drained, and connections are closed via `repository.disconnect_all()`

#### Scenario: No adapter imports at runtime

- **WHEN** `orchestrator.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: Task deployment delegated to TaskDeployer resolves session by allocated_node_id

- **WHEN** the orchestrator allocates a task to a machine
- **THEN** the orchestrator resolves a `session` via `repository.get_session(task.allocated_node_id)`, resolves `ncpus` via `uow.nodes.get_by_id(task.allocated_node_id)` (falling back to `session.get_cpu_cores()` when the node is absent), and calls `self._task_deployer.start_task_on_machine(session, engine, task, ncpus, self._remote_defaults.engines_dir)` — never touches `get_sftp`, `get_path`, or `get_quote` directly, never keys a session lookup by `ip`

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
producer SHALL compute cloud capacity via the inline `_clouds_get_capacity`
method (UoW read of `uow.nodes.list_all()` + `Counter` over
`active_clouds`). SSH collection operations SHALL use `MachineRepository`.
The orchestrator SHALL pass its `occupancy_checker` instance into each
`allocate_task` invocation. The `_allocator_consumer` SHALL NOT apply
`@backoff.on_exception` — retry logic lives in the adapter.

#### Scenario: Task allocated in order

- **WHEN** multiple TO_DO tasks exist
- **THEN** tasks are allocated up to the configured `allocate_limit` concurrently

#### Scenario: Cloud capacity computed inline

- **WHEN** `_allocator_producer` determines the task limit
- **THEN** `_clouds_get_capacity` opens a UoW, reads `uow.nodes.list_all()`, counts nodes per cloud, and returns `max(0, sum(max_nodes for c in active_clouds) - sum(current_counts for c in active_clouds))`

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. Queue messages SHALL
carry domain `Task` objects. The orchestrator SHALL pass its
`output_downloader` instance into each `consume_task` invocation. The
`session` is resolved via `repository.get_session(task.allocated_node_id)`.

The orchestrator SHALL maintain an in-process `set[TaskId]` of in-flight consume
task ids (`self._consuming`). The consume producer SHALL skip yielding a task
whose id is in `self._consuming`. The consume consumer SHALL add the task id to
`self._consuming` before awaiting `consume_task` and remove it in a `finally`
block so a failed consume does not permanently block re-yield.

The orchestrator SHALL maintain an in-process `set[NodeId]` of node_ids whose
occupancy check has been started (`self._occupancy_started`). On the first
consumer tick for a task, the orchestrator SHALL add `task.allocated_node_id`
to `_occupancy_started` and call
`self._occupancy_checker.start_occupancy_check(session, engine)`. On finalised
consume, the orchestrator SHALL discard the node_id from `_occupancy_started`.

#### Scenario: Consume task in-flight guard

- **WHEN** the consume producer is about to yield a task whose id is in `self._consuming`
- **THEN** the producer skips it and moves to the next RUNNING task

#### Scenario: Consume task id removed after completion

- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the consumer's `finally` block removes the task id from `self._consuming`, allowing a future producer cycle to yield the task again if it is still RUNNING

#### Scenario: Session resolved by allocated_node_id

- **WHEN** `_task_consumer_consumer` runs for a task with `allocated_node_id=NodeId(7)`
- **THEN** it calls `self._repository.get_session(NodeId(7))` once at the top; if `None`, the `MACHINE_GONE` path runs; if a session is returned, it is threaded through the consumer body

#### Scenario: occupancy_started keyed by NodeId

- **WHEN** `_task_consumer_consumer` starts an occupancy check for a task with `allocated_node_id=NodeId(7)`
- **THEN** `NodeId(7)` is added to `self._occupancy_started`; on finalised consume, `NodeId(7)` is discarded

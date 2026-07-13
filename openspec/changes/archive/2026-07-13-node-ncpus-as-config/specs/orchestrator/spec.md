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

The `Orchestrator` SHALL type `repository` as `MachineRepository`
(Protocol). The orchestrator's
`_start_task_on_machine` SHALL be a thin wrapper that resolves `ncpus` via
`uow.nodes.get_by_id(task.allocated_node_id)`: if the resolved `Node` exists
AND its `ncpus` is not `None`, the stored value is used directly (operator-set
static config); otherwise (node absent OR `node.ncpus is None`) the orchestrator
falls back to `session.get_cpu_cores()` (memoized per session — see the
ssh-infrastructure spec) and delegates the actual upload + spawn to
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
- **THEN** the orchestrator resolves a `session` via `repository.get_session(task.allocated_node_id)`, resolves `ncpus` via `uow.nodes.get_by_id(task.allocated_node_id)` — using the stored value when `node.ncpus is not None`, falling back to `session.get_cpu_cores()` when the node is absent OR `node.ncpus is None` — and calls `task_deployer.start_task_on_machine(session, engine, task, ncpus, remote_defaults.engines_dir)` — never touches `get_sftp`, `get_path`, or `get_quote` directly, never keys a session lookup by `ip`

#### Scenario: Orchestrator uses static ncpus when node carries a positive value

- **WHEN** the orchestrator deploys a task whose allocated `Node.ncpus == 8`
- **THEN** `session.get_cpu_cores()` is NOT called and `8` is passed to `task_deployer.start_task_on_machine`

#### Scenario: Orchestrator discovers ncpus when node carries None

- **WHEN** the orchestrator deploys a task whose allocated `Node.ncpus is None`
- **THEN** `session.get_cpu_cores()` is called (returning the session-cached value on cache hits) and its result is passed to `task_deployer.start_task_on_machine`

#### Scenario: Orchestrator does not import Config

- **WHEN** `orchestrator.py` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears (TYPE_CHECKING or runtime); the orchestrator imports `LocalSettings` and `RemoteDefaults` from `yascheduler.domain` under TYPE_CHECKING

#### Scenario: Orchestrator constructed with unpacked settings and three collaborators

- **WHEN** `Orchestrator(...)` is constructed by the composition root
- **THEN** the call passes `local_settings=` and `remote_defaults=` keyword arguments (instances of `LocalSettings` and `RemoteDefaults`), not a `Config` aggregate; the `list_private_keys_fn` callable is passed as before; `repository=`, `task_deployer=`, `output_downloader=`, and `occupancy_checker=` are passed as separate keyword arguments

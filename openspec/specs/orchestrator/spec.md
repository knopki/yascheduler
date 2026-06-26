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

#### Scenario: Completed task consumed
- **WHEN** a RUNNING task's machine reports `state=FREE`
- **THEN** `consume_task` is called with `task_id` to download outputs

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

#### Scenario: New node connected
- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via gateway and the machine is registered

#### Scenario: Connection failure caught as domain error
- **WHEN** `gateway.connect(...)` fails
- **THEN** the orchestrator catches `MachineConnectionError` and logs the error

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

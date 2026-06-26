## MODIFIED Requirements

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
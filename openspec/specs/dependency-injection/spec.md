# Dependency Injection

## Purpose

Factory functions that wire up entry-point-specific dependencies, ensuring
each entry point instantiates only the adapters it needs.

## Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log:
Logger | None = None, *, clouds: CloudProvisionerImpl | None = None) ->
Orchestrator` factory function, exposed at `yascheduler.entrypoints.di`.
The `Config` aggregate SHALL be imported from
`yascheduler.entrypoints.config` (not `yascheduler.config`). The function
SHALL create a `PostgresUnitOfWork` factory and pass it to the
`Orchestrator` instead of a `DB` instance. It SHALL construct the SSH
infrastructure directly as TWO ports — a `MachineRepository` (instantiated
as `SSHMachineRepository`) and a `MachineOperations` (instantiated as
`SSHMachineOperations` receiving the repository), then inject them into
the consumers that previously took a single `gateway`. It SHALL NOT
construct a single `SSHMachineGateway`. It SHALL NOT import from
`remote_machine/`, `clouds/`, or `infra/ssh/gateway.py` (deleted). It
SHALL NOT import from `infra/ssh/helpers.py` (deleted).

The function SHALL NOT create a `DB` instance, SHALL NOT run schema
migration, and SHALL NOT accept a `db` parameter. Schema migration is the
operator's responsibility (run `yainit` before starting the daemon).

The function SHALL construct `CloudProvisionerImpl` without a `node_repo`
parameter — the adapter is a pure cloud-API client. The function SHALL
construct an `AllocationTracker`, an `asyncio.Lock` for allocation
serialization, and a filtered `active_clouds` list (clouds with
`max_nodes > 0` AND a successfully resolved adapter), passing all three
to the `Orchestrator` alongside the `clouds` instance.

The function SHALL NOT pass `adapters` or `configs` dicts to the
`Orchestrator` — provider selection is delegated to the
`clouds.select_provider` port method, and `adapters`/`configs` stay on
`CloudProvisionerImpl`.

The function SHALL unpack the `Config` aggregate when constructing the
`Orchestrator`: `config.local` SHALL be passed as the `local_settings`
parameter, `config.remote` SHALL be passed as the `remote_defaults`
parameter, and `list_private_keys` from `yascheduler.infra.ssh.keys` SHALL
be passed as the `list_private_keys_fn` callable. The `Orchestrator` SHALL
NOT receive the `Config` aggregate itself.

The composition root SHALL NOT introduce a DB-facade class. Persistence is
accessed only via `PostgresUnitOfWork` and the repository ports
(`TaskRepository`, `NodeRepository`). No module in
`yascheduler.entrypoints.di` SHALL import from `yascheduler.db` (the
module is removed) or from `yascheduler.config` (the package is removed).

The composition root SHALL NOT use `typing.cast` to bridge between the
domain `CloudConfig` Protocol and the infra `ConfigCloud` Union. The
`typing.cast` symbol SHALL NOT be imported by `yascheduler.entrypoints.di`.

#### Scenario: make_daemon returns orchestrator with UoW factory

- **WHEN** `make_daemon(config)` is called with a valid Config
- **THEN** returns an Orchestrator wired with `uow_factory`, `repository: MachineRepository` (an `SSHMachineRepository` instance), `operations: MachineOperations` (an `SSHMachineOperations` instance), `CloudProvisionerImpl`, `AllocationTracker`, `allocation_lock`, `active_clouds`, `local_settings=config.local`, `remote_defaults=config.remote`, and `list_private_keys_fn=list_private_keys` — without creating `DB`, without running schema migration, and without creating `RemoteMachineRepository` or a single `SSHMachineGateway`

#### Scenario: make_daemon accepts pre-built clouds

- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the provided `clouds` are wired to the orchestrator; no `DB` is created and no schema migration runs

#### Scenario: make_daemon unpacks Config into orchestrator

- **WHEN** `make_daemon(config)` is inspected for how it constructs `Orchestrator`
- **THEN** it passes `local_settings=config.local` and `remote_defaults=config.remote` (not `config=config`); the `Orchestrator` never receives the aggregate

#### Scenario: make_daemon imports Config from entrypoints

- **WHEN** `yascheduler.entrypoints.di` is inspected for its `Config` import
- **THEN** it imports `Config` from `yascheduler.entrypoints.config` (or `yascheduler.entrypoints`), not from `yascheduler.config`

#### Scenario: No DB-facade import in the composition root

- **WHEN** `yascheduler.entrypoints.di` is imported
- **THEN** it does NOT import `DB` from `yascheduler.db`, and no `DB`-like facade class is introduced; persistence is wired only via `PostgresUnitOfWork`; it does NOT import from `yascheduler.config`

#### Scenario: No cast bridges in the composition root

- **WHEN** `yascheduler/entrypoints/di.py` is parsed with `ast` and walked for
  `Call` nodes whose function is the bare name `cast` or the attribute
  `typing.cast`, and for `ImportFrom` from `typing` binding the name `cast`
- **THEN** zero matches are found

#### Scenario: active_clouds built without cast

- **WHEN** `make_daemon` is inspected for the construction of the `active_clouds`
  value in the `clouds is None` branch (the loop appending resolved configs) and
  in the `clouds is not None` branch (the list comprehension filtering by
  `max_nodes > 0` and `cfg.prefix in resolved_prefixes`)
- **THEN** neither branch wraps its result in `cast("list[ConfigCloud]", ...)`

### Requirement: make_cli_deps factory

The system SHALL provide a `make_cli_deps(config: Config) -> CLIDeps`
factory function, exposed at `yascheduler.entrypoints.di`, that creates
lightweight dependencies for CLI commands.

#### Scenario: CLI deps do not create SSH connections
- **WHEN** `make_cli_deps(config)` is called
- **THEN** no SSH connections or cloud providers are instantiated

#### Scenario: CLI deps include submit use case
- **WHEN** `make_cli_deps(config)` is called
- **THEN** the returned CLIDeps has a `submit` attribute usable for task
  submission

### Requirement: DI factories in yascheduler.entrypoints.di

The system SHALL expose DI factories from `yascheduler.entrypoints.di`. The
module SHALL NOT import from `remote_machine/` or `clouds/`. The module is
a resident of the `yascheduler.entrypoints` layer and is subject to the
`layers` contract (R3); its imports flow `entrypoints → infra →
application → domain`.

#### Scenario: Import factories
- **WHEN** `from yascheduler.entrypoints.di import make_daemon, make_cli_deps` is executed
- **THEN** both functions are available

#### Scenario: Import factories via entrypoints facade
- **WHEN** `from yascheduler.entrypoints import make_daemon, make_cli_deps` is executed
- **THEN** both functions are available (re-exported by the `entrypoints` layer facade)

### Requirement: Each factory creates only needed dependencies

The system SHALL ensure each factory instantiates only the adapters required
by that entry point's use cases.

#### Scenario: CLI factory is lightweight
- **WHEN** `make_cli_deps(config)` is compared to `make_daemon(config)`
- **THEN** the CLI factory creates fewer dependencies (no SSH pool, no cloud
  manager, no webhook notifier)

### Requirement: Yascheduler deps_factory test seam

The `Yascheduler.__init__` constructor SHALL accept an optional
keyword-only `deps_factory: Callable[[Config], CLIDeps]` parameter. When
`deps_factory is None`, the constructor SHALL lazily default to
`make_cli_deps` (invoked per query call, not cached). The factory passed
via `deps_factory` SHALL be invoked as `<factory>(self.config)` exactly
once per `queue_get_tasks_async` call to obtain a fresh `CLIDeps`,
mirroring the per-call construction pattern already used by
`queue_submit_task_async`.

The factory invocation SHALL be synchronous (not awaited).

#### Scenario: deps_factory defaults to make_cli_deps
- **WHEN** `Yascheduler()` is constructed without `deps_factory`
- **THEN** the first `queue_get_tasks_async` call invokes `make_cli_deps(self.config)` to obtain `CLIDeps`

#### Scenario: deps_factory injects a test double
- **WHEN** `Yascheduler(deps_factory=lambda cfg: fake_deps)` is constructed with a `fake_deps` whose `uow_factory` returns a `FakeUnitOfWork`
- **THEN** `queue_get_tasks_async` uses the injected `fake_deps.uow_factory` and does not call `make_cli_deps`

#### Scenario: deps_factory is keyword-only
- **WHEN** `Yascheduler(config_path, logger, lambda cfg: fake_deps)` is called with the factory positionally
- **THEN** `TypeError` is raised

#### Scenario: Factory is invoked once per query call
- **WHEN** `queue_get_tasks_async` is called twice on the same `Yascheduler` instance with `deps_factory` set to a counting spy
- **THEN** the factory callable is invoked twice (no caching; a fresh `CLIDeps` is produced each time)

#### Scenario: Factory invocation is synchronous
- **WHEN** `queue_get_tasks_async` invokes the configured `deps_factory`
- **THEN** the factory callable returns `CLIDeps` directly (it is NOT awaited; `deps_factory` is not declared `async` and the result is used synchronously)

### Requirement: make_daemon shares one SSHMachineGateway on the production path

On the `clouds is None` branch, `make_daemon` SHALL construct exactly one
`SSHMachineRepository` instance and inject the SAME instance into both
`CloudProvisionerImpl.machine_gateway` (renamed to
`machine_repository`) and `Orchestrator.repository`. It SHALL ALSO
construct exactly one `SSHMachineOperations` instance bound to that
repository and inject it into `Orchestrator.operations` (and into
`CloudProvisionerImpl.machine_operations` if it needs any operations-side
methods — current `CloudProvisionerImpl` uses only `setup_node` and
`get_cpu_cores`, both on operations). This ensures a single `_machines`
registry spans cloud setup (via `_setup_vm`) and orchestrator runtime,
so that connections opened during cloud allocation are visible to the
orchestrator and are reaped by `Orchestrator.stop()` via
`repository.disconnect_all()`.

The pre-built-clouds (`clouds is not None`) branch is out of scope: it
SHALL continue to construct a fresh `SSHMachineRepository` and
`SSHMachineOperations` pair for the orchestrator while the caller-supplied
`clouds` retain whatever repository/operations they were built with.
This branch is exercised only by unit tests and performs no real
allocations.

This requirement exists to prevent two correctness defects that arise from
split registries: (1) every allocated cloud node leaks one SSH connection
for the process lifetime because the cloud gateway is never drained, and
(2) the orchestrator opens a second connection to each cloud VM because its
`contains(ip)` filter inspects only its own registry.

#### Scenario: clouds is None shares one repository instance

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** the `SSHMachineRepository` instance passed as
  `CloudProvisionerImpl.machine_repository` SHALL be the same object (`is`) as
  the instance passed as `Orchestrator.repository`

#### Scenario: clouds is None shares one operations instance

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** the `SSHMachineOperations` instance passed to `Orchestrator.operations` SHALL be the same object (`is`) as the instance passed to `CloudProvisionerImpl.machine_operations` (if the latter is wired); both share the same `repository` reference

#### Scenario: clouds is None constructs exactly one SSHMachineRepository

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `SSHMachineRepository(...)` SHALL be invoked exactly once across the
  construction of `CloudProvisionerImpl` and `Orchestrator`

#### Scenario: clouds is None constructs exactly one SSHMachineOperations

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `SSHMachineOperations(repository=..., log=...)` SHALL be invoked
  exactly once across the construction of `CloudProvisionerImpl` and
  `Orchestrator`; the single instance is shared by both consumers on the
  production path

#### Scenario: pre-built clouds path keeps its own repository/operations

- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the orchestrator SHALL be constructed with a `repository` and an
  `operations` pair that are freshly-constructed `SSHMachineRepository` /
  `SSHMachineOperations`, NOT taken from `my_clouds`; the caller-supplied
  `clouds` instance SHALL be wired to the orchestrator unchanged

#### Scenario: cloud-allocation connections are visible to orchestrator

- **WHEN** a cloud node is allocated via `clouds.allocate(provider)` and
  `_setup_vm` connects it via `machine_repository.connect(ip)`
- **THEN** a subsequent `_connect_machine_producer` cycle in the orchestrator
  SHALL observe `repository.contains(ip) == True` for that node and SHALL NOT
  call `repository.connect(ip)` again for it

#### Scenario: cloud-allocation connections are reaped at shutdown

- **WHEN** `Orchestrator.stop()` runs after one or more cloud nodes have been
  allocated on the `clouds is None` path
- **THEN** `repository.disconnect_all()` SHALL close every connection opened by
  `_setup_vm`, leaving no cloud-setup SSH connection open at process exit

# Delta: dependency-injection

## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an
`async make_daemon(config: Config, *, clouds: CloudProvisionerImpl | None = None) -> Orchestrator`
factory function, exposed at `yascheduler.entrypoints.di`. The `Config`
aggregate SHALL be imported from `yascheduler.entrypoints.config` (or
re-exported by `yascheduler.entrypoints`). The function SHALL create a
`PostgresUnitOfWork` factory and pass it to the `Orchestrator`. It SHALL
construct a `SSHMachineRepository` and three stateless collaborator instances
(`TaskDeployer`, `OutputDownloader`, `OccupancyChecker` from
`yascheduler.infra`) and pass the repository and the three collaborators to
the `Orchestrator`.

#### Scenario: Config imported from entrypoints

- **WHEN** `yascheduler.entrypoints.di` is inspected for its `Config` import
- **THEN** it imports `Config` from `yascheduler.entrypoints.config` (or `yascheduler.entrypoints`)

#### Scenario: No DB-facade import in the composition root

- **WHEN** `yascheduler.entrypoints.di` is imported
- **THEN** it does NOT import a `DB` facade, and no `DB`-like facade class is introduced; persistence is wired only via `PostgresUnitOfWork`

#### Scenario: Three collaborators constructed without log argument

- **WHEN** `make_daemon(config)` is called
- **THEN** exactly one instance each of `TaskDeployer()`, `OutputDownloader()`, `OccupancyChecker()` is constructed with no arguments; all three are passed to `Orchestrator(...)` as `task_deployer=`, `output_downloader=`, `occupancy_checker=` keyword arguments

#### Scenario: make_daemon does not accept a log parameter

- **WHEN** `make_daemon` is inspected for its signature
- **THEN** it is declared `async def make_daemon(config, *, clouds=None) -> Orchestrator` with no `log` parameter

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
module is a resident of the `yascheduler.entrypoints` layer and is subject
to the `layers` contract (R3); its imports flow
`entrypoints → infra → application → domain`.

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
once per `queue_get_tasks_async` call to obtain a fresh `CLIDeps`.

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

### Requirement: make_daemon shares one SSHMachineRepository on the production path

On the `clouds is None` branch, `make_daemon` SHALL construct exactly one
`SSHMachineRepository` instance and inject the SAME instance into both
`CloudProvisionerImpl.machine_repository` and `Orchestrator.repository`.

The pre-built-clouds (`clouds is not None`) branch SHALL construct a fresh
`SSHMachineRepository` for the orchestrator; the caller-supplied `clouds`
retain whatever repository they were built with.

#### Scenario: clouds is None shares one repository instance

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** the `SSHMachineRepository` instance passed as `CloudProvisionerImpl.machine_repository` SHALL be the same object (`is`) as the instance passed as `Orchestrator.repository`

#### Scenario: CloudProvisionerImpl constructed without operations port or log

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `CloudProvisionerImpl(...)` SHALL be invoked with `machine_repository=` but WITHOUT any `machine_operations=` (or equivalent operations-side) keyword argument AND WITHOUT any `log=` keyword argument

#### Scenario: clouds is None constructs three collaborator instances

- **WHEN** `make_daemon(config)` is called without a `clouds` argument
- **THEN** `TaskDeployer()`, `OutputDownloader()`, and `OccupancyChecker()` SHALL each be invoked exactly once with no arguments; all three instances are passed to `Orchestrator(...)`

#### Scenario: pre-built clouds path keeps its own repository

- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the orchestrator SHALL be constructed with a `repository` that is a freshly-constructed `SSHMachineRepository` (without `log=`), NOT taken from `my_clouds`; the caller-supplied `clouds` instance SHALL be wired to the orchestrator unchanged

#### Scenario: cloud-allocation connections are visible to orchestrator

- **WHEN** a cloud node is allocated and connected via the shared repository
- **THEN** a subsequent orchestrator cycle SHALL observe `repository.contains(node.node_id) == True` for that node and SHALL NOT open a second connection

#### Scenario: cloud-allocation connections are reaped at shutdown

- **WHEN** `Orchestrator.stop()` runs after one or more cloud nodes have been allocated on the `clouds is None` path
- **THEN** `repository.disconnect_all()` SHALL close every connection opened during cloud allocation, leaving no cloud-setup SSH connection open at process exit

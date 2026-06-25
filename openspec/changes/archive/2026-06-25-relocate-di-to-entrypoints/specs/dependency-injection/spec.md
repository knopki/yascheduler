## MODIFIED Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log:
Logger | None = None, *, clouds: CloudProvisionerImpl | None = None) ->
Orchestrator` factory function, exposed at `yascheduler.entrypoints.di`.
The function SHALL create a `PostgresUnitOfWork` factory and pass it to the
`Orchestrator` instead of a `DB` instance. It SHALL wire `SSHMachineGateway`
directly — no `RemoteMachineRepository`. It SHALL NOT import from
`remote_machine/` or `clouds/`.

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

The composition root SHALL NOT introduce a DB-facade class. Persistence is
accessed only via `PostgresUnitOfWork` and the repository ports
(`TaskRepository`, `NodeRepository`). No module in
`yascheduler.entrypoints.di` SHALL import from `yascheduler.db` (the
module is removed).

#### Scenario: make_daemon returns orchestrator with UoW factory
- **WHEN** `make_daemon(config)` is called with a valid Config
- **THEN** returns an Orchestrator wired with `uow_factory`, `SSHMachineGateway`, `CloudProvisionerImpl`, `AllocationTracker`, `allocation_lock`, and `active_clouds` — without creating `DB`, without running schema migration, and without creating `RemoteMachineRepository`

#### Scenario: make_daemon accepts pre-built clouds
- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the provided `clouds` are wired to the orchestrator; no `DB` is created and no schema migration runs

#### Scenario: No DB-facade import in the composition root
- **WHEN** `yascheduler.entrypoints.di` is imported
- **THEN** it does NOT import `DB` from `yascheduler.db`, and no `DB`-like facade class is introduced; persistence is wired only via `PostgresUnitOfWork`

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
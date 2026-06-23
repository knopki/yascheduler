# Dependency Injection

## Purpose

Factory functions that wire up entry-point-specific dependencies, ensuring
each entry point instantiates only the adapters it needs.

## Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log:
Logger | None = None, *, clouds: CloudProvisionerImpl | None = None) ->
Orchestrator` factory function. The function SHALL create a
`PostgresUnitOfWork` factory and pass it to the `Orchestrator` instead of
a `DB` instance. It SHALL wire `SSHMachineGateway` directly — no
`RemoteMachineRepository`. It SHALL NOT import from `remote_machine/` or
`clouds/`.

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

#### Scenario: make_daemon returns orchestrator with UoW factory
- **WHEN** `make_daemon(config)` is called with a valid Config
- **THEN** returns an Orchestrator wired with `uow_factory`, `SSHMachineGateway`, `CloudProvisionerImpl`, `AllocationTracker`, `allocation_lock`, and `active_clouds` — without creating `DB`, without running schema migration, and without creating `RemoteMachineRepository`

#### Scenario: make_daemon accepts pre-built dependencies
- **WHEN** `make_daemon(config, db=my_db, clouds=my_clouds)` is called
- **THEN** the provided `db` is used for schema migration and the provided `clouds` are wired to the orchestrator

#### Scenario: make_daemon accepts pre-built clouds
- **WHEN** `make_daemon(config, clouds=my_clouds)` is called
- **THEN** the provided `clouds` are wired to the orchestrator; no `DB` is created and no schema migration runs

#### Scenario: No DB import in make_daemon
- **WHEN** `di.py` is imported
- **THEN** it does NOT import `DB` from `yascheduler.db`

### Requirement: make_cli_deps factory

The system SHALL provide a `make_cli_deps(config: Config) -> CLIDeps` factory
function that creates lightweight dependencies for CLI commands.

#### Scenario: CLI deps do not create SSH connections
- **WHEN** `make_cli_deps(config)` is called
- **THEN** no SSH connections or cloud providers are instantiated

#### Scenario: CLI deps include submit and query use cases
- **WHEN** `make_cli_deps(config)` is called
- **THEN** the returned CLIDeps has `submit` and `query` attributes usable
  for task submission and status checking

### Requirement: DI factories in yascheduler.di

The system SHALL expose DI factories from `yascheduler.di`. The module SHALL
NOT import from `remote_machine/` or `clouds/`.

#### Scenario: Import factories
- **WHEN** `from yascheduler.di import make_daemon, make_cli_deps` is executed
- **THEN** both functions are available

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

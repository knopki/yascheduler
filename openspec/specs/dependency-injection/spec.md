# Dependency Injection

## Purpose

Factory functions that wire up entry-point-specific dependencies, ensuring
each entry point instantiates only the adapters it needs.

## Requirements

### Requirement: make_daemon factory

The system SHALL provide an `async make_daemon(config: Config, log: Logger | None = None, *, db: DB | None = None, clouds: CloudAPIManager | None = None) -> Orchestrator`
factory function that creates all dependencies needed for the daemon entry point.

#### Scenario: make_daemon returns ready orchestrator
- **WHEN** `make_daemon(config)` is called with a valid Config
- **THEN** returns an Orchestrator with wired use cases, DB, machine gateway, and cloud provisioner

#### Scenario: make_daemon accepts pre-built dependencies
- **WHEN** `make_daemon(config, db=my_db, clouds=my_clouds)` is called
- **THEN** the provided `db` and `clouds` are used instead of creating new ones

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

The system SHALL expose DI factories from `yascheduler.di`.

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

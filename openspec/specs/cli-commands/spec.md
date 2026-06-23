# CLI Commands

## Purpose

Define how CLI commands are wired to use cases via dependency injection,
how entry points resolve to the correct module, and how backward compatibility
is maintained through utils.py re-exports.

## Requirements

### Requirement: CLI commands call use cases via DI

The system SHALL implement each CLI command as a function that obtains
dependencies from di.py and delegates to use cases. The `init` command is
an exception — it performs infrastructure setup (service installation + schema
application) directly.

#### Scenario: yasubmit calls SubmitTask
- **WHEN** yasubmit is invoked with valid arguments
- **THEN** make_cli_deps() is called, SubmitTask use case is invoked, task_id is printed

#### Scenario: yastatus calls query use case
- **WHEN** yastatus is invoked
- **THEN** task statuses are queried via use case and displayed

#### Scenario: yascheduler starts daemon via orchestrator
- **WHEN** yascheduler is invoked
- **THEN** make_daemon() is called and orchestrator.start() is awaited

#### Scenario: yainit applies schema synchronously
- **WHEN** yainit is invoked
- **THEN** service files are installed and `apply_schema()` is called synchronously to initialize the database

### Requirement: yainit uses apply_schema adapter

The `yainit` command (`init()` in `infra/cli/init.py`) SHALL be a plain
synchronous function that calls `apply_schema(config.db)` from
`infra/persistence/postgres_schema.py` for database initialization.

#### Scenario: yainit initializes database
- **WHEN** `yainit` is invoked
- **THEN** `apply_schema(config.db)` is called synchronously, schema is applied transactionally, and no async/`@to_sync` wrapper is used

### Requirement: Entry points updated

The system SHALL update pyproject.toml console_scripts to point to
adapters.cli.commands instead of utils.

#### Scenario: yasubmit resolves to new location
- **WHEN** yasubmit is executed from the command line
- **THEN** adapters.cli.commands:submit is invoked

#### Scenario: All 6 commands functional
- **WHEN** each CLI command is invoked with --help
- **THEN** usage information is displayed (commands resolve correctly)

### Requirement: utils.py preserves re-exports

The system SHALL keep utils.py as a re-export module importing from
adapters.cli.commands.

#### Scenario: Direct import of utils.submit still works
- **WHEN** from yascheduler.utils import submit is executed
- **THEN** the function from adapters.cli.commands is returned

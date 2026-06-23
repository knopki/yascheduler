## MODIFIED Requirements

### Requirement: yainit uses apply_schema adapter

The `yainit` command (`init()` in `infra/cli/init.py`) SHALL be a plain
synchronous function that calls `apply_schema(config.db)` from
`infra/persistence/postgres_schema.py` for database initialization.

#### Scenario: yainit initializes database
- **WHEN** `yainit` is invoked
- **THEN** `apply_schema(config.db)` is called synchronously, schema is applied transactionally, and no async/`@to_sync` wrapper is used

### Requirement: Entry points updated

The system SHALL update pyproject.toml console_scripts to point to
infra.cli.commands instead of utils.

#### Scenario: yasubmit resolves to new location
- **WHEN** yasubmit is executed from the command line
- **THEN** infra.cli.commands:submit is invoked

#### Scenario: All 6 commands functional
- **WHEN** each CLI command is invoked with --help
- **THEN** usage information is displayed (commands resolve correctly)

### Requirement: utils.py preserves re-exports

The system SHALL keep utils.py as a re-export module importing from
infra.cli.commands.

#### Scenario: Direct import of utils.submit still works
- **WHEN** from yascheduler.utils import submit is executed
- **THEN** the function from infra.cli.commands is returned

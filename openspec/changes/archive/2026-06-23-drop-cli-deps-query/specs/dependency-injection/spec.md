## MODIFIED Requirements

### Requirement: make_cli_deps factory

The system SHALL provide a `make_cli_deps(config: Config) -> CLIDeps` factory
function that creates lightweight dependencies for CLI commands.

#### Scenario: CLI deps do not create SSH connections
- **WHEN** `make_cli_deps(config)` is called
- **THEN** no SSH connections or cloud providers are instantiated

#### Scenario: CLI deps include submit use case
- **WHEN** `make_cli_deps(config)` is called
- **THEN** the returned CLIDeps has a `submit` attribute usable for task
  submission

## MODIFIED Requirements

### Requirement: Dependency injection factories

Tests SHALL verify:
- `CLIDeps` stores fields and delegates `submit`
- `make_cli_deps` returns `CLIDeps` with `PostgresUnitOfWork` factory
- `make_daemon` creates all dependencies and accepts optional `db`/`clouds`
- `make_aiida` raises `NotImplementedError`

#### Scenario: make_cli_deps returns CLIDeps with PostgresUnitOfWork factory
- **WHEN** `make_cli_deps(config)` is called
- **THEN** the returned `CLIDeps.engines` matches `config.engines` and `uow_factory()` returns a `PostgresUnitOfWork`

## MODIFIED Requirements

### Requirement: E2E test fixtures
The project SHALL provide session-scoped and function-scoped pytest fixtures in `tests/e2e/conftest.py` that set up a complete test environment:
- Session-scoped PostgreSQL container (testcontainers) with schema applied via `apply_schema()` from `infra/persistence/postgres_schema.py`
- Session-scoped SSH container (testcontainers `openssh-server`) with generated key pair
- Session-scoped config fixture that creates a temp directory with minimal INI file (`[db]` + `[engine.test_shell]`), test engine script (`run.sh`) in `data/engines/test_shell/`, and SSH key symlink in `data/keys/`
- Session-scoped `Config` instance parsed from the generated INI
- Function-scoped persistence fixtures: a raw `pg8000.native.Connection` (`pg_conn`), a single-worker `ThreadPoolExecutor` (`pg_executor`), and a `uow_factory` callable returning a `PostgresUnitOfWork` constructed with `_db_config` and a bare `MessageBus()`. Teardown SHALL `TRUNCATE yascheduler_tasks, yascheduler_nodes CASCADE` via `pg_conn`. The fixtures SHALL NOT yield a `DB` instance (the class is removed).
- Function-scoped orchestrator fixture that creates but does not start an `Orchestrator` instance

The `YASCHEDULER_CONF_PATH` environment variable SHALL be set to the generated INI path for the duration of the session.

#### Scenario: Config fixture provides valid Config with test engine
- **WHEN** the session-scoped config fixture is resolved
- **THEN** `config.engines` contains exactly one engine named `test_shell` with `spawn="{engine_path}/run.sh"`, `check_pname="sleep"`, `input_files=("1.input",)`, `output_files=("1.input.out",)`, `deployable` containing one `LocalFilesDeploy` pointing to `run.sh`

#### Scenario: Persistence fixtures provide empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node via `uow_factory`
- **THEN** the second test sees zero nodes (the `pg_conn` teardown TRUNCATEs both tables)

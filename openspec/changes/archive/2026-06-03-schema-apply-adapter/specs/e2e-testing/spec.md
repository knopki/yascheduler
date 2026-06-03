## MODIFIED Requirements

### Requirement: E2E test fixtures

The project SHALL provide session-scoped and function-scoped pytest fixtures in
`tests/e2e/conftest.py` that set up a complete test environment:
- Session-scoped PostgreSQL container (testcontainers) with schema applied via
  `apply_schema()` from `adapters/persistence/postgres_schema.py`
- Session-scoped SSH container (testcontainers `openssh-server`) with generated key pair
- Session-scoped config fixture that creates a temp directory with minimal INI file (`[db]` + `[engine.test_shell]`), test engine script (`run.sh`) in `data/engines/test_shell/`, and SSH key symlink in `data/keys/`
- Session-scoped `Config` instance parsed from the generated INI
- Function-scoped `db` fixture providing a fresh DB connection with TRUNCATE teardown
- Function-scoped orchestrator fixture that creates but does not start an `Orchestrator` instance

The `YASCHEDULER_CONF_PATH` environment variable SHALL be set to the generated INI path for the duration of the session.

#### Scenario: Config fixture provides valid Config with test engine
- **WHEN** the session-scoped config fixture is resolved
- **THEN** `config.engines` contains exactly one engine named `test_shell` with `spawn="{engine_path}/run.sh"`, `check_pname="sleep"`, `input_files=("1.input",)`, `output_files=("1.input.out",)`, `deployable` containing one `LocalFilesDeploy` pointing to `run.sh`

#### Scenario: DB fixture provides empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node
- **THEN** the second test sees zero nodes

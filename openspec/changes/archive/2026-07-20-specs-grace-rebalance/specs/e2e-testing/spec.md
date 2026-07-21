## MODIFIED Requirements

### Requirement: E2E test fixtures

The project SHALL provide session-scoped and function-scoped pytest fixtures
that set up a complete test environment:

- Session-scoped PostgreSQL container (testcontainers) with schema applied.
- Session-scoped `ssh_pool` fixture: a list of TWO SSH containers
  (testcontainers `openssh-server`) started from ONE generated keypair
  (shared `PUBLIC_KEY` env). Each container yields its own
  `get_container_host_ip()` and mapped port 2222. Both containers share
  the same `username`.
- Session-scoped config fixture that creates a temp directory with minimal
  INI file (`[db]` + `[engine.test_shell]`), test engine script (`run.sh`)
  in `data/engines/test_shell/`, and a SINGLE SSH private key symlink in
  `data/keys/` (the shared keypair used by both `ssh_pool` containers).
- Session-scoped `Config` instance parsed from the generated INI.
- Function-scoped persistence fixtures: a raw pg8000 connection (`pg_conn`),
  a single-worker executor, and a `uow_factory` callable returning a
  `PostgresUnitOfWork`. Teardown SHALL `TRUNCATE yascheduler_tasks,
  yascheduler_nodes CASCADE` via `pg_conn`.
- Function-scoped `log_records` fixture: an in-memory `logging.Handler`
  subclass that appends every stdlib `LogRecord` to a list, attached to the
  `"yascheduler"` logger at DEBUG level for the test duration and removed in
  teardown. The fixture SHALL expose the captured records so tests can
  assert on the block-marker message and the structured fields (exposed as
  programmatic attributes on each record via stdlib `extra={...}` semantics)
  instead of parsing the rendered message string. Records emitted by any
  `yascheduler.*` descendant logger propagate to the `"yascheduler"` parent
  logger (standard stdlib propagation) and are captured.
- Function-scoped orchestrator fixture that creates but does not start an
  `Orchestrator` instance.

The `YASCHEDULER_CONF_PATH` environment variable SHALL be set to the
generated INI path for the duration of the session.

The `log_records` fixture description is brought in line with the
`logging` capability: production modules emit trace records via stdlib
`logger.debug(msg, extra={...})` calls on `logging.getLogger(__name__)`
loggers; the fixture captures those records by attaching a handler to the
`"yascheduler` parent logger.

#### Scenario: Config fixture provides valid Config with test engine
- **WHEN** the session-scoped config fixture is resolved
- **THEN** `config.engines` contains exactly one engine named `test_shell` with `spawn="{engine_path}/run.sh"`, `check_pname="sleep"`, `input_files=("1.input",)`, `output_files=("1.input.out",)`, `deployable` containing one `LocalFilesDeploy` pointing to `run.sh`

#### Scenario: Persistence fixtures provide empty database per test
- **WHEN** two E2E tests run sequentially and the first inserts a node via `uow_factory`
- **THEN** the second test sees zero nodes (the `pg_conn` teardown TRUNCATEs both tables)

#### Scenario: log_records fixture captures yascheduler trace records for the test duration
- **GIVEN** the `log_records` fixture is active
- **WHEN** the orchestrator emits a trace record via `logger.debug("BLOCK", extra={...})` on its module-local `logging.getLogger(__name__)` logger
- **THEN** the captured record exposes the block marker (the positional debug message) as a programmatic attribute
- **AND** the captured record exposes the structured fields (the `extra` dict keys) as programmatic attributes
- **AND** after the test, the handler is removed from the `"yascheduler"` logger

#### Scenario: log_records fixture captures records via propagation from module-local loggers
- **GIVEN** the `log_records` fixture attaches a handler to the `"yascheduler"` logger
- **WHEN** a descendant `yascheduler.application.allocate_task` logger (bound via `logging.getLogger(__name__)`) emits a trace record
- **THEN** the record propagates to the `"yascheduler"` parent logger and is present in the captured list

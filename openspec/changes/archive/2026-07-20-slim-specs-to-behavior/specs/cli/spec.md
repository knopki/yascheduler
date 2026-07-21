## MODIFIED Requirements

### Requirement: CLI commands call use cases via DI

Each CLI command SHALL obtain dependencies from DI and delegate to use cases.
All six commands and three daemon launchers SHALL accept `--config` and
`--log-level` via shared helpers. The five non-daemon CLI commands SHALL be
synchronous `def` entry points calling
`asyncio.run(_<name>_async(argv))` with `argv: list[str] | None = None` for
testability.

`yainit` performs infrastructure setup directly (no DI, no use case): service
file install and/or `apply_schema(config.db)` + `apply_migrations(config.db)`.

#### Scenario: yasubmit calls SubmitTask
- **WHEN** yasubmit is invoked with valid arguments
- **THEN** `make_cli_deps()` is called, `SubmitTask` use case is invoked via `CLIDeps.submit`, task_id is printed to stdout

#### Scenario: yainit is a bootstrap entrypoint without DI
- **WHEN** `yainit` is invoked (with any combination of `--schema` / `--daemon` / no flags)
- **THEN** `init()` performs infrastructure setup (service install and/or schema apply + migration apply) directly via `apply_schema(config.db)` and `apply_migrations(config.db)`, and service-template file writes, without calling `make_cli_deps` or any use case

#### Scenario: missing config file exits 2
- **WHEN** any CLI command or daemon launcher is invoked with `--config /nonexistent.conf`
- **THEN** argparse prints `not a file: /nonexistent.conf` to stderr and exits 2 (via the `existing_path` validator)

#### Scenario: invalid log level exits 2
- **WHEN** any CLI command or daemon launcher is invoked with `--log-level WARN`
- **THEN** argparse rejects it with exit 2 (only `WARNING` is accepted, not the `WARN` alias)

#### Scenario: five CLI commands use asyncio.run
- **WHEN** `submit`, `show_nodes`, `manage_node`, or `check_status` is inspected
- **THEN** the entry point is a synchronous `def f(argv: list[str] | None = None)` that calls `asyncio.run(_f_async(argv))`

#### Scenario: yainit with no flags installs service and applies schema and migrations
- **WHEN** `yainit` is invoked with no flags
- **THEN** the systemd or sysv service file is installed (auto-detected) and `apply_schema(config.db)` followed by `apply_migrations(config.db)` is called synchronously to initialize the database; the process exits `0` on success

#### Scenario: yainit --daemon installs only the service
- **WHEN** `yainit --daemon` is invoked
- **THEN** the auto-detected service file (systemd or sysv) is written, `apply_schema` and `apply_migrations` are NOT called, and `init()` exits `0` on success

#### Scenario: yainit --config honors the path
- **WHEN** `yainit --config /custom/yascheduler.conf` is invoked
- **THEN** `Config.from_config_parser("/custom/yascheduler.conf")` is called (passed through to `apply_schema(config.db)` and `apply_migrations(config.db)`)

#### Scenario: yainit initializes database idempotently
- **WHEN** `yainit --schema` (or the default invocation) is run against an already-initialized database
- **THEN** `apply_schema(config.db)` succeeds (because `schema.sql` uses `CREATE TABLE IF NOT EXISTS` and the DO block `to_regclass` guard) and `apply_migrations(config.db)` succeeds (the tracker already records all applied migrations, so none are pending), and `init()` exits `0`

#### Scenario: yainit exits 1 on DatabaseError from apply_schema or apply_migrations
- **WHEN** `apply_schema(config.db)` or `apply_migrations(config.db)` raises `DatabaseError` (e.g. connection refused, authentication failure, migration SQL error)
- **THEN** `init()` prints the error and exits `1`

#### Scenario: yainit exits 1 on service file write failure
- **WHEN** writing the service file raises `OSError` (e.g. permission denied, missing `/etc/systemd/system/` or `/etc/init.d/` parent directory, disk full)
- **THEN** `init()` prints `Error: cannot write to <path>: <error>` and exits `1`

#### Scenario: yainit installs systemd unit on a systemd host
- **WHEN** `yainit` service install is requested on a host managed by systemd
- **THEN** the systemd unit template is rendered and written to `/etc/systemd/system/yascheduler.service`

#### Scenario: yainit installs sysv init script on a non-systemd host
- **WHEN** `yainit` service install is requested on a host NOT managed by systemd
- **THEN** the sysv init script template is rendered and written to `/etc/init.d/yascheduler` with `chmod 0755`

#### Scenario: yasubmit parses AiiDA script and submits task
- **WHEN** yasubmit is invoked with a valid script file path
- **THEN** the script is parsed, the engine is validated against `config.engines`, input files are read, metadata is built, and `deps.submit(...)` is called

#### Scenario: yasubmit entry point uses asyncio.run
- **WHEN** the `submit` callable is inspected
- **THEN** it is a synchronous `def submit(argv: list[str] | None = None)` that calls `asyncio.run(_submit_async(argv))`

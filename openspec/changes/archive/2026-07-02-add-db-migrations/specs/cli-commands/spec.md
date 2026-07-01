## MODIFIED Requirements

### Requirement: CLI commands call use cases via DI

The system SHALL implement each CLI command as a function that obtains
dependencies from di.py and delegates to use cases. The `yainit` command is a
bootstrap entrypoint: it performs infrastructure setup (service installation
and/or schema application and migration application) directly, without DI, and
lives in the `entrypoints/cli/` layer. The `yanodes` command is an execution-query
entrypoint that reads nodes and running tasks via a UoW and lives in
`entrypoints/cli/`. The `yasubmit` command is an execution-write entrypoint
that parses an AiiDA script file, builds task metadata, and submits a task
via `CLIDeps.submit` (which delegates to the `submit_task` use case); it
lives in `entrypoints/cli/`. The `yasetnode` command is an execution-mutate
entrypoint that adds, soft-removes, or hard-removes nodes via a UoW (and via
`SSHMachineRepository` + `SSHMachineOperations` for the add path's optional
remote setup); it lives in `entrypoints/cli/`. The `yastatus` command is an
execution-query entrypoint that reads tasks (and, in verbose mode, remote
machine output) via `CLIDeps` and the SSH repository/operations; it lives in
`entrypoints/cli/`. The `yascheduler` command (`daemonize` in
`entrypoints/cli/daemonize.py`) starts the daemon via
`make_daemon()` and `orchestrator.start()`, delegating the async runtime and
signal handling to `daemon_common.run_daemon` (see the `daemon-common`
capability); it lives in `entrypoints/cli/`. All six CLI commands live in
`entrypoints/cli/`.

All six CLI commands and the three daemon launchers (`daemonize`,
`daemon_systemd`, `daemon_sysv`) SHALL accept `--config PATH` (default
`CONFIG_FILE`, validated by `existing_path` — a missing config file exits 2)
and `--log-level` (default `WARNING` for `yainit`/`yanodes`/`yasubmit`/
`yasetnode`/`yastatus`; default `INFO` for the three daemon launchers), via
the shared `args.py` helpers (see the `cli-args` capability). The five
non-daemon CLI commands SHALL apply `logging.getLevelName(args.log_level)` to
the root logger. The three daemon launchers SHALL additionally accept
`--log-file PATH` (default `None` → stderr for `daemonize` and
`daemon_systemd`; default `LOG_FILE` for `daemon_sysv`) via
`add_log_file_arg`.

The five non-daemon CLI commands (`init`, `show_nodes`, `submit`,
`manage_node`, `check_status`) SHALL be synchronous `def` entry points that
call `asyncio.run(_<name>_async(argv))` on a private `async def` coroutine.
Each entry point SHALL accept an `argv: list[str] | None = None` parameter
(None reads `sys.argv`) for testability.

The `yainit` command (`init()` in `entrypoints/cli/init.py`) SHALL be a plain
synchronous function. When schema application is requested (default invocation
or `--schema`), it SHALL call `apply_schema(config.db)` followed by
`apply_migrations(config.db)` (see the `db-migrations` capability), where
`config` is loaded from `Config.from_config_parser(args.config)` (honoring
`--config`). The `_init_schema` helper SHALL accept a `config_path: str =
CONFIG_FILE` parameter so `init()` can pass `args.config`, and SHALL call both
`apply_schema(config.db)` and `apply_migrations(config.db)` in that order.
When service installation is requested, `init()` SHALL detect systemd via
`Path("/run/systemd/system").is_dir()` (NOT by shelling out to `pidof systemd`),
render the matching template, and SHALL overwrite the existing service file on
re-run (instead of silently skipping). Service file write failures
(`OSError`, including missing `/etc/systemd/system/` or `/etc/init.d/` parent
directory) SHALL cause `init()` to print the error and exit `1`.

#### Scenario: yasubmit calls SubmitTask
- **WHEN** yasubmit is invoked with valid arguments
- **THEN** make_cli_deps() is called, SubmitTask use case is invoked via CLIDeps.submit, task_id is printed to stdout

#### Scenario: yastatus queries tasks via CLIDeps
- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** make_cli_deps() is called, tasks are read via `uow.tasks.list_by_status({RUNNING, TO_DO})` (default) or `uow.tasks.list_by_jobs(job_ids)` (with `-j`), and the selected renderer prints the result

#### Scenario: yascheduler starts daemon via orchestrator
- **WHEN** yascheduler is invoked
- **THEN** `make_daemon(config, logger)` is called via `daemon_common.run_daemon` and `orchestrator.start()` is awaited inside `asyncio.run(run_daemon(config, logger))`

#### Scenario: yainit is a bootstrap entrypoint without DI
- **WHEN** `yainit` is invoked (with any combination of `--schema` / `--daemon` / no flags)
- **THEN** `init()` performs infrastructure setup (service install and/or schema apply + migration apply) directly via `apply_schema(config.db)` and `apply_migrations(config.db)`, and service-template file writes, without calling `make_cli_deps` or any use case

#### Scenario: yainit applies migrations after schema
- **WHEN** `yainit` is invoked with schema application requested (no flags, or `--schema`, or `--schema --daemon`)
- **THEN** `apply_schema(config.db)` is called synchronously, then `apply_migrations(config.db)` is called synchronously (in that order), and `init()` exits `0` on success

#### Scenario: yainit --schema applies only the schema and migrations
- **WHEN** `yainit --schema` is invoked
- **THEN** `apply_schema(config.db)` and `apply_migrations(config.db)` are called synchronously in that order, no service file is written, and `init()` exits `0` on success

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW
- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineRepository` and an `SSHMachineOperations` (bound to that repository) are constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened via `async with deps.uow_factory() as uow:` solely to read `already_there = await uow.nodes.get(spec.host) is not None` (it is closed without commit — nothing was mutated), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the repository and operations are passed to the add helper.

#### Scenario: all six CLI commands accept --config
- **WHEN** any of `yascheduler`, `yainit`, `yanodes`, `yasubmit`, `yasetnode`, `yastatus` is invoked with `--config /path/to/yascheduler.conf`
- **THEN** `Config.from_config_parser("/path/to/yascheduler.conf")` is called instead of the hardcoded `CONFIG_FILE`

#### Scenario: all six CLI commands accept --log-level
- **WHEN** any of `yascheduler`, `yainit`, `yanodes`, `yasubmit`, `yasetnode`, `yastatus` is invoked with `--log-level DEBUG`
- **THEN** the root logger is configured at `DEBUG` (via `logging.getLevelName("DEBUG")` for the five CLI commands, or via `configure_logger(..., level=logging.DEBUG)` for the three daemon launchers)

#### Scenario: missing config file exits 2
- **WHEN** any CLI command or daemon launcher is invoked with `--config /nonexistent.conf`
- **THEN** argparse prints `not a file: /nonexistent.conf` to stderr and exits 2 (via the `existing_path` validator in `args.py`)

#### Scenario: invalid log level exits 2
- **WHEN** any CLI command or daemon launcher is invoked with `--log-level WARN`
- **THEN** argparse rejects it with exit 2 (only `WARNING` is accepted, not the `WARN` alias)

#### Scenario: five CLI commands use asyncio.run
- **WHEN** `submit`, `show_nodes`, `manage_node`, or `check_status` is inspected
- **THEN** the entry point is a synchronous `def f(argv: list[str] | None = None)` that calls `asyncio.run(_f_async(argv))`

#### Scenario: yascheduler console_script points at entrypoints/cli/daemonize
- **WHEN** the `yascheduler` console_script in `pyproject.toml` is inspected
- **THEN** it points at `yascheduler.entrypoints.cli.daemonize:daemonize`

#### Scenario: yainit with no flags installs service and applies schema and migrations
- **WHEN** `yainit` is invoked with no flags
- **THEN** the systemd or sysv service file is installed (auto-detected) and `apply_schema(config.db)` followed by `apply_migrations(config.db)` is called synchronously to initialize the database; the process exits `0` on success

#### Scenario: yainit --daemon installs only the service
- **WHEN** `yainit --daemon` is invoked
- **THEN** the auto-detected service file (systemd or sysv) is written, `apply_schema` and `apply_migrations` are NOT called, and `init()` exits `0` on success

#### Scenario: yainit --schema --daemon runs both (equals default)
- **WHEN** `yainit --schema --daemon` is invoked
- **THEN** the service file is installed AND `apply_schema(config.db)` followed by `apply_migrations(config.db)` is called (identical to the no-flags default), and `init()` exits `0` on success

#### Scenario: yainit --help shows argparse usage
- **WHEN** `yainit --help` is invoked
- **THEN** argparse prints the standard help screen listing `--config`, `--log-level`, `--schema`, and `--daemon` with their descriptions, and exits `0`

#### Scenario: yainit with an unknown flag exits 2
- **WHEN** `yainit --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yainit --config honors the path
- **WHEN** `yainit --config /custom/yascheduler.conf` is invoked
- **THEN** `Config.from_config_parser("/custom/yascheduler.conf")` is called (passed through `_init_schema(args.config)` to `apply_schema(config.db)` and `apply_migrations(config.db)`)

#### Scenario: yainit --config missing file exits 2
- **WHEN** `yainit --config /nonexistent.conf` is invoked
- **THEN** argparse prints `not a file: /nonexistent.conf` to stderr and exits `2`

#### Scenario: yainit initializes database idempotently
- **WHEN** `yainit --schema` (or the default invocation) is run against an already-initialized database
- **THEN** `apply_schema(config.db)` succeeds (because `schema.sql` uses `CREATE TABLE IF NOT EXISTS` and the DO block `to_regclass` guard) and `apply_migrations(config.db)` succeeds (the tracker already records all applied migrations, so none are pending), and `init()` exits `0`

#### Scenario: yainit exits 1 on DatabaseError from apply_schema or apply_migrations
- **WHEN** `apply_schema(config.db)` or `apply_migrations(config.db)` raises `DatabaseError` (e.g. connection refused, authentication failure, migration SQL error)
- **THEN** `init()` prints the error and exits `1`

#### Scenario: yainit exits 1 on service file write failure
- **WHEN** writing the service file raises `OSError` (e.g. permission denied, missing `/etc/systemd/system/` or `/etc/init.d/` parent directory, disk full)
- **THEN** `init()` prints `Error: cannot write to <path>: <error>` and exits `1`

#### Scenario: yainit overwrites existing systemd unit file
- **WHEN** `yainit --daemon` (or the default) is invoked on a systemd host and `/etc/systemd/system/yascheduler.service` already exists
- **THEN** the file is overwritten with the freshly rendered template content and `init()` exits `0`

#### Scenario: yainit overwrites existing sysv init script
- **WHEN** `yainit --daemon` (or the default) is invoked on a sysv host and `/etc/init.d/yascheduler` already exists
- **THEN** the file is overwritten with the freshly rendered template content, `chmod 0755` is applied, and `init()` exits `0`

#### Scenario: yainit detects systemd via /run/systemd/system
- **WHEN** `yainit` service install is requested and `/run/systemd/system/` exists as a directory
- **THEN** the systemd unit template is rendered and written to `/etc/systemd/system/yascheduler.service`

#### Scenario: yainit detects non-systemd host
- **WHEN** `yainit` service install is requested and `/run/systemd/system/` does NOT exist
- **THEN** the sysv init script template is rendered and written to `/etc/init.d/yascheduler` with `chmod 0755`
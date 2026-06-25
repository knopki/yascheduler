## MODIFIED Requirements

### Requirement: CLI commands call use cases via DI

The system SHALL implement each CLI command as a function that obtains
dependencies from di.py and delegates to use cases. The `yainit` command is a
bootstrap entrypoint: it performs infrastructure setup (service installation
and/or schema application) directly, without DI, and lives in the
`entrypoints/cli/` layer. The `yanodes` command is an execution-query
entrypoint that reads nodes and running tasks via a UoW and lives in
`entrypoints/cli/`. The `yasubmit` command is an execution-write entrypoint
that parses an AiiDA script file, builds task metadata, and submits a task
via `CLIDeps.submit` (which delegates to the `submit_task` use case); it
lives in `entrypoints/cli/`. The `yasetnode` command is an execution-mutate
entrypoint that adds, soft-removes, or hard-removes nodes via a UoW (and via
`SSHMachineGateway` for the add path's optional remote setup); it lives in
`entrypoints/cli/`. The `yastatus` command is an execution-query entrypoint
that reads tasks (and, in verbose mode, remote machine output) via `CLIDeps`
and the SSH gateway; it lives in `entrypoints/cli/`. The `yascheduler` command
(`daemonize` in `entrypoints/cli/daemonize.py`) starts the daemon via
`make_daemon()` and `orchestrator.start()`, delegating the async runtime and
signal handling to `daemon_common.run_daemon` (see the `daemon-common`
capability); it lives in `entrypoints/cli/`. All six CLI commands now live in
`entrypoints/cli/`; `yascheduler/infra/cli/` is liquidated.

All six CLI commands and the three daemon launchers (`daemonize`,
`daemon_systemd`, `daemon_sysv`) SHALL accept `--config PATH` (default
`CONFIG_FILE`, validated by `existing_path` — a missing config file exits 2)
and `--log-level` (default `WARNING` for `yainit`/`yanodes`/`yasubmit`/
`yasetnode`/`yastatus`; default `INFO` for the three daemon launchers), via
the shared `args.py` helpers (see the `cli-args` capability). The five
non-daemon CLI commands SHALL replace their hardcoded `logging.WARN` (or
unconfigured root logger) with `logging.getLevelName(args.log_level)` applied
to the root logger. The three daemon launchers SHALL additionally accept
`--log-file PATH` (default `None` → stderr for `daemonize` and
`daemon_systemd`; default `LOG_FILE` for `daemon_sysv`) via
`add_log_file_arg`.

The five non-daemon CLI commands (`init`, `show_nodes`, `submit`,
`manage_node`, `check_status`) SHALL be synchronous `def` entry points that
call `asyncio.run(_<name>_async(argv))` on a private `async def` coroutine,
NOT `@to_sync`-decorated async functions. The thread-offload branch of
`to_sync` never fires for CLI entry points (no async caller invokes them);
`asyncio.run` is explicit and equivalent. `to_sync` stays in
`yascheduler/shared/async_utils.py` for `client.py`'s legitimate
cross-context use. Each entry point SHALL accept an `argv: list[str] | None =
None` parameter (None reads `sys.argv`) for testability.

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
- **THEN** `init()` performs infrastructure setup (service install and/or schema apply) directly via `apply_schema(config.db)` and service-template file writes, without calling `make_cli_deps` or any use case

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW
- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called (NOT the hardcoded `CONFIG_FILE`), `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineGateway` is constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened via `async with deps.uow_factory() as uow:` solely to read `already_there = await uow.nodes.get(spec.host) is not None` (it is closed without commit — nothing was mutated), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the gateway is passed to the add helper.

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

#### Scenario: five CLI commands use asyncio.run, not @to_sync
- **WHEN** `submit`, `show_nodes`, `manage_node`, or `check_status` is inspected
- **THEN** the entry point is a synchronous `def f(argv: list[str] | None = None)` that calls `asyncio.run(_f_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

#### Scenario: yascheduler console_script points at entrypoints/cli/daemonize
- **WHEN** the `yascheduler` console_script in `pyproject.toml` is inspected
- **THEN** it points at `yascheduler.entrypoints.cli.daemonize:daemonize` (NOT `yascheduler.infra.cli.daemonize:daemonize`)

#### Scenario: infra/cli/ is liquidated
- **WHEN** the `yascheduler/infra/cli/` directory is inspected
- **THEN** it does not exist (both `daemonize.py` and `__init__.py` are deleted)

### Requirement: Entry points updated

The system SHALL update pyproject.toml console_scripts to point to
`yascheduler.entrypoints.cli.init` for `yainit`, to
`yascheduler.entrypoints.cli.show_nodes` for `yanodes`, to
`yascheduler.entrypoints.cli.submit` for `yasubmit`, to
`yascheduler.entrypoints.cli.manage_node` for `yasetnode`, to
`yascheduler.entrypoints.cli.check_status` for `yastatus`, and to
`yascheduler.entrypoints.cli.daemonize` for `yascheduler`. All six CLI
commands now resolve to `yascheduler.entrypoints.cli.*`; no console_script
points at `yascheduler.infra.cli.*`.

#### Scenario: yainit resolves to the new location
- **WHEN** `yainit` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.init:init` is invoked

#### Scenario: yanodes resolves to the new location
- **WHEN** `yanodes` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.show_nodes:show_nodes` is invoked

#### Scenario: yasubmit resolves to the new location
- **WHEN** `yasubmit` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.submit:submit` is invoked

#### Scenario: yastatus resolves to the new location
- **WHEN** `yastatus` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.check_status:check_status` is invoked

#### Scenario: yascheduler resolves to the new location
- **WHEN** `yascheduler` is executed from the command line
- **THEN** `yascheduler.entrypoints.cli.daemonize:daemonize` is invoked (NOT `yascheduler.infra.cli.daemonize:daemonize`)

#### Scenario: All 6 commands functional
- **WHEN** each CLI command is invoked with `--help`
- **THEN** usage information is displayed (commands resolve correctly)

The `yainit` command (`init()` in `entrypoints/cli/init.py`) SHALL be a plain
synchronous function. When schema application is requested, it SHALL call
`apply_schema(config.db)` from `infra/persistence/postgres_schema.py`, where
`config` is loaded from `Config.from_config_parser(args.config)` (honoring
`--config`). The `_init_schema` helper SHALL accept a `config_path: str =
CONFIG_FILE` parameter so `init()` can pass `args.config`. When service
installation is requested, `init()` SHALL detect systemd via
`Path("/run/systemd/system").is_dir()` (NOT by shelling out to `pidof systemd`),
render the matching template, and SHALL overwrite the existing service file on
re-run (instead of silently skipping). Service file write failures
(`OSError`, including missing `/etc/systemd/system/` or `/etc/init.d/` parent
directory) SHALL cause `init()` to print the error and exit `1`.

#### Scenario: yainit with no flags installs service and applies schema
- **WHEN** `yainit` is invoked with no flags
- **THEN** the systemd or sysv service file is installed (auto-detected) and `apply_schema(config.db)` is called synchronously to initialize the database; the process exits `0` on success

#### Scenario: yainit --schema applies only the schema
- **WHEN** `yainit --schema` is invoked
- **THEN** `apply_schema(config.db)` is called synchronously, no service file is written, and `init()` exits `0` on success

#### Scenario: yainit --daemon installs only the service
- **WHEN** `yainit --daemon` is invoked
- **THEN** the auto-detected service file (systemd or sysv) is written, `apply_schema` is NOT called, and `init()` exits `0` on success

#### Scenario: yainit --schema --daemon runs both (equals default)
- **WHEN** `yainit --schema --daemon` is invoked
- **THEN** the service file is installed AND `apply_schema(config.db)` is called (identical to the no-flags default), and `init()` exits `0` on success

#### Scenario: yainit --help shows argparse usage
- **WHEN** `yainit --help` is invoked
- **THEN** argparse prints the standard help screen listing `--config`, `--log-level`, `--schema`, and `--daemon` with their descriptions, and exits `0`

#### Scenario: yainit with an unknown flag exits 2
- **WHEN** `yainit --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yainit --config honors the path
- **WHEN** `yainit --config /custom/yascheduler.conf` is invoked
- **THEN** `Config.from_config_parser("/custom/yascheduler.conf")` is called (passed through `_init_schema(args.config)` to `apply_schema(config.db)`)

#### Scenario: yainit --config missing file exits 2
- **WHEN** `yainit --config /nonexistent.conf` is invoked
- **THEN** argparse prints `not a file: /nonexistent.conf` to stderr and exits `2`

#### Scenario: yainit initializes database idempotently
- **WHEN** `yainit --schema` (or the default invocation) is run against an already-initialized database
- **THEN** `apply_schema(config.db)` succeeds (because `schema.sql` uses `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN IF NOT EXISTS`) and `init()` exits `0`

#### Scenario: yainit exits 1 on DatabaseError from apply_schema
- **WHEN** `apply_schema(config.db)` raises `DatabaseError` (e.g. connection refused, authentication failure, type mismatch)
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

## ADDED Requirements

### Requirement: Daemon launcher argparse and defaults

Each daemon launcher SHALL build its own argparse parser via the `args.py`
helpers and call `daemon_common.run_daemon` with ready arguments (see the
`daemon-common` capability). The three launchers are `daemonize` in
`entrypoints/cli/daemonize.py`, `daemon_systemd` in
`entrypoints/cli/daemon_systemd.py`, and `daemon_sysv` in
`entrypoints/cli/daemon_sysv.py`. Each SHALL set `prog="yascheduler"` so
`--help` shows the product name. Each SHALL accept
`--config` (default `CONFIG_FILE`, `type=existing_path`) and `--log-level`
(default `INFO`, choices `["DEBUG","INFO","WARNING","ERROR","CRITICAL"]`).
Each SHALL accept `--log-file` (default `None` → stderr for `daemonize` and
`daemon_systemd`; default `LOG_FILE` for `daemon_sysv`).

`daemon_sysv.py` SHALL additionally accept `-p`/`--pid-file` (default
`PID_FILE`) and SHALL keep the short flag `-l`/`--log-file` for backward
compatibility with the installed `yascheduler.sh` init script, which invokes
`$yascheduler -p "$pidfile" -l "$logfile" "$OPTIONS"`. `--config` and
`--log-level` SHALL be long-only in `daemon_sysv.py` (no short flag collision
with `-l`, since `daemonize`'s `--log-level` is also long-only — the original
`-l` collision bug is fixed by each launcher parsing once and passing ready
values, not by re-parsing `sys.argv`).

`daemon_sysv.py` SHALL wrap the daemon execution in a `python-daemon`
`DaemonContext` with `working_directory="/"` (the `python-daemon` default, NOT
`os.path.dirname(__file__)`), `umask=0o002`, and
`pidfile=pidfile.TimeoutPIDLockFile(args.pid_file)`. The `configure_logger`
call SHALL happen INSIDE the `DaemonContext` so the `FileHandler`'s file
descriptor is the daemon's.

`daemon_systemd.py` SHALL NOT use `python-daemon`; it runs in the foreground
under systemd's supervision (logs to stderr → journald). Its `--log-file`
default is `None`.

The `daemonize` console_script (`yascheduler`) SHALL NOT use `python-daemon`;
it is intended for manual foreground execution (e.g. debugging, containers).
Its `--log-file` default is `None` (stderr).

#### Scenario: daemonize --help shows prog yascheduler
- **WHEN** `yascheduler --help` is invoked
- **THEN** the help text shows `usage: yascheduler [-h] [--config CONFIG] [--log-level {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [--log-file LOG_FILE]`

#### Scenario: daemonize default log-file is None (stderr)
- **WHEN** `yascheduler` is invoked with no `--log-file`
- **THEN** `configure_logger(log_file=None, ...)` is called; the root logger has only a `StreamHandler(sys.stderr)`, no `FileHandler`

#### Scenario: daemon_systemd default log-file is None (journald)
- **WHEN** `python daemon_systemd.py` is invoked with no `--log-file`
- **THEN** `configure_logger(log_file=None, ...)` is called; logs go to stderr, which systemd captures into journald

#### Scenario: daemon_sysv default log-file is LOG_FILE
- **WHEN** `python daemon_sysv.py` is invoked with no `--log-file`
- **THEN** `configure_logger(log_file=LOG_FILE, ...)` is called; the daemon writes to `/var/log/yascheduler.log` (or the `YASCHEDULER_LOG_PATH` override)

#### Scenario: daemon_sysv preserves -p and -l short flags
- **WHEN** `python daemon_sysv.py -p /var/run/yascheduler.pid -l /var/log/yascheduler.log` is invoked
- **THEN** `args.pid_file == "/var/run/yascheduler.pid"` and `args.log_file == "/var/log/yascheduler.log"` (compatible with `yascheduler.sh:47`)

#### Scenario: daemon_sysv --log-level is long-only (no -l collision)
- **WHEN** `python daemon_sysv.py --log-level DEBUG -l /var/log/yascheduler.log` is invoked
- **THEN** `args.log_level == "DEBUG"` and `args.log_file == "/var/log/yascheduler.log"` (no collision: `-l` is `--log-file`, `--log-level` is long-only)

#### Scenario: daemon_sysv working_directory is root
- **WHEN** `daemon_sysv.py` builds its `DaemonContext`
- **THEN** `working_directory="/"` is passed (NOT `os.path.dirname(__file__)`); the daemon's CWD is `/`

#### Scenario: daemon_sysv configure_logger inside DaemonContext
- **WHEN** `daemon_sysv.py` runs
- **THEN** `configure_logger(args.log_file, level)` is called INSIDE the `with daemon.DaemonContext(...)` block, so the `FileHandler` opens the file in the daemon's context

#### Scenario: daemonize accepts argv parameter for tests
- **WHEN** `daemonize(argv=["--config", "/tmp/test.conf", "--log-level", "DEBUG"])` is called from a test
- **THEN** the parser reads the explicit argv (NOT `sys.argv`); `args.config == "/tmp/test.conf"` and `args.log_level == "DEBUG"`

### Requirement: Daemon and CLI exit-code contract

All six CLI commands and the three daemon launchers SHALL follow the uniform
exit-code contract:

- `0` — success (clean shutdown for daemons, completed operation for CLI commands), and `--help`.
- `1` — runtime error caught by the top-level `try/except Exception`; the entry point prints `Error: <exception>` to stderr and calls `sys.exit(1)`.
- `2` — argparse error (unknown flag, missing positional, invalid choice) or `existing_path` `ArgumentTypeError` (missing `--config` file). argparse and the type validator handle this natively; the `except Exception` block SHALL NOT catch `SystemExit` (which is not an `Exception` subclass), so argparse's exit propagates.

The daemon entry points SHALL wrap `make_daemon`, `Config.from_config_parser`,
and `asyncio.run(run_daemon(...))` in `try: ... except Exception as e:
print(f"Error: {e}", file=sys.stderr); sys.exit(1)`. A bare traceback without
an `Error:` message is a defect.

#### Scenario: daemon runtime error exits 1 with Error message
- **WHEN** `make_daemon(config, logger)` raises `Exception("db connection refused")`
- **THEN** the daemon entry point prints `Error: db connection refused` to stderr and exits `1` (NOT a bare traceback)

#### Scenario: daemon argparse error exits 2
- **WHEN** `yascheduler --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`; the `except Exception` block is not reached

#### Scenario: daemon --help exits 0
- **WHEN** `yascheduler --help` is invoked
- **THEN** argparse prints the usage text to stdout and exits `0`

#### Scenario: CLI runtime error exits 1 with Error message
- **WHEN** `make_cli_deps(config)` raises `Exception("db unreachable")`
- **THEN** the CLI entry point prints `Error: db unreachable` to stderr and exits `1`

#### Scenario: SystemExit propagates past except Exception
- **WHEN** argparse calls `sys.exit(2)` inside the `try` block of an entry point
- **THEN** the `except Exception` block does NOT catch it (`SystemExit` is not an `Exception` subclass); the exit code is `2`
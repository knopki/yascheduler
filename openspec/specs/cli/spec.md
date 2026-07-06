# CLI

## Purpose

The six CLI command entry points (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`,
`yainit`, `yascheduler`), the three daemon launchers (`daemonize`,
`daemon_systemd`, `daemon_sysv`), the shared argparse helpers, and the async
daemon core. Each CLI command is a synchronous `def` entry point that calls
`asyncio.run(_<name>_async(argv))` and delegates to use cases via dependency
injection (`yainit` is a bootstrap exception).

## Requirements

### Requirement: Shared argparse helpers

`yascheduler/entrypoints/cli/args.py` SHALL provide reusable argparse helpers
consumed by all six CLI command entry points and the three daemon launchers:

- `existing_path(s: str) -> Path` — argparse type validator returning `Path(s)` if `s` is an existing file, else raising `argparse.ArgumentTypeError` (→ exit 2). Single source of truth for the "file must exist" validator.
- `add_config_arg(parser, *, default=CONFIG_FILE, dest="config")` — adds `--config PATH` with `type=existing_path`, so a missing config exits 2 with `not a file: <path>` (not a cryptic parse error). Default `CONFIG_FILE` is env-aware via `YASCHEDULER_CONF_PATH`.
- `add_log_level_arg(parser, *, default="WARNING", short=None)` — adds `--log-level` with explicit `choices=["DEBUG","INFO","WARNING","ERROR","CRITICAL"]`. When `short` is given (e.g. `"-l"`), it registers the short flag as alias. The caller MUST ensure no collision; `daemon_sysv.py` SHALL NOT pass `short="-l"` (it registers `-l`/`--log-file`). Resolves via `logging.getLevelName(args.log_level)` (NOT private `logging._nameToLevel`).
- `add_log_file_arg(parser, *, default=None)` — adds `--log-file PATH` (path string, no existence check; `FileHandler` fails loudly if unwritable). Used only by the three daemon entry points.

Each helper SHALL be a function mutating the passed parser (composing with the
caller's bespoke parser), NOT a base `ArgumentParser` subclass and NOT a single
shared dispatcher.

#### Scenario: existing_path returns Path for an existing file
- **WHEN** `existing_path("/etc/yascheduler/yascheduler.conf")` is called and the file exists
- **THEN** it returns `Path("/etc/yascheduler/yascheduler.conf")`

#### Scenario: existing_path raises ArgumentTypeError for a missing file
- **WHEN** `existing_path("/nonexistent.conf")` is called
- **THEN** it raises `argparse.ArgumentTypeError` with a message containing `not a file: /nonexistent.conf`

#### Scenario: add_log_level_arg rejects WARN alias
- **WHEN** a parser built with `add_log_level_arg(parser)` is given `--log-level WARN`
- **THEN** argparse rejects it with exit 2 (only `WARNING` is accepted, not the `WARN` alias)

#### Scenario: add_log_level_arg registers a short alias
- **WHEN** a parser built with `add_log_level_arg(parser, short="-l")` is given `-l DEBUG`
- **THEN** `args.log_level == "DEBUG"` (the `-l` short flag is an alias for `--log-level`)

#### Scenario: add_log_level_arg long-only by default
- **WHEN** a parser built with `add_log_level_arg(parser)` (no `short`) is given `-l DEBUG`
- **THEN** argparse rejects it with exit 2 (no short flag registered)

### Requirement: Shared daemon core for entry points

`yascheduler/entrypoints/cli/daemon_common.py` SHALL provide the shared daemon
runtime consumed by all three daemon entry points:

- `configure_logger(log_file: str | Path | None, level: int) -> logging.Logger` — configures the ROOT logger (so warnings from `aiohttp`, `pg8000`, `asyncio` reach the log file): always adds a `StreamHandler(sys.stderr)`, adds a `FileHandler(log_file)` only when `log_file is not None`, sets `backoff` and `asyncssh` loggers to `ERROR`, and calls `logging.captureWarnings(True)`. SHALL NOT call `logging.basicConfig`.
- `async def run_daemon(config: Config, logger: logging.Logger) -> None` — the async daemon core: `await make_daemon(config, logger)` to build the `Orchestrator`, register SIGTERM/SIGINT handlers on the running event loop (cancel outstanding tasks, sleep 250ms for SSL close, log "Done"), then `await orch.start()` wrapped in a `try/finally` whose `finally` clause awaits `orch.stop()`. Signal-handler registration lives in `run_daemon` (not the entry points) because `loop.add_signal_handler` requires a running loop.

Each daemon entry point SHALL be a synchronous `def` that builds its own argparse
parser via the `args.py` helpers, calls `configure_logger`, loads
`Config.from_config_parser(args.config)`, and invokes
`asyncio.run(run_daemon(config, logger))`. The entry points SHALL NOT register
signal handlers themselves.

#### Scenario: configure_logger writes to stderr when log_file is None
- **WHEN** `configure_logger(log_file=None, level=logging.INFO)` is called
- **THEN** the root logger has a `StreamHandler(sys.stderr)` and no `FileHandler`

#### Scenario: configure_logger writes to file and stderr when log_file is set
- **WHEN** `configure_logger(log_file="/tmp/y.log", level=logging.INFO)` is called
- **THEN** the root logger has both a `StreamHandler(sys.stderr)` and a `FileHandler` pointed at `/tmp/y.log`

#### Scenario: run_daemon is async
- **WHEN** `run_daemon` is inspected
- **THEN** it is declared `async def run_daemon(config, logger) -> None`

#### Scenario: run_daemon awaits make_daemon and orch.start
- **WHEN** `run_daemon(config, logger)` is awaited
- **THEN** `make_daemon(config, logger)` is awaited, SIGTERM/SIGINT handlers are registered on the running event loop, `orch.start()` is awaited, and the `finally` block awaits `orch.stop()` (idempotent per the `orchestrator` capability)

#### Scenario: start() exception propagates after cleanup
- **WHEN** `orch.start()` raises an exception
- **THEN** the `finally` block's `orch.stop()` still runs (cancelling early background jobs, closing the HTTP session) before the exception propagates out of `run_daemon`

#### Scenario: entry points call asyncio.run
- **WHEN** any of `daemonize.py`, `daemon_systemd.py`, `daemon_sysv.py` is inspected
- **THEN** the entry point is a synchronous `def` that calls `asyncio.run(run_daemon(...))`

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

### Requirement: yasubmit parses AiiDA script and submits task

The `yasubmit` command SHALL parse an AiiDA script file (key=value metadata
lines), read the engine's declared input files from the current working
directory, build the task metadata, and submit a task via `CLIDeps.submit`
(which delegates to the `submit_task` use case). The command is implemented
as `submit()` in `yascheduler/entrypoints/cli/submit.py`, a synchronous
entry point that calls `asyncio.run(_submit_async(argv))` (NOT
`@to_sync`-decorated; CLI entry points have no async caller). It SHALL
accept an `argv: list[str] | None = None` parameter for testability (`None`
reads `sys.argv`, the argparse convention; tests pass an explicit list). It
SHALL obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via
`make_cli_deps(config)`, parse the script into key=value pairs, validate
that an `ENGINE` key is present and known to `config.engines`, build the
metadata dict (including `local_folder`, the engine's input files, and the
webhook fields when `PARENT` is present and `config.local.webhook_url` is
set), and call `deps.submit(label, metadata, engine.name)`. The logic SHALL
be split into private pure functions: `_existing_path` (argparse type
validator), `_parse_submit_args(argv)`.

#### Scenario: yasubmit parses AiiDA script and submits task
- **WHEN** yasubmit is invoked with a valid script file path
- **THEN** the script is parsed, the engine is validated against `config.engines`, input files are read, metadata is built, and `deps.submit(...)` is called

#### Scenario: yasubmit entry point uses asyncio.run
- **WHEN** the `submit` callable in `yascheduler/entrypoints/cli/submit.py` is inspected
- **THEN** it is a synchronous `def submit(argv: list[str] | None = None)` that calls `asyncio.run(_submit_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

### Requirement: yasubmit parses flags via argparse

`submit()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasubmit",
description="Submit task to yascheduler via AiiDA script")` exposing one
positional argument:
- `script` (positional, `type=_existing_path`): the path to the AiiDA script
  file. `_existing_path(s)` SHALL return `Path(s)` if `s` is an existing
  file or raise `argparse.ArgumentTypeError(f"not a file: {s}")`, so a
  missing file is an argparse error (exit `2`), not a runtime error (exit
  `1`). This places argument-*shape* validation (the file exists) at the
  argparse layer, while argument-*content* validation (the `ENGINE` key is
  present; the engine name is known to config) remains in the body (exit
  `1`).

`submit()` SHALL NOT add `--json`, `--table`, or any output-mode flag. The
AiiDA scheduler plugin parses `int(stdout.strip())` on the success path
(see the AiiDA stdout compatibility requirement), so the success output is
fixed to `str(task_id)` and cannot be decorated.

#### Scenario: yasubmit --help shows argparse usage
- **WHEN** `yasubmit --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yasubmit"` and the `script` positional argument with its description, and exits `0`

#### Scenario: yasubmit with no arguments exits 2
- **WHEN** `yasubmit` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr (missing the required `script` argument) and exits `2`

#### Scenario: yasubmit with a non-existent script exits 2
- **WHEN** `yasubmit /nonexistent.in` is invoked
- **THEN** the `_existing_path` type validator raises `argparse.ArgumentTypeError("not a file: /nonexistent.in")`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasubmit with extra positional exits 2
- **WHEN** `yasubmit script.in extra.in` is invoked
- **THEN** argparse prints a usage error to stderr (unrecognized extra positional) and exits `2`

#### Scenario: yasubmit with an unknown flag exits 2
- **WHEN** `yasubmit --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasubmit prog is yasubmit in help and errors
- **WHEN** `yasubmit --help` or any argparse error is shown
- **THEN** the program name displayed is `yasubmit` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasubmit validates script content in the body

After argparse succeeds, `submit()` SHALL validate the script *content* in
the body (exit `1` on failure, NOT exit `2` — argparse cannot inspect file
content). The validations are:
- The script's parsed `script_params` dict MUST contain an `ENGINE` key. If
  absent, `submit()` SHALL raise `ValueError("Script has not defined an
  engine")`, print `Error: Script has not defined an engine` to stderr, and
  exit `1`.
- The `ENGINE` value MUST be a known engine name in `config.engines`. If
  `config.engines.get(engine_name)` returns `None`, `submit()` SHALL raise
  `ValueError(f"Engine {engine_name} is not supported")`, print the message
  to stderr, and exit `1`.

#### Scenario: yasubmit exits 1 when ENGINE key is missing
- **WHEN** `yasubmit script.in` is invoked with a script containing `LABEL = Test` but no `ENGINE = ...` line
- **THEN** `Error: Script has not defined an engine` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasubmit exits 1 when engine is unknown
- **WHEN** `yasubmit script.in` is invoked with a script containing `ENGINE = unknown` and `config.engines.get("unknown")` returns `None`
- **THEN** `Error: Engine unknown is not supported` is printed to stderr, nothing is printed to stdout, and the process exits `1`

### Requirement: yasubmit exit code contract

`submit()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success: `print(str(task_id))`, normal completion.
- `1` on runtime failure: `ENGINE` key missing, engine name unknown to
  config, DB error, config parse error, or any unexpected exception caught
  at the top level. The error SHALL be printed to stderr as
  `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error: argparse default (missing script arg, file not
  found via `type=_existing_path`, extra positional, unknown flag).

`submit()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yasubmit exits 0 on success
- **WHEN** `yasubmit script.in` is invoked and the submission completes without exception
- **THEN** `str(task_id)` is printed to stdout and the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yasubmit exits 1 on DB error
- **WHEN** `deps.submit(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasubmit exits 1 on config error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasubmit exits 1 on unexpected exception
- **WHEN** any other unexpected exception is raised during execution
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasubmit --help exits 0
- **WHEN** `yasubmit --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yasubmit missing script exits 2
- **WHEN** `yasubmit` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasubmit non-existent file exits 2
- **WHEN** `yasubmit /nonexistent.in` is invoked
- **THEN** argparse prints a usage error to stderr (the `_existing_path` validator rejected the path) and exits `2`

### Requirement: yasubmit preserves AiiDA stdout compatibility

The success path of `yasubmit` SHALL print exactly `str(task_id)` to stdout
— no prefix, no suffix, no JSON envelope, no decoration. The failure path
SHALL print nothing to stdout and an error message to stderr. This contract
SHALL be preserved exactly because the AiiDA scheduler plugin
(`entrypoints/aiida_plugin.py:_parse_submit_output`) parses
`int(stdout.strip())` and treats `ValueError` as "no task id received":
```python
output = stdout.strip()
try:
    int(output)
except ValueError:
    self.logger.error("Submitting failed, no task id received")
return output
```
`_get_submit_command` returns `f"{_CMD_PREFIX}yasubmit {submit_script}"`, so
AiiDA executes `yasubmit` as a subprocess over SSH transport and parses its
stdout. Any decoration of the success output breaks the consumer. This is
the key constraint distinguishing `yasubmit` from query-oriented commands
like `yanodes` (which has no machine consumer of its output and can freely
change format). `yasubmit` is a write command; the `--json` convention
established by `yanodes` applies to query-oriented commands only.

#### Scenario: yasubmit success prints only the task id
- **WHEN** `yasubmit script.in` succeeds and `deps.submit(...)` returns `42`
- **THEN** stdout contains exactly `42` (possibly with a trailing newline from `print`), with no prefix, suffix, JSON envelope, or other decoration

#### Scenario: yasubmit failure prints nothing to stdout
- **WHEN** `yasubmit script.in` fails (ENGINE key missing, engine unknown, DB error, or any exception)
- **THEN** stdout is empty; the error message is on stderr; the process exits `1` (or `2` for argparse errors)

#### Scenario: yasubmit does not add output-mode flags
- **WHEN** the `submit()` argparse parser is inspected
- **THEN** it does NOT define `--json`, `--table`, or any other output-mode flag (the success output is fixed to `str(task_id)`)

#### Scenario: AiiDA plugin is unchanged
- **WHEN** `entrypoints/aiida_plugin.py` is inspected
- **THEN** `_get_submit_command` still returns `f"{_CMD_PREFIX}yasubmit {submit_script}"` and `_parse_submit_output` still does `int(stdout.strip())` (the AiiDA contract is not touched)

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

`daemonize.py` (the foreground `yascheduler` console_script) SHALL accept the
short flag `-l`/`--log-level` for backward compatibility with the pre-refactor
behavior (`yascheduler -l DEBUG` worked before the
`consolidate-daemon-entrypoints` refactor regressed it to long-only). Because
`daemonize.py` registers `--log-file` via `add_log_file_arg` (long-only), `-l`
is free to alias `--log-level` with no collision. This is independent of
`daemon_sysv.py`'s `-l`/`--log-file`: each launcher parses its own argv once,
so there is no shared `sys.argv` re-parse to collide on.

`daemon_sysv.py` SHALL additionally accept `-p`/`--pid-file` (default
`PID_FILE`) and SHALL keep the short flag `-l`/`--log-file` for backward
compatibility with the installed `yascheduler.sh` init script, which invokes
`$yascheduler -p "$pidfile" -l "$logfile" "$OPTIONS"`. `--config` and
`--log-level` SHALL be long-only in `daemon_sysv.py` (no short flag collision
with `-l`: `-l` is `--log-file` in `daemon_sysv.py`; the original `-l` collision
bug is fixed by each launcher parsing once and passing ready values, not by
re-parsing `sys.argv`).

`daemon_systemd.py` SHALL keep `--log-level` long-only (no `-l` alias): it has
no historical `-l` short flag and no `yascheduler.sh`-style external caller;
adding `-l` there would be gratuitous surface area.

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
- **THEN** the help text shows `usage: yascheduler [-h] [--config CONFIG] [-l {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [--log-file LOG_FILE]`

#### Scenario: daemonize accepts -l as --log-level alias
- **WHEN** `yascheduler -l DEBUG` is invoked
- **THEN** `args.log_level == "DEBUG"` (the `-l` short flag aliases `--log-level`; backward compatibility with the pre-refactor behavior)

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

### Requirement: yanodes lists nodes and their running tasks

The `yanodes` command SHALL list nodes and their currently running tasks. The command is implemented as `show_nodes()` in `yascheduler/entrypoints/cli/show_nodes.py`, a synchronous entry point that calls `asyncio.run(_show_nodes_async(argv))`. It SHALL accept an `argv: list[str] | None = None` parameter for testability. It SHALL obtain `Config` via `Config.from_config_parser`, build `CLIDeps` via `make_cli_deps(config)`, open a single UoW, read nodes via `uow.nodes.list_all()` and running tasks via `uow.tasks.list_by_status({TaskStatus.RUNNING})`, join them in memory, apply the active filters, and print the result via the selected renderer. Output row order SHALL preserve the order returned by `uow.nodes.list_all()` (no sorting). Each node SHALL produce exactly one output row (table) or one output object (JSON).

The in-memory join SHALL build `tasks_by_node_id: dict[NodeId, Task] =
{t.allocated_node_id: t for t in tasks if t.allocated_node_id is not
None}` (was `tasks_by_ip` keyed by `allocated_ip`). Each node is matched
to its running task via `tasks_by_node_id.get(node.node_id)` (was
`tasks_by_ip.get(node.ip)`). The one-RUNNING-task-per-node invariant
means a later task on the same `node_id` would overwrite, but the
invariant forbids that.

#### Scenario: yanodes entry point uses asyncio.run

- **WHEN** the `show_nodes` callable in `yascheduler/entrypoints/cli/show_nodes.py` is inspected
- **THEN** it is a synchronous `def show_nodes(argv: list[str] | None = None)` that calls `asyncio.run(_show_nodes_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

#### Scenario: yanodes joins nodes to tasks by node_id

- **WHEN** `_fetch_nodes_view` runs
- **THEN** it builds `tasks_by_node_id = {t.allocated_node_id: t for t in tasks if t.allocated_node_id is not None}` and matches each node to its task via `tasks_by_node_id.get(node.node_id)` (the join key is `node_id`, not `ip`)
### Requirement: yanodes parses flags via argparse

`show_nodes()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yanodes",
description="Show nodes and their running tasks")` exposing:
- `--json` (`store_true`): emit JSON instead of the default table. Selects the
  renderer; not a filter.
- `--enabled` (`store_true`): include only nodes where `node.enabled` is True.
- `--disabled` (`store_true`): include only nodes where `node.enabled` is False.
- `--busy` (`store_true`): include only nodes that have ≥1 RUNNING task with
  `allocated_ip == node.ip`.
- `--free` (`store_true`): include only nodes with no such RUNNING task.
- `--cloud NAME` (`str`): include only nodes where `node.cloud == NAME` (exact
  string equality).
- `--no-cloud` (`store_true`): include only nodes where `node.cloud is None`.

`--enabled` and `--disabled` SHALL be subset selectors, NOT mutually exclusive:
`--enabled --disabled` selects all nodes (= the default, no enabled-axis
filtering). `--busy` and `--free` SHALL be subset selectors, NOT mutually
exclusive: `--busy --free` selects all nodes. `--cloud` and `--no-cloud` SHALL
be in a `mutually_exclusive_group`: `--cloud NAME --no-cloud` is an argparse
error (exit `2`). All filters SHALL compose by AND: a row is emitted iff it
passes every active filter.

#### Scenario: yanodes --help shows argparse usage
- **WHEN** `yanodes --help` is invoked
- **THEN** argparse prints the standard help screen listing `--json`, `--enabled`, `--disabled`, `--busy`, `--free`, `--cloud NAME`, `--no-cloud` with their descriptions, and exits `0`

#### Scenario: yanodes with an unknown flag exits 2
- **WHEN** `yanodes --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yanodes --cloud and --no-cloud are mutually exclusive
- **WHEN** `yanodes --cloud hetzner --no-cloud` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2` (mutex group violation)

#### Scenario: yanodes --enabled --disabled equals default
- **WHEN** `yanodes --enabled --disabled` is invoked
- **THEN** no enabled-axis filter is applied and all nodes (enabled and disabled) are listed

#### Scenario: yanodes --busy --free equals default
- **WHEN** `yanodes --busy --free` is invoked
- **THEN** no busy-axis filter is applied and all nodes (busy and free) are listed

#### Scenario: yanodes filters compose by AND
- **WHEN** `yanodes --enabled --busy --cloud hetzner` is invoked
- **THEN** only nodes that are enabled AND busy AND have `cloud == "hetzner"` are listed

#### Scenario: yanodes --enabled lists only enabled nodes
- **WHEN** `yanodes --enabled` is invoked against a node set containing both enabled and disabled nodes
- **THEN** only the enabled nodes appear in the output

#### Scenario: yanodes --disabled lists only disabled nodes
- **WHEN** `yanodes --disabled` is invoked against a node set containing both enabled and disabled nodes
- **THEN** only the disabled nodes appear in the output

#### Scenario: yanodes --busy lists only nodes with a running task
- **WHEN** `yanodes --busy` is invoked against a node set where some nodes have a RUNNING task and others do not
- **THEN** only the nodes with a RUNNING task (whose `allocated_ip` matches the node's `ip`) appear in the output

#### Scenario: yanodes --free lists only nodes without a running task
- **WHEN** `yanodes --free` is invoked against a node set where some nodes have a RUNNING task and others do not
- **THEN** only the nodes with no RUNNING task appear in the output

#### Scenario: yanodes --cloud NAME exact-matches the cloud field
- **WHEN** `yanodes --cloud hetzner` is invoked against a node set containing nodes with `cloud="hetzner"`, `cloud="exoscale"`, and `cloud=None`
- **THEN** only the nodes with `cloud == "hetzner"` appear in the output (no substring/regex matching; static nodes with `cloud=None` are excluded)

#### Scenario: yanodes --no-cloud lists only static nodes
- **WHEN** `yanodes --no-cloud` is invoked against a node set containing nodes with `cloud="hetzner"` and `cloud=None`
- **THEN** only the nodes with `cloud is None` (static nodes) appear in the output

### Requirement: yanodes exit code contract

`show_nodes()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success, including an empty filter result (an empty table or `[]` is
  a valid query answer, not a failure).
- `1` on runtime failure: DB error, config parse error, or any unexpected
  exception caught at the top level. The error SHALL be printed to stderr as
  `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error (argparse default — unknown flag, bad value, mutex
  violation).

`show_nodes()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yanodes exits 0 on success
- **WHEN** `yanodes` is invoked and the query completes without exception
- **THEN** the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yanodes exits 0 on empty filter result
- **WHEN** `yanodes --cloud nonexistent` is invoked and no node matches
- **THEN** an empty table (header only, or no rows) is printed and the process exits `0`

#### Scenario: yanodes exits 1 on DB error
- **WHEN** `uow.nodes.list_all()` or `uow.tasks.list_by_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yanodes exits 1 on config error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yanodes exits 1 on unexpected exception
- **WHEN** any other unexpected exception is raised during execution
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yanodes --help exits 0
- **WHEN** `yanodes --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yanodes --bogus exits 2
- **WHEN** `yanodes --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

### Requirement: yanodes default table output format

The default output of `yanodes` (when `--json` is not given) SHALL be a
fixed-width text table rendered with stdlib string formatting only (no
external dependencies such as `rich` or `tabulate`). The table SHALL have a
header row followed by one data row per node, in the order returned by
`uow.nodes.list_all()` (which is `ORDER BY node_id`). Column widths SHALL be
computed from the data (the maximum of the header width and the widest cell
width per column) so the table is self-aligning regardless of value lengths.

The columns SHALL be: `NODE_ID`, `IP`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`,
`TASK_ID`, `LABEL`. `NODE_ID` is the first column (identity first). Display-only
transformations SHALL apply to the table cells:

| column   | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| NODE_ID  | `node.node_id`    | `str(node.node_id)` (the bare int, via `NodeId.__str__`) |
| IP       | `node.ip`         | as-is                            |
| PORT     | `node.port`       | `-` when `22`, else the int      |
| NCPUS    | `node.ncpus`      | `MAX` when `0`, else the int     |
| ENABLED  | `node.enabled`    | `yes` when True, `no` when False |
| CLOUD    | `node.cloud`      | `-` when None, else the string   |
| TASK_ID  | `task.task_id`     | `-` when free, else the int      |
| LABEL    | `task.label`       | `-` when free, else the string   |

A node is "free" when no RUNNING task has `allocated_ip == node.ip`; it is
"busy" when exactly one RUNNING task does (the one-task-per-node invariant).

#### Scenario: yanodes table has a header row
- **WHEN** `yanodes` is invoked (with or without filter flags)
- **THEN** the first line of output is the header row `NODE_ID`, `IP`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`, `LABEL` (column separators and exact spacing follow the fixed-width computation)

#### Scenario: yanodes table shows a busy node
- **WHEN** a node with `node_id=1`, `ip="10.0.0.1"`, `port=22`, `ncpus=4`, `enabled=True`, `cloud=None` has a RUNNING task with `task_id=7`, `label="my_job"`
- **THEN** one row is emitted with NODE_ID=`1`, PORT=`-`, NCPUS=`4`, ENABLED=`yes`, CLOUD=`-`, TASK_ID=`7`, LABEL=`my_job`

#### Scenario: yanodes table shows a free node
- **WHEN** a node with `node_id=2`, `ip="10.0.0.2"`, `port=2222`, `ncpus=0`, `enabled=False`, `cloud="hetzner"` has no RUNNING task
- **THEN** one row is emitted with NODE_ID=`2`, PORT=`2222`, NCPUS=`MAX`, ENABLED=`no`, CLOUD=`hetzner`, TASK_ID=`-`, LABEL=`-`

#### Scenario: yanodes table hides port 22
- **WHEN** a node has `port=22`
- **THEN** the PORT cell is `-` (the default SSH port is not shown)

#### Scenario: yanodes table shows non-default port
- **WHEN** a node has `port=2222`
- **THEN** the PORT cell is `2222`

#### Scenario: yanodes table shows MAX for zero ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the NCPUS cell is `MAX`

#### Scenario: yanodes table shows enabled as yes/no
- **WHEN** a node has `enabled=True` (resp. `False`)
- **THEN** the ENABLED cell is `yes` (resp. `no`)

#### Scenario: yanodes table shows dash for null cloud
- **WHEN** a node has `cloud=None`
- **THEN** the CLOUD cell is `-`

#### Scenario: yanodes table column widths fit the data
- **WHEN** the widest IP value is `10.0.0.255` (10 chars) and the header `IP` is 2 chars
- **THEN** the IP column is at least 10 chars wide and all IP cells are padded to that width

#### Scenario: yanodes table no external deps
- **WHEN** the implementation of `_render_nodes_table` is inspected
- **THEN** it uses only stdlib string formatting (f-string width specifiers, `str.ljust`, or equivalent) and does NOT import `rich`, `tabulate`, or any other third-party formatting library

### Requirement: yanodes --json output format

When `--json` is given, `yanodes` SHALL emit `json.dumps(list_of_objects)`
where each object represents one node with raw domain values (NO display
transformations — no `-`, no `MAX`, no `yes`/`no`). The object schema SHALL
be:

```
{"node_id": int, "ip": str, "port": int, "ncpus": int, "enabled": bool,
 "cloud": str | null, "occupied_by": {"task_id": int, "label": str} | null}
```

- `node_id`: the raw `node.node_id.value` int (serialized via `.value` because
  a `NodeId` dataclass is not JSON-serializable).
- `port`: the raw `node.port` int (22 stays 22, 2222 stays 2222).
- `ncpus`: the raw `node.ncpus` int (0 stays 0 — `MAX` is a table-only display
  token and MUST NOT appear in JSON).
- `cloud`: `null` for static nodes, else the `node.cloud` string.
- `occupied_by`: `null` when the node is free; a single object
  `{"task_id": int, "label": str}` when the node is busy (one RUNNING task).
  The single-object shape encodes the one-RUNNING-task-per-node invariant;
  promotion to an array is a separate change if the invariant ever relaxes.

One object per node, in the order returned by `uow.nodes.list_all()`.

#### Scenario: yanodes --json emits a list of objects
- **WHEN** `yanodes --json` is invoked against a non-empty node set
- **THEN** the output is valid JSON parseable as a list of objects, one per node, in `list_all()` order

#### Scenario: yanodes --json includes node_id
- **WHEN** a node with `node_id=NodeId(5)` is listed
- **THEN** the JSON object's `node_id` field is `5` (the bare int via `.value`)

#### Scenario: yanodes --json uses raw port
- **WHEN** a node has `port=22`
- **THEN** the JSON object's `port` field is `22` (NOT `null` or `"-"`)

#### Scenario: yanodes --json uses raw ncpus
- **WHEN** a node has `ncpus=0`
- **THEN** the JSON object's `ncpus` field is `0` (NOT `"MAX"` or `null`)

#### Scenario: yanodes --json busy node occupied_by is an object
- **WHEN** a node has a RUNNING task with `task_id=1`, `label="my_job"`
- **THEN** the JSON object's `occupied_by` field is `{"task_id": 1, "label": "my_job"}`

#### Scenario: yanodes --json free node occupied_by is null
- **WHEN** a node has no RUNNING task
- **THEN** the JSON object's `occupied_by` field is `null`

#### Scenario: yanodes --json static node cloud is null
- **WHEN** a node has `cloud=None`
- **THEN** the JSON object's `cloud` field is `null`

#### Scenario: yanodes --json empty result is empty list
- **WHEN** `yanodes --json` is invoked and no node matches the filters
- **THEN** the output is `[]` and the process exits `0`

### Requirement: yanodes joins nodes to running tasks in memory

`show_nodes()` SHALL perform the node-to-running-task join in memory within a
single UoW: it SHALL read `uow.nodes.list_all()` and
`uow.tasks.list_by_status({TaskStatus.RUNNING})` (two reads within one UoW),
build a `tasks_by_node_id` dict mapping `allocated_node_id` to the single
running task on that node (O(n+m) single pass over tasks), and look up each
node's task via `tasks_by_node_id.get(node.node_id)`. It SHALL NOT perform an
O(n*m) nested scan.

The join key is `node_id` (the task's `allocated_node_id` matches the node's
`node_id`), NOT `ip`. The `allocated_ip` field is removed from `Task`; the
join is by `allocated_node_id` exclusively.

#### Scenario: yanodes join is O(n+m)
- **WHEN** the implementation of `_fetch_nodes_view` (or equivalent) is inspected
- **THEN** it builds a `tasks_by_node_id` dict once and looks up each node's task by `node_id` via dict access, rather than scanning the full task list per node

#### Scenario: yanodes join key is node_id not ip
- **WHEN** the in-memory join is built
- **THEN** the dict is `tasks_by_node_id = {t.allocated_node_id: t for t in tasks if t.allocated_node_id is not None}` and each node is matched via `tasks_by_node_id.get(node.node_id)`; no `allocated_ip` or `ip`-keyed dict is used

#### Scenario: yanodes reads nodes and tasks within one UoW
- **WHEN** `show_nodes()` is invoked
- **THEN** both `uow.nodes.list_all()` and `uow.tasks.list_by_status({TaskStatus.RUNNING})` are called within the same `async with deps.uow_factory() as uow:` block

### Requirement: --json is the machine-readable CLI output convention

The `--json` flag on `yanodes` and `yastatus` SHALL establish the project
convention for machine-readable CLI output: query-oriented CLI commands SHALL
offer a `--json` flag that emits raw domain values as JSON (no display
transformations), so that scripts can consume the output without
reverse-mapping display tokens. `yanodes --json` is the first instance of the
convention; `yastatus --json` is the second instance. Future query-oriented
CLI commands MAY follow the same convention; this is not a retroactive
requirement on existing commands that lack a machine consumer.

#### Scenario: yanodes --json is the first instance of the convention
- **WHEN** `yanodes --json` is invoked
- **THEN** the output is raw-domain-value JSON (no display tokens), establishing the convention

#### Scenario: yastatus --json is the second instance of the convention
- **WHEN** `yastatus --json` is invoked
- **THEN** the output is raw-domain-value JSON (no display tokens), the second instance of the convention established by `yanodes`

#### Scenario: --json convention does not retroactively require changes to other commands
- **WHEN** `yasubmit`, `yasetnode`, or `yascheduler` is inspected
- **THEN** no `--json` flag is required on `yasubmit`, `yasetnode`, or `yascheduler`; the convention is forward-looking (yastatus is the second instance, not a retroactive mandate)

### Requirement: yasetnode parses host grammar via argparse type

The `yasetnode` command SHALL accept a single positional `host` argument whose
argparse `type=` is `_parse_node_target(s) -> NodeTarget`. For input that is
NOT purely digits, `_parse_node_target` SHALL delegate to
`_parse_host_spec(s) -> HostSpec`, where `HostSpec` is a frozen dataclass with
fields `host: str`, `username: str | None`, `port: int`, `ncpus: int | None`.
The grammar for the host-delegation branch is `[user@]host[:port][~ncpus]`:

- `user` — non-empty string without `@`. When the `user@` prefix is absent,
  `HostSpec.username` is `None` (the default is resolved later from
  `config.remote.username` by `manage_node`, NOT hardcoded by the parser).
- `host` — either an IPv4 literal or a bracketed IPv6 literal `[...]`. The
  host string MUST be non-empty.
- `port` — integer in `1..65535`. When `:port` is absent, the parser
  applies the default `22`.
- `ncpus` — non-negative integer. `~0` and absent `~ncpus` both yield
  `HostSpec.ncpus = None` (the unlimited/MAX sentinel; downstream
  `Node(ncpus=0)` encodes this in the DB).

Malformed input (multiple `@`, multiple `~`, empty segments, unbracketed
IPv6, port out of range, negative ncpus, non-integer port/ncpus) SHALL
raise `argparse.ArgumentTypeError`, which argparse surfaces as a usage error
with exit `2`.

Purely-digit input (e.g. `"5"`) routes to the node_id branch described in
the "yasetnode positional discriminates node_id from host" requirement; it
does NOT pass through `_parse_host_spec`. The `_parse_host_spec` grammar
rules and ALL error/rejection behavior tested below are stable —
the positional `type=` is wired to a wrapper
(`_parse_node_target`) that dispatches digit vs. non-digit input, so the
scenarios below call `_parse_node_target` (which delegates non-digit input
to the unchanged `_parse_host_spec`).

#### Scenario: yasetnode plain IPv4 host
- **WHEN** `_parse_node_target("10.0.0.1")` is called
- **THEN** it returns a `NodeTarget(node_id=None, host_spec=HostSpec(host="10.0.0.1", username=None, port=22, ncpus=None))`

#### Scenario: yasetnode user@host
- **WHEN** `_parse_node_target("deploy@10.0.0.1")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username="deploy", port=22, ncpus=None)`

#### Scenario: yasetnode host with explicit port
- **WHEN** `_parse_node_target("10.0.0.1:2222")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username=None, port=2222, ncpus=None)`

#### Scenario: yasetnode host with ncpus
- **WHEN** `_parse_node_target("10.0.0.1~4")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username=None, port=22, ncpus=4)`

#### Scenario: yasetnode full spec user@host:port~ncpus
- **WHEN** `_parse_node_target("deploy@10.0.0.1:2222~4")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username="deploy", port=2222, ncpus=4)`

#### Scenario: yasetnode bracketed IPv6
- **WHEN** `_parse_node_target("[::1]")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="::1", username=None, port=22, ncpus=None)`

#### Scenario: yasetnode bracketed IPv6 with port
- **WHEN** `_parse_node_target("[fe80::1]:2222")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="fe80::1", username=None, port=2222, ncpus=None)`

#### Scenario: yasetnode tilde-zero maps to None ncpus
- **WHEN** `_parse_node_target("10.0.0.1~0")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="10.0.0.1", username=None, port=22, ncpus=None)` (the `0` is normalized to `None`, the unlimited sentinel)

#### Scenario: yasetnode unbracketed IPv6 is rejected
- **WHEN** `_parse_node_target("::1")` is called
- **THEN** `_parse_host_spec` (to which `_parse_node_target` delegates the non-digit input) raises `argparse.ArgumentTypeError` (IPv6 must be bracketed to disambiguate from `:port`)

#### Scenario: yasetnode multiple at-signs rejected
- **WHEN** `_parse_node_target("a@b@c")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode multiple tildes rejected
- **WHEN** `_parse_node_target("10.0.0.1~4~5")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode empty port rejected
- **WHEN** `_parse_node_target("10.0.0.1:")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode port out of range rejected
- **WHEN** `_parse_node_target("10.0.0.1:99999")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (port must be `1..65535`)

#### Scenario: yasetnode port zero rejected
- **WHEN** `_parse_node_target("10.0.0.1:0")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError` (port `0` is not a valid SSH port)

#### Scenario: yasetnode negative ncpus rejected
- **WHEN** `_parse_node_target("10.0.0.1~-5")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode non-integer port rejected
- **WHEN** `_parse_node_target("10.0.0.1:abc")` is called
- **THEN** `_parse_host_spec` raises `argparse.ArgumentTypeError`

#### Scenario: yasetnode hostname passes (no DNS validation)
- **WHEN** `_parse_node_target("compute-node-7")` is called
- **THEN** it returns a `NodeTarget` whose `host_spec == HostSpec(host="compute-node-7", username=None, port=22, ncpus=None)` (the parser validates structure, not reachability)

#### Scenario: yasetnode missing host positional exits 2
- **WHEN** `yasetnode` is invoked with no arguments
- **THEN** argparse prints a usage error to stderr (missing the required `host` argument) and exits `2`

#### Scenario: yasetnode malformed host exits 2
- **WHEN** `yasetnode ::1` is invoked (unbracketed IPv6)
- **THEN** the positional `type=_parse_node_target` raises `argparse.ArgumentTypeError` (via `_parse_host_spec` for the non-digit input), argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode prog is yasetnode in help and errors
- **WHEN** `yasetnode --help` or any argparse error is shown
- **THEN** the program name displayed is `yasetnode` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasetnode parses flags via argparse

`manage_node()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasetnode",
description="Add or remove nodes from the yascheduler daemon")` exposing:
- `host` (positional, `type=_parse_node_target`): the node target — EITHER a
  node_id (purely-digit string) OR a host spec in the
  `[user@]host[:port][~ncpus]` grammar (see the host grammar requirement).
  `_parse_node_target` returns a `NodeTarget` (see the "yasetnode positional
  discriminates node_id from host" requirement).
- `--skip-setup` (`store_true`): on the add path, skip the remote
  `gateway.setup_node` step. Valid ONLY on the add path.
- `--remove-soft` (`store_true`): disable the node if it has running tasks,
  or remove it immediately if not. Mutually exclusive with `--remove-hard`.
- `--remove-hard` (`store_true`): mark associated RUNNING tasks DONE and
  remove the node record. Mutually exclusive with `--remove-soft`.

`--remove-soft` and `--remove-hard` SHALL be in a
`mutually_exclusive_group`: passing both exits `2`. `--skip-setup` is
incompatible with either remove flag; a body-level check after `parse_args`
SHALL call `parser.error(...)` when
`skip_setup and (remove_soft or remove_hard)`, producing exit `2`. A
node_id positional is incompatible with the add path (no remove flag); a
body-level check after `parse_args` SHALL call `parser.error(...)` when
`node_target.node_id is not None and not (remove_soft or remove_hard)`,
producing exit `2` (see the "yasetnode positional discriminates node_id
from host" requirement). The flags SHALL use `action="store_true"` and
SHALL NOT accept a value (the previous `nargs="?", type=bool, const=True`
pattern was removed because `bool("false") is True`).

The parser SHALL accept an `argv: list[str] | None = None` parameter
forwarded to `parser.parse_args(argv)`. `None` reads `sys.argv` (the
console_script convention); tests pass an explicit list.

#### Scenario: yasetnode --help shows argparse usage
- **WHEN** `yasetnode --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yasetnode"`, the `host` positional argument with its description, and the three flags, and exits `0`

#### Scenario: yasetnode with unknown flag exits 2
- **WHEN** `yasetnode 10.0.0.1 --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yasetnode --remove-soft --remove-hard exits 2
- **WHEN** `yasetnode 10.0.0.1 --remove-soft --remove-hard` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yasetnode --skip-setup --remove-hard exits 2
- **WHEN** `yasetnode 10.0.0.1 --skip-setup --remove-hard` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode --skip-setup --remove-soft exits 2
- **WHEN** `yasetnode 10.0.0.1 --skip-setup --remove-soft` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode --skip-setup does not accept a value
- **WHEN** `yasetnode 10.0.0.1 --skip-setup true` is invoked
- **THEN** argparse treats `true` as an unknown extra positional and exits `2` (the `store_true` flag takes no value)

#### Scenario: yasetnode node_id positional with add path exits 2
- **WHEN** `yasetnode 5` is invoked (a node_id positional with no `--remove-soft`/`--remove-hard`)
- **THEN** the body-level `parser.error(...)` fires (a node cannot be added by id), argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode argv parameter reads sys.argv when None
- **WHEN** `manage_node()` is invoked with `argv=None` (the console_script default)
- **THEN** `parser.parse_args(None)` is called, which reads `sys.argv[1:]`

#### Scenario: yasetnode argv parameter accepts explicit list
- **WHEN** `manage_node(["10.0.0.1", "--remove-hard"])` is invoked
- **THEN** `parser.parse_args(["10.0.0.1", "--remove-hard"])` is called, with no reading of `sys.argv`

### Requirement: yasetnode exit code contract

`manage_node()` SHALL follow the `0`/`1`/`2` exit-code contract:
- `0` on success: add completed; remove-hard completed; remove-soft
  completed (whether the node was disabled or removed).
- `1` on runtime failure: host already in DB (on the add path); host NOT in
  DB (on either remove path); node_id NOT in DB (on a remove-by-id path);
  SSH connection or setup failure; DB error; config parse error; or any
  unexpected exception caught at the top level. The error SHALL be printed
  to stderr as `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error (argparse default — missing host positional,
  malformed host grammar via `type=_parse_node_target` (which delegates to
  `_parse_host_spec` for non-digit input), port out of range, negative
  ncpus, `--remove-soft --remove-hard`, `--skip-setup --remove-*`,
  node_id-positional × add-path combination, unknown flag).

`manage_node()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body.

#### Scenario: yasetnode add exits 0 on success
- **WHEN** `yasetnode 10.0.0.1` is invoked and the add completes without exception
- **THEN** the success messages are printed to stdout and the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yasetnode add exits 1 when host already in DB
- **WHEN** `yasetnode 10.0.0.1` is invoked and `uow.nodes.get("10.0.0.1")` returns an existing node
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode remove exits 1 when host NOT in DB
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked and `uow.nodes.get("10.0.0.1")` returns `None`
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode remove-by-id exits 1 when node_id NOT in DB
- **WHEN** `yasetnode 999 --remove-hard` is invoked and `uow.nodes.get_by_id(NodeId(999))` returns `None`
- **THEN** `Error: ...` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasetnode exits 1 on SSH connect failure
- **WHEN** `yasetnode 10.0.0.1` is invoked and `gateway.connect(...)` raises an SSH connection error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode exits 1 on DB error
- **WHEN** `uow.nodes.insert(...)`, `uow.nodes.remove(...)`, `uow.nodes.disable(...)`, `uow.tasks.update_status(...)`, or `uow.tasks.list_ids_by_ip_and_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode exits 1 on config parse error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yasetnode --help exits 0
- **WHEN** `yasetnode --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yasetnode remove-hard exits 0 on success
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against an existing node and the hard-remove completes without exception
- **THEN** the per-task and removal success messages are printed to stdout and the process exits `0`

#### Scenario: yasetnode remove-soft exits 0 on success
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against an existing node and the soft-remove completes without exception (whether the node had running tasks or not)
- **THEN** the success messages are printed to stdout and the process exits `0`

### Requirement: yasetnode output channels and verbatim success messages

On success, `manage_node()` SHALL print the following messages verbatim to
**stdout**, and SHALL emit them **after** `await uow.commit()` succeeds (so
the observable output matches the committed DB state):

| path                        | message (verbatim)                                                      |
| --------------------------- | ----------------------------------------------------------------------- |
| add, before setup           | `Setup host...`                                                          |
| add, after commit           | `Added host to yascheduler: {host}:{port}`                                |
| remove-hard, per task       | `An associated task {task_id} at {host} is now marked done!`              |
| remove-hard, after commit   | `Removed host from yascheduler: {host}`                                   |
| remove-soft, has tasks      | `A task associated, prevent from assigning the new tasks`                 |
|                              | `Prevented from assigning the new tasks: {host}`                          |
| remove-soft, no tasks       | `No tasks associated, remove node immediately`                             |
| remove-soft, no tasks, after commit | `Removed host from yascheduler: {host}`                            |

`{host}` is the parsed `HostSpec.host` (the cleaned host string, not the
raw input) when the positional is a host spec. When the positional is a
node_id (see the "yasetnode positional discriminates node_id from host"
requirement), `{host}` is the resolved `node.ip` from `get_by_id` (no
`HostSpec` is parsed on that path). `{port}` is the resolved `port` int
(host-spec path only; the node_id path has no port placeholder in the
messages — the remove messages use `{host}` alone). `{task_id}` is each
RUNNING task id marked DONE by the hard-remove.

On failure, `manage_node()` SHALL print `Error: <message>` to **stderr**
via `raise` + top-level `except Exception as e: print(f"Error: {e}",
file=sys.stderr); sys.exit(1)`. Failure messages SHALL NOT appear on
stdout.

#### Scenario: yasetnode add success prints verbatim messages to stdout after commit
- **WHEN** `yasetnode 10.0.0.1` succeeds (without `--skip-setup`)
- **THEN** stdout contains `Setup host...` (a progress indicator printed before `setup_node`, not a success confirmation) and `Added host to yascheduler: 10.0.0.1:22` (the confirmation, emitted after `uow.commit()` returns), in that order

#### Scenario: yasetnode add with --skip-setup omits Setup host message
- **WHEN** `yasetnode 10.0.0.1 --skip-setup` succeeds
- **THEN** stdout does NOT contain `Setup host...` (the setup step was skipped) and contains `Added host to yascheduler: 10.0.0.1:22`

#### Scenario: yasetnode remove-hard prints per-task messages after commit
- **WHEN** `yasetnode 10.0.0.1 --remove-hard` succeeds against a node with RUNNING task ids `[1, 2]`
- **THEN** stdout contains `An associated task 1 at 10.0.0.1 is now marked done!` and `An associated task 2 at 10.0.0.1 is now marked done!` and `Removed host from yascheduler: 10.0.0.1`, all emitted after `uow.commit()` returns

#### Scenario: yasetnode remove-soft with tasks prints disable messages
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` succeeds against a node with at least one RUNNING task
- **THEN** stdout contains `A task associated, prevent from assigning the new tasks` and `Prevented from assigning the new tasks: 10.0.0.1`

#### Scenario: yasetnode remove-soft without tasks prints remove messages
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` succeeds against a node with no RUNNING tasks
- **THEN** stdout contains `No tasks associated, remove node immediately` and `Removed host from yascheduler: 10.0.0.1`

#### Scenario: yasetnode failure prints Error to stderr not stdout
- **WHEN** `yasetnode 10.0.0.1` fails (host already in DB, SSH failure, DB error, or any exception)
- **THEN** stderr contains `Error: ...`, stdout is empty of success messages, and the process exits `1`

#### Scenario: yasetnode remove-by-id success messages use resolved node.ip
- **WHEN** `yasetnode 5 --remove-hard` succeeds against a node with `node_id=5`, `ip="10.0.0.5"`
- **THEN** stdout's success messages substitute `{host}` with `10.0.0.5` (the resolved `node.ip`), since no `HostSpec` is parsed on the node_id path

### Requirement: yasetnode positional discriminates node_id from host

The `yasetnode` positional argument SHALL accept EITHER a node_id (a purely
digit string) OR a host spec (the `[user@]host[:port][~ncpus]` grammar). The
positional `type=_parse_node_target(s) -> NodeTarget` discriminates:

- if `s.isdigit()` is True, the result is
  `NodeTarget(node_id=NodeId(int(s)), host_spec=None)`;
- otherwise the result is
  `NodeTarget(node_id=None, host_spec=_parse_host_spec(s))`.

`NodeTarget` is a frozen dataclass with `node_id: NodeId | None` and
`host_spec: HostSpec | None`; exactly one of the two is set. The
discriminator `s.isdigit()` is safe because IPv4 literals contain `.`, IPv6
must be bracketed (`[...]`), and FQDNs contain `.`/letters — none are
pure-digit.

A node cannot be added by id (adding requires a real host). After
`parse_args`, if `node_target.node_id is not None` AND neither `--remove-soft`
nor `--remove-hard` is set (i.e. the add path), `manage_node` SHALL call
`parser.error("a node cannot be added by id; provide a host like user@host[:port][~ncpus]")`
(exit `2` — an argument-combination error, consistent with the existing
`--skip-setup × remove` `parser.error`).

On the remove path, the validation UoW resolves the `Node` early —
`uow.nodes.get_by_id(node_target.node_id) -> Node | None` on the node_id path,
`uow.nodes.get(spec.host) -> Node | None` on the host_spec path. If `None`, the
existing "NOT in DB" body validation raises (exit `1`). If found, the `Node`
is passed to the remove helpers (`_remove_node_soft`, `_remove_node_hard`),
which use `node.node_id` for the `nodes.disable(node.node_id)` /
`nodes.remove(node.node_id)` mutators and `node.ip` for
`tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)` (Surface C —
ip-keyed, unchanged) and for user-facing stdout messages.

#### Scenario: yasetnode pure-digit positional is a node_id
- **WHEN** `_parse_node_target("5")` is called
- **THEN** it returns `NodeTarget(node_id=NodeId(5), host_spec=None)`

#### Scenario: yasetnode node_id branch does not call _parse_host_spec
- **WHEN** `_parse_node_target("5")` is called
- **THEN** `_parse_host_spec` is NOT invoked (the digit short-circuit returns a `NodeTarget` with `node_id` set directly)

#### Scenario: yasetnode add-by-id is rejected
- **WHEN** `yasetnode 5` is invoked (no `--remove-soft`/`--remove-hard`)
- **THEN** argparse surfaces `parser.error(...)` with exit `2` and a message stating a node cannot be added by id

#### Scenario: yasetnode remove-by-id soft resolves Node via get_by_id
- **WHEN** `yasetnode 5 --remove-soft` is invoked and a node with node_id=5 exists with no RUNNING tasks
- **THEN** `uow.nodes.get_by_id(NodeId(5))` resolves the `Node`, the `Node` is passed to `_remove_node_soft`, and `uow.nodes.remove(node.node_id)` removes it (node_id-keyed mutator)

#### Scenario: yasetnode remove-by-host soft resolves Node via get
- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked and a node with ip=10.0.0.1 exists with no RUNNING tasks
- **THEN** `uow.nodes.get("10.0.0.1")` resolves the `Node`, the `Node` is passed to `_remove_node_soft`, and `uow.nodes.remove(node.node_id)` removes it (node_id-keyed mutator)

#### Scenario: yasetnode remove-by-id unknown id is a body error
- **WHEN** `yasetnode 999 --remove-hard` is invoked and no node with node_id=999 exists
- **THEN** `get_by_id` returns `None` and the body raises a "not in DB" error with exit `1`

#### Scenario: yasetnode node_id zero is rejected
- **WHEN** `_parse_node_target("0")` is called
- **THEN** `NodeId(0)` raises `ValueError` in `__post_init__` (node_id must be > 0); the error surfaces as a runtime error (exit `1`) or is rejected at parse time

#### Scenario: yasetnode negative-looking token falls through to grammar
- **WHEN** `_parse_node_target("-5")` is called
- **THEN** `"-5".isdigit()` is `False`, so it falls through to `_parse_host_spec`, which rejects it as a malformed host (no dots/brackets)

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL construct a single
`SSHMachineRepository` and a single `SSHMachineOperations` (bound to that
repository) at the top of the function (before opening any UoW) and pass
them as parameters to the add helper. The add helper `_add_node(deps,
repository, operations, spec, config, skip_setup)` SHALL adopt the
V1-pattern (same as cloud allocation): insert the row with `enabled=False`
BEFORE connecting, so the `Node` (carrying `node_id`) is in hand for
`connect(node, ...)`. The flow SHALL be:

1. Open a UoW, call `uow.nodes.insert(NewNode(ip=spec.host, port=spec.port,
   username=username, ncpus=(spec.ncpus if spec.ncpus is not None else 0),
   enabled=False)) -> Node(T)`, commit, close the UoW. The row is
   `enabled=False` so orchestrator's `list_enabled()` skips it.
2. Connect via `repository.connect(node=T, username=username,
   client_keys=..., engines_dir=..., port=spec.port)`, registering the
   session under `T.node_id`.
3. If not `skip_setup`: call `operations.setup_node(session, config.engines)`.
4. Open a second UoW, call `uow.nodes.update(Node(node_id=T.node_id,
   ip=spec.host, port=spec.port, username=username, ncpus=…,
   enabled=True, …))`, commit, close the UoW. This flips the row to
   `enabled=TRUE`.
5. Print `Added host to yascheduler: {spec.host}:{spec.port}`.
6. In a `finally` block: `await repository.disconnect(T.node_id)`.

The `disconnect` SHALL run on both the success path and any failure path
(SSH failure, setup failure, DB failure), so the SSH connection is released
rather than leaking until timeout.

The repository and operations SHALL be instantiated once per invocation;
the helper SHALL NOT construct its own repository/operations. This makes
the add helper unit-testable via direct mock injection.

On connect-failure (step 2 raises `MachineConnectionError` or any
`Exception`): the `_add_node` helper SHALL best-effort remove the tmp row
via a UoW (`uow.nodes.remove(T.node_id)` + commit, logged not raised),
then re-raise. The orchestrator never saw the row (it was
`enabled=FALSE`), so no orchestrator-side cleanup is needed. The
operator-visible behavior is unchanged: success → "Added host", failure →
error + no row remains.

#### Scenario: yasetnode constructs repository+operations once and passes to add helper

- **WHEN** `yasetnode 10.0.0.1` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` and one `SSHMachineOperations(...)` are constructed (at the top of `manage_node`), and those instances are passed as parameters to the add helper

#### Scenario: yasetnode add-path inserts enabled=False before connect

- **WHEN** `_add_node` is called with a valid host spec
- **THEN** it inserts `NewNode(ip=spec.host, enabled=False, …) -> Node(T)` FIRST (before any SSH work), so `T.node_id` is in hand for `connect(node=T, ...)`

#### Scenario: yasetnode add-path connects via Node and disconnects by node_id

- **WHEN** `_add_node` reaches the connect step
- **THEN** it calls `repository.connect(node=T, client_keys=..., ...)` with no `username`/`port` arguments (the login user and port are `T.username` / `T.port`), registering the session under `T.node_id`; the `finally` block calls `repository.disconnect(T.node_id)`

#### Scenario: yasetnode add-path flips enabled to TRUE after setup

- **WHEN** `_add_node` completes the optional `setup_node` step
- **THEN** it opens a second UoW, calls `uow.nodes.update(Node(node_id=T.node_id, enabled=True, …))`, commits, and prints `Added host to yascheduler: {spec.host}:{spec.port}`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, ...)` raises `MachineConnectionError` (or any `Exception`) during `_add_node`
- **THEN** the helper best-effort removes the tmp row via `uow.nodes.remove(T.node_id)` + commit (logged not raised), then re-raises; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)

#### Scenario: yasetnode add-path row is invisible to orchestrator during setup

- **WHEN** `_add_node` has inserted the row (enabled=False) and is mid-connect or mid-setup
- **THEN** the orchestrator's `_connect_machine_producer` filters by `list_enabled()`, which excludes the row; no concurrent connect attempt occurs

#### Scenario: yasetnode disconnects repository on add success

- **WHEN** `yasetnode 10.0.0.1` succeeds on the add path
- **THEN** `repository.disconnect(T.node_id)` is called after the `update` commit (inside `_add_node`'s `try/finally`, disconnect runs)

#### Scenario: yasetnode disconnects repository when setup_node raises

- **WHEN** `operations.setup_node(session, ...)` raises an exception after `repository.connect(node=T, ...)` succeeded
- **THEN** `repository.disconnect(T.node_id)` is still called (the `finally` block runs), the tmp row is best-effort removed, and the exception propagates to the top-level handler which prints `Error: ...` to stderr and exits `1`
### Requirement: yasetnode dispatches add and remove paths

After argparse succeeds and the `HostSpec` is parsed, `manage_node()` SHALL
open a short, read-only validation UoW via
`async with deps.uow_factory() as uow:`, resolve the target `Node` (via
`get_by_id(target.node_id)` on the node_id path, or via `get_by_id` after a
host-spec resolution on the host_spec path — the ip-keyed `get(spec.host)` is
REMOVED), and close it (without commit — nothing was mutated). It SHALL then
dispatch to exactly one helper, each of which opens its OWN UoW via
`deps.uow_factory()` to perform its mutations, commit, and print:

- If `already_there` and no remove flag: raise `ValueError` → top-level
  handler prints `Error: ...` to stderr, exits `1`. (Adding an existing
  node is an operator error; disabled nodes are re-enabled via the
  remove + add cycle, not by re-adding.)
- If NOT `already_there` and a remove flag is set: raise `ValueError` →
  top-level handler prints `Error: ...` to stderr, exits `1`.
- If `--remove-hard`: call `_remove_node_hard(deps, node: Node)` — inside its
  own UoW, list RUNNING task ids for `node.ip`, mark each DONE, remove the node
  via `uow.nodes.remove(node.node_id)`, commit.
- If `--remove-soft`: call `_remove_node_soft(deps, node: Node)` — inside its
  own UoW, if RUNNING tasks exist, disable the node via
  `uow.nodes.disable(node.node_id)`; else remove the node via
  `uow.nodes.remove(node.node_id)`; commit.
- Otherwise (add): resolve `username = spec.username or
  config.remote.username`, call `_add_node(deps, gateway, operations, spec,
  config, skip_setup)` (see the "yasetnode gateway lifecycle and resource
  safety" requirement for the V1-pattern add sequence).

A TOCTOU window exists between closing the validation UoW and opening the
dispatch helper's UoW; for a single-operator CLI this is accepted (see design
D18). Failure modes are benign and non-corrupting: add-on-already-present →
no-op / helper re-check → exit 1; remove-on-just-removed →
no-op / not-found → exit 1.

The remove helpers SHALL accept `node: Node` (not `ip: str`); the validation
UoW already fetched the `Node`, and passing it down avoids a re-fetch.
`tasks.list_ids_by_ip_and_status(node.ip, RUNNING)` stays ip-keyed
(`ip` is the cloud host identifier for the TaskRepository lookup — out of
scope for this change). User-facing stdout messages use `node.ip` (operators
read ip, not node_id).

The `NewNode` record constructed on the add path SHALL use
`ip=spec.host`, `port=spec.port`, `username=<resolved>`,
`ncpus=(spec.ncpus if spec.ncpus is not None else 0)`, `enabled=False` (the
row is inserted `enabled=FALSE` before connect; the V1-pattern add sequence
in "yasetnode gateway lifecycle and resource safety" flips it to `enabled=TRUE`
via `update` after setup).

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW

- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineRepository` and an `SSHMachineOperations` (bound to that repository) are constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened to resolve the target `Node` (by `get_by_id` on the node_id path, or via host-spec resolution on the host_spec path — `get(spec.host)` is removed), and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the repository and operations are passed to the add helper.

#### Scenario: yasetnode remove helpers take Node not ip

- **WHEN** `_remove_node_hard` or `_remove_node_soft` is inspected
- **THEN** the signature is `(deps, node: Node)` (not `(deps, ip: str)`); the validation UoW resolved the `Node` and passed it down

#### Scenario: yasetnode remove-hard marks running tasks DONE then removes node by node_id

- **WHEN** `yasetnode 10.0.0.1 --remove-hard` is invoked against a node with `node_id=7`, ip=10.0.0.1, and RUNNING task ids `[1, 2]`
- **THEN** inside `_remove_node_hard`'s own UoW, `uow.tasks.update_status(1, TaskStatus.DONE)` and `uow.tasks.update_status(2, TaskStatus.DONE)` are called, then `uow.nodes.remove(NodeId(7))` is called (node_id-keyed), then `uow.commit()` is called

#### Scenario: yasetnode remove-soft with tasks disables node by node_id

- **WHEN** `yasetnode 10.0.0.1 --remove-soft` is invoked against a node with `node_id=7`, ip=10.0.0.1, and at least one RUNNING task
- **THEN** inside `_remove_node_soft`'s own UoW, `uow.nodes.disable(NodeId(7))` is called (node_id-keyed), `uow.nodes.remove(...)` is NOT called, and `uow.commit()` is called
### Requirement: yasetnode module path and GRACE-lite markup

The `yasetnode` command SHALL be implemented as `manage_node()` in
`yascheduler/entrypoints/cli/manage_node.py`, a synchronous entry point
that calls `asyncio.run(_manage_node_async(argv))` (NOT `@to_sync`-decorated;
CLI entry points have no async caller). The module SHALL carry fresh
GRACE-lite markup (`MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`,
function contracts, and block anchors) versioned `1.0.0`. The stale
`# FIXME: split adapter and application layer` comment from the old
`infra/cli/manage_node.py` SHALL NOT be carried to the new file. The logic
SHALL be split into private pure functions: `_parse_host_spec(s)`,
`_parse_node_args(argv)`, `_remove_node_hard(deps, node: Node)`,
`_remove_node_soft(deps, node: Node)`, `_add_node(deps, repository, operations,
spec, config, skip_setup)`, and the `HostSpec` frozen dataclass. Each
mutate helper opens its own UoW via `deps.uow_factory()` (see the dispatch
requirement); the validation read uses a separate read-only UoW closed
before dispatch. No use case SHALL be extracted into `application/` — YAGNI
(no second consumer; the daemon-side node lifecycle is owned by the
orchestrator).

#### Scenario: yasetnode entry point uses asyncio.run
- **WHEN** the `manage_node` callable in `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it is a synchronous `def manage_node(argv: list[str] | None = None)` that calls `asyncio.run(_manage_node_async(argv))`; it is NOT `@to_sync`-decorated and has no `__wrapped__` attribute

#### Scenario: yasetnode module has fresh GRACE-lite markup
- **WHEN** `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** it contains `START_MODULE_CONTRACT`/`END_MODULE_CONTRACT`, `START_MODULE_MAP`/`END_MODULE_MAP`, `START_CHANGE_SUMMARY`/`END_CHANGE_SUMMARY`, function-level `START_CONTRACT:`/`END_CONTRACT:` blocks, and `START_BLOCK_`/`END_BLOCK_` anchors, versioned `1.0.0`

#### Scenario: yasetnode module drops stale FIXME
- **WHEN** `yascheduler/entrypoints/cli/manage_node.py` is inspected
- **THEN** the comment `# FIXME: split adapter and application layer` does NOT appear (the framing was stale at the new home and the function-level split resolves the separation)

#### Scenario: yasetnode does not extract an application use case
- **WHEN** the implementation is inspected
- **THEN** no `application/manage_node.py` or equivalent use-case module is created; all orchestration lives in the CLI module's private helpers

### Requirement: yastatus queries task status

The `yastatus` command SHALL query and display task status, optionally with
remote machine output (verbose mode) and convergence info, resolving nodes via
`get_by_ids` (batch lookup by `allocated_node_id`). The command is implemented
as `check_status()` in `yascheduler/entrypoints/cli/check_status.py`, a
synchronous entry point that calls `asyncio.run(_check_status_async(argv))`
and accepts `argv: list[str] | None = None` for testability.

In view/json mode, the command SHALL open a single query-phase UoW, read
tasks via `_query_tasks(uow, args)`, and read nodes via
`uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if
t.allocated_node_id])` (a single batch round-trip), building
`nodes_by_id: dict[NodeId, Node]`. The UoW is closed before any SSH work
in the view path.

The renderers SHALL look up nodes via `nodes_by_id.get(task.allocated_node_id)`.
The `_render_json` output object SHALL emit a nested `node` object (see the
"yastatus --json output format" requirement) built from the resolved `Node`,
and SHALL NOT emit flat `allocated_ip`/`port`/`cloud` fields (those are
removed in favor of the nested `node`). The `_render_info` renderer SHALL emit
`node_id={task.allocated_node_id}` (was `ip={task.allocated_ip}`) as the
placement field, because the `Task` entity no longer carries `allocated_ip`.

The `_display_remote_output` helper SHALL resolve the node via
`nodes_by_id.get(task.allocated_node_id)`, build `_ConnParams` from the
node (via `_resolve_conn_params(node, config)`), and connect via
`SSHMachineRepository().connect(node, ...)` (passing the `Node` so the
session registers under `node.node_id`). The finally block SHALL call
`repository.disconnect(session.machine.node_id)`. The verbose renderer
(`_render_view`) SHALL use `node.ip` (the resolved `Node`'s transport
address) in its display line, NOT `task.allocated_ip` (which is removed).

#### Scenario: yastatus queries tasks via CLIDeps

- **WHEN** yastatus is invoked (default mode, `-i`, `--json`, or `-v`)
- **THEN** make_cli_deps() is called, tasks are read via `uow.tasks.list_by_status({RUNNING, TO_DO})` (default) or `uow.tasks.list_by_jobs(job_ids)` (with `-j`), and the selected renderer prints the result

#### Scenario: yastatus view/json resolves nodes via get_by_ids

- **WHEN** yastatus is invoked with `--view` or `--json` and tasks have `allocated_node_id` set
- **THEN** the query-phase UoW calls `uow.nodes.get_by_ids([t.allocated_node_id for t in tasks if t.allocated_node_id])` (a single batch round-trip); the resulting `nodes_by_id: dict[NodeId, Node]` is closed over for the render phase

#### Scenario: yastatus does not read allocated_ip

- **WHEN** the `check_status.py` implementation is inspected
- **THEN** no code reads `task.allocated_ip` (the field is removed from `Task`); node transport address is obtained from the resolved `Node.ip` via `nodes_by_id`

#### Scenario: yastatus _display_remote_output connects via Node

- **WHEN** `_display_remote_output` is called for a running task
- **THEN** it resolves the node via `nodes_by_id.get(task.allocated_node_id)`, builds `_ConnParams` from the node, connects via `SSHMachineRepository().connect(node, ...)` (the session registers under `node.node_id`), and disconnects via `repository.disconnect(session.machine.node_id)` in the finally block
### Requirement: yastatus default output format (AiiDA compatibility)

The default renderer of `yastatus` SHALL emit exactly one line per task in
the form `<task_id><whitespace><STATUS_NAME>`, used when none of
`-v`/`-i`/`--json` is given. `<task_id>` is the integer task id and
`<STATUS_NAME>` is the `TaskStatus` enum member name (`TO_DO`, `RUNNING`,
or `DONE`). This format SHALL be preserved exactly because the AiiDA
scheduler plugin (`entrypoints/aiida_plugin.py:_parse_joblist_output`) parses
the output via `for job_id, status in job.split()` (requiring exactly 2
whitespace-separated elements per line) and maps `status` through
`_MAP_STATUS_YASCHEDULER` (whose keys are `{TO_DO, RUNNING, DONE}`).

`yastatus` SHALL NOT add a header line, a footer line, a summary count, or
any other decoration to the default output. The default renderer
(`_render_default`) SHALL be `print(f"{task.task_id}   {task.status.name}")`
per task (moved as-is from the previous `_print_status_default`). The exact
whitespace run between the two fields is not contractual (the plugin's
`.split()` tolerates any run), but the 2-element shape and the status-name
set are.

The `-v`, `-i`, `-o`, and `--json` modes are NOT used by the AiiDA plugin
(it only invokes `yastatus` or `yastatus --jobs ...`); their output is free
to change. `--json` is therefore safe to add (opt-in; AiiDA never passes it).

#### Scenario: yastatus default output is two-column
- **WHEN** `yastatus` is invoked against tasks with ids 1 (RUNNING), 2 (TO_DO), 3 (DONE)
- **THEN** the default invocation (no `-j`) excludes DONE and prints exactly `1   RUNNING` and `2   TO_DO` (one line per RUNNING/TO_DO task, in the order returned by `list_by_status`)

#### Scenario: yastatus default output has no header or decoration
- **WHEN** `yastatus` is invoked
- **THEN** the first line of stdout is a task row, not a header; no summary, count, or banner appears

#### Scenario: yastatus -j includes DONE tasks in default format
- **WHEN** `yastatus -j 3` is invoked and task 3 has status DONE
- **THEN** the default renderer prints `3   DONE` (DONE is a valid AiiDA state and is included because `-j` queries by id, not by status)

#### Scenario: AiiDA plugin parses yastatus default output
- **WHEN** the default renderer's stdout is parsed with the AiiDA plugin's exact logic `[job.split() for job in stdout.split("\n") if job]` and the resulting pairs are unpacked `for job_id, status in pairs`
- **THEN** every line yields exactly 2 elements and every `status` is a key of `_MAP_STATUS_YASCHEDULER` (`TO_DO`, `RUNNING`, or `DONE`) — no `ValueError`, no `KeyError`

#### Scenario: AiiDA plugin is unchanged
- **WHEN** `entrypoints/aiida_plugin.py` is inspected
- **THEN** `_get_joblist_command` still returns `yastatus` or `yastatus --jobs <ids>` and `_parse_joblist_output` still does `for job_id, status in job.split()` with `_MAP_STATUS_YASCHEDULER` (the AiiDA contract is not touched)

### Requirement: yastatus parses flags via argparse

`check_status()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yastatus",
description="Show status of tasks")`. The flag matrix SHALL be:

- `-j/--jobs` (`nargs="*"`, `default=None`): orthogonal filter; composes with
  any renderer. With no `-j`, the default query `list_by_status({RUNNING,
  TO_DO})` is used; with `-j ID...`, `list_by_jobs(job_ids=ID...)` is used.
- A `mutually_exclusive_group` containing exactly:
  - `-v/--view` (`action="store_true"`): verbose renderer (tail remote OUTPUT,
    optional convergence).
  - `-i/--info` (`action="store_true"`): tab-separated one-line-per-task
    renderer.
  - `--json` (`action="store_true"`): JSON renderer with raw domain values.
  At most one renderer is selected; none means the default AiiDA-compatible
  renderer (`_render_default`).
- `-o/--convergence` (`action="store_true"`): NOT in the mutex group (it
  modifies `-v`, so `-o -v` must remain valid). A body-check after
  `parse_args` SHALL reject `-o` without `-v` via
  `parser.error("--convergence requires --view")` (exit 2).

`--help` shows the standard argparse help screen (argparse default). The
parser SHALL use `action="store_true"` for all boolean flags (NOT the
previous non-idiomatic `nargs="?", type=bool, const=True` shape).

#### Scenario: yastatus --help shows argparse usage
- **WHEN** `yastatus --help` is invoked
- **THEN** argparse prints the standard help screen showing `prog="yastatus"` and the flags `-j/--jobs`, `-v/--view`, `-i/--info`, `-o/--convergence`, `--json` with their descriptions, and exits `0`

#### Scenario: yastatus -v -i mutually exclusive
- **WHEN** `yastatus -v -i` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus --json -v mutually exclusive
- **WHEN** `yastatus --json -v` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus --json -i mutually exclusive
- **WHEN** `yastatus --json -i` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus -o without -v exits 2
- **WHEN** `yastatus -o` is invoked (without `-v`)
- **THEN** the body-check calls `parser.error("--convergence requires --view")`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yastatus -o -v is valid
- **WHEN** `yastatus -v -o` is invoked
- **THEN** argparse accepts the combination (both flags set), the body-check passes (because `args.view` is True), and the verbose renderer runs with convergence fetching enabled

#### Scenario: yastatus with an unknown flag exits 2
- **WHEN** `yastatus --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yastatus -j composes with any renderer
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes orthogonally with any renderer in the mutex group)

#### Scenario: yastatus prog is yastatus in help and errors
- **WHEN** `yastatus --help` or any argparse error is shown
- **THEN** the program name displayed is `yastatus` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yastatus exit code contract

`check_status()` SHALL follow the `0`/`1`/`2` exit-code contract:

- `0` on success: the function returns normally after rendering (default,
  `-i`, `--json`, or `-v`); the process exits `0`.
- `1` on runtime failure: DB error, config parse error, SSH connection
  failure, SFTP failure, convergence-parse failure, or any unexpected
  exception caught at the top level. The error SHALL be printed to stderr as
  `Error: <error>` and the process SHALL exit `1`.
- `2` on argparse error: argparse default (unknown flag, mutex group
  violation) or `parser.error("--convergence requires --view")`.

`check_status()` SHALL NOT call `sys.exit(0)` explicitly on success — the
function returns normally and the process exits `0`. Only the failure path
calls `sys.exit(1)`. argparse's `--help`/error path calls `sys.exit(0)`/
`sys.exit(2)` internally before reaching the function body. `asyncio.run`
propagates `SystemExit` correctly (it is a `BaseException`; `asyncio.run`
does not wrap it).

#### Scenario: yastatus exits 0 on success
- **WHEN** `yastatus` is invoked and the query + render complete without exception
- **THEN** the process exits `0` (the function returns normally; no explicit `sys.exit(0)`)

#### Scenario: yastatus exits 1 on DB error
- **WHEN** `uow.tasks.list_by_status(...)` raises a database error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus exits 1 on config error
- **WHEN** `Config.from_config_parser(CONFIG_FILE)` raises a config parse error
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus exits 1 on SSH connection failure
- **WHEN** `yastatus -v` is invoked and `gateway.connect(...)` raises `MachineConnectionError`
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus exits 1 on unexpected exception
- **WHEN** any other unexpected exception is raised during execution
- **THEN** `Error: <error>` is printed to stderr and the process exits `1`

#### Scenario: yastatus --help exits 0
- **WHEN** `yastatus --help` is invoked
- **THEN** argparse prints the help screen and exits `0`

#### Scenario: yastatus --bogus exits 2
- **WHEN** `yastatus --bogus` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2`

#### Scenario: yastatus -o without -v exits 2
- **WHEN** `yastatus -o` is invoked (without `-v`)
- **THEN** the body-check calls `parser.error(...)` and the process exits `2`

### Requirement: yastatus --json output format

When `--json` is given, `yastatus` SHALL emit
`json.dumps(list_of_objects)` where each object represents one task with raw
domain values (NO display transformations — no `MAX`, no `-`, no banner).
The object schema SHALL be exactly these fields:

```
{"task_id": int, "status": str, "label": str, "engine": str,
 "local_folder": str | null, "remote_folder": str | null,
 "created_at": str, "updated_at": str,
 "node": {"ip": str, "port": int, "username": str, "cloud": str | null} | null}
```

- `task_id`: the raw `task.task_id.value` int.
- `status`: the `task.status.name` string (`"TO_DO"`, `"RUNNING"`, or
  `"DONE"`) — NOT an int, NOT a display token. Unchanged from the prior
  format.
- `label`: the raw `task.label` string. Unchanged (the DB column is `title`,
  but the domain field and JSON key remain `label`).
- `engine`: the raw `task.context.engine` string (always present —
  `TaskContext.engine` is a required field). Unchanged.
- `local_folder`: the raw `task.context.local_folder` string, or `null`.
  Unchanged.
- `remote_folder`: the raw `task.context.remote_folder` string, or `null`.
  Unchanged.
- `created_at`: the `task.created_at` datetime serialized as an ISO-8601
  string (via `.isoformat()`). New field (the DB column is added by migration
  007).
- `updated_at`: the `task.updated_at` datetime serialized as an ISO-8601
  string. New field.
- `node`: an object built from `nodes_by_id.get(task.allocated_node_id)`,
  or `null` when the task has no allocated node (`allocated_node_id` is
  `None`, e.g. a `TO_DO` task or a task whose node was deleted). When
  non-null, the object has exactly:
  - `ip`: the raw `node.ip` string (was the flat `allocated_ip` field; now
    sourced from the resolved `Node`).
  - `port`: the raw `node.port` int (was the flat `port` field; now sourced
    from the resolved `Node`).
  - `username`: the raw `node.username` string. New nested field (was not
    in the flat 9-field shape).
  - `cloud`: the raw `node.cloud` string, or `null` for static nodes (was
    the flat `cloud` field; now sourced from the resolved `Node`).

The flat `allocated_ip`, `port`, and `cloud` fields are REMOVED and
replaced by the nested `node` object. This is a **BREAKING** change to the
`yastatus --json` wire format.

One object per task, in the order returned by the query
(`list_by_status` or `list_by_jobs`). `--json` SHALL be in the
`mutually_exclusive_group` with `-v` and `-i`; convergence (`-o`) is NOT
part of `--json` (mixing machine-readable JSON with ephemeral scientific
output is excluded by design).

#### Scenario: yastatus --json emits a list of objects
- **WHEN** `yastatus --json` is invoked against a non-empty task set
- **THEN** the output is valid JSON parseable as a list of objects, one per task, in query order

#### Scenario: yastatus --json uses raw status name
- **WHEN** a task has status `RUNNING`
- **THEN** the JSON object's `status` field is the string `"RUNNING"` (NOT `1`, NOT `"running"`) — unchanged

#### Scenario: yastatus --json uses nested node object
- **WHEN** a task is allocated to a node with `ip="10.0.0.1"`, `port=22`, `username="root"`, `cloud="hetzner"`
- **THEN** the JSON object's `node` field is `{"ip": "10.0.0.1", "port": 22, "username": "root", "cloud": "hetzner"}` (a nested object, NOT the flat `allocated_ip`/`port`/`cloud` fields)

#### Scenario: yastatus --json TO_DO task has null node
- **WHEN** a `TO_DO` task (no `allocated_node_id`) is rendered via `--json`
- **THEN** the JSON object's `node` field is `null` (the task has not been placed on a node yet); the flat `allocated_ip`, `port`, and `cloud` fields are ABSENT (replaced by the nested `node`)

#### Scenario: yastatus --json includes audit timestamps
- **WHEN** a task with `created_at` and `updated_at` datetimes is rendered via `--json`
- **THEN** the JSON object's `created_at` and `updated_at` fields are ISO-8601 strings (e.g. `"2026-07-06T12:00:00+00:00"`)

#### Scenario: yastatus --json engine always present
- **WHEN** a task with `context.engine="g09"` is rendered via `--json`
- **THEN** the JSON object's `engine` field is `"g09"` (never null — `TaskContext.engine` is required)

#### Scenario: yastatus --json empty result is empty list
- **WHEN** `yastatus --json` is invoked and the query returns no tasks
- **THEN** the output is `[]` and the process exits `0`

#### Scenario: yastatus --json composes with -j
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes with `--json`)

### Requirement: yastatus view mode connects via SSH with correct node params

When `-v` (or `-v -o`) is given, `yastatus` SHALL, for each RUNNING task with
an allocated IP, connect to the remote machine via `SSHMachineRepository`
(resolving a `MachineSession` via `repository.get_session` / a fresh
`repository.connect`), display a tail of the remote `OUTPUT` file, optionally
download and parse a CRYSTAL convergence snippet (when `-o` is also given),
and disconnect. The connection SHALL pass the resolved `node` to
`repository.connect(node=node, ...)`; the login user and port come from
`node.username` / `node.port` (NOT from separate `username`/`port` arguments —
`connect` reads them from the node). A private
`_resolve_conn_params(node, config)` helper resolves the jump-host parameters
(mirroring `orchestrator._connect_machine_consumer:209-214`):

- The login user is `node.username` (NOT a cloud username — the previous
  implementation's `for c in config.clouds: ssh_user = c.username` took the
  last cloud's username, which was a bug).
- The port is `node.port` (the previous implementation always used the
  gateway default of 22).
- `jump_host` and `jump_username` SHALL come from the cloud whose `prefix
  == node.cloud` (if any such cloud has both set), falling back to
  `config.remote.jump_host` / `config.remote.jump_username` for static nodes
  or clouds without a jump host. The previous implementation never passed
  jump-host parameters, so `yastatus -v` on a cloud node behind a jump host
  was functionally broken.

The `jump_host` and `jump_username` parameters SHALL be passed to
`repository.connect(...)`. The
convergence snippet SHALL be stored in a `tempfile`-based file (NOT the
previous fixed-name `local_calc_snippet.tmp`) and cleaned up in a
`try/finally` block so it is removed even when `_render_view` raises.

#### Scenario: yastatus -v uses node.username not cloud username
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `username="yascheduler"` and `cloud="hetzner"`, and the `hetzner` cloud config has `username="hcloud-user"`
- **THEN** `repository.connect(node=node, ...)` is called with a `node` whose `username == "yascheduler"` (the node's username, NOT the cloud's), and no separate `username` argument is passed

#### Scenario: yastatus -v uses node.port
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `port=2222`
- **THEN** `repository.connect(node=node, ...)` is called with a `node` whose `port == 2222` (NOT the repository default of 22), and no separate `port` argument is passed

#### Scenario: yastatus -v resolves jump host from matching cloud
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `cloud="hetzner"`, and the `hetzner` cloud config has `jump_host="jump.example.com"` and `jump_username="jumper"`
- **THEN** `repository.connect(...)` is called with `jump_host="jump.example.com"` and `jump_username="jumper"`

#### Scenario: yastatus -v falls back to config.remote for static nodes
- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a static node (`cloud=None`), and `config.remote.jump_host` is set
- **THEN** `repository.connect(...)` is called with `jump_host=config.remote.jump_host` and `jump_username=config.remote.jump_username`

#### Scenario: yastatus -v -o uses a tempfile for the convergence snippet
- **WHEN** `yastatus -v -o` is invoked
- **THEN** the convergence snippet is written to a `tempfile.NamedTemporaryFile`/`mkstemp`-created file with a unique name (NOT the fixed `local_calc_snippet.tmp`), so concurrent invocations do not collide

#### Scenario: yastatus cleans up the snippet on exception
- **WHEN** `yastatus -v -o` is invoked and `_render_view` raises an exception during SSH or parse
- **THEN** the convergence snippet file is removed by the `try/finally` block (the previous implementation skipped cleanup on the exception path)


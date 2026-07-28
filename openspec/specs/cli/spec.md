## Purpose

The six CLI command entry points (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`,
`yainit`, `yascheduler`), the three daemon launchers (`daemonize`,
`daemon_systemd`, `daemon_sysv`), the shared argparse helpers, and the async
daemon core. Each CLI command is a synchronous `def` entry point that calls
`asyncio.run(_<name>_async(argv))` and delegates to use cases via dependency
injection (`yainit` is a bootstrap exception).

## Requirements

### Requirement: Shared argparse helpers

The system SHALL provide reusable argparse helpers consumed by all six CLI
command entry points and the three daemon launchers:

- `existing_path(s: str) -> Path` — argparse type validator returning `Path(s)`
  if `s` is an existing file, else raising `argparse.ArgumentTypeError` (→ exit
  2).
- `add_config_arg(parser, *, default=CONFIG_FILE, dest="config")` — adds
  `--config PATH` with `type=existing_path`.
- `add_log_level_arg(parser, *, default="WARNING", short=None)` — adds
  `--log-level` with explicit
  `choices=["DEBUG","INFO","WARNING","ERROR","CRITICAL"]`. When `short` is
  given (e.g. `"-l"`), it registers the short flag as alias.
- `add_log_file_arg(parser, *, default=None)` — adds `--log-file PATH` (path
  string, no existence check).

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

The system SHALL provide the shared daemon runtime consumed by all three daemon
entry points:

- `configure_logger(log_file: str | Path | None, level: int, *, timestamp: bool = False) -> logging.Logger`
  — configures the ROOT logger: always adds a `StreamHandler(sys.stderr)`, adds
  a `FileHandler(log_file)` only when `log_file is not None`, wires a
  `LogFormatter` (with timestamping enabled iff `timestamp=True`) onto both
  handlers as a single shared instance, sets `backoff` and `asyncssh` loggers to
  `ERROR`, and calls `logging.captureWarnings(True)`.
- `async def run_daemon(config: Config, logger: logging.Logger) -> None` — the
  async daemon core: awaits `make_daemon(config)` to build the
  `Orchestrator`, registers SIGTERM/SIGINT handlers on the running event loop
  (cancel outstanding tasks, sleep 250ms for SSL close, log "Done"), then
  awaits `orch.start()` wrapped in a `try/finally` whose `finally` clause awaits
  `orch.stop()`.

Each daemon entry point SHALL be a synchronous `def` that builds its own
argparse parser via the shared helpers, calls `configure_logger`, loads
`Config.from_config_parser(args.config)`, and invokes
`asyncio.run(run_daemon(config, logger))`.

Each daemon entry point SHALL pass `timestamp=True` to `configure_logger` when
its output is NOT captured by journald (i.e. the foreground launcher
`daemonize` and the file-logging launcher `daemon_sysv`), and SHALL pass
`timestamp=False` (or omit it) when its stderr is captured by journald (i.e.
the `daemon_systemd` launcher), because journald stamps records itself.

#### Scenario: configure_logger writes to stderr when log_file is None
- **WHEN** `configure_logger(log_file=None, level=logging.INFO)` is called
- **THEN** the root logger has a `StreamHandler(sys.stderr)` and no `FileHandler`
- **AND** the `StreamHandler` is configured with a `LogFormatter`

#### Scenario: configure_logger writes to file and stderr when log_file is set
- **WHEN** `configure_logger(log_file="/tmp/y.log", level=logging.INFO)` is called
- **THEN** the root logger has both a `StreamHandler(sys.stderr)` and a `FileHandler` pointed at `/tmp/y.log`
- **AND** both handlers are configured with a `LogFormatter` (single formatter, no per-handler format variants)

#### Scenario: configure_logger timestamp defaults to off
- **WHEN** `configure_logger(log_file=None, level=logging.INFO)` is called without a `timestamp` argument
- **THEN** the wired `LogFormatter` does NOT prepend a timestamp to rendered records

#### Scenario: configure_logger timestamp=True enables ISO 8601 prefix on both handlers
- **WHEN** `configure_logger(log_file="/tmp/y.log", level=logging.INFO, timestamp=True)` is called
- **THEN** both the `StreamHandler(sys.stderr)` and the `FileHandler` are wired with a `LogFormatter` that prepends an ISO 8601 local-time timestamp to every rendered record

#### Scenario: configure_logger does not call basicConfig
- **WHEN** `configure_logger(...)` is invoked
- **THEN** `logging.basicConfig` is NOT called (handlers and level are set explicitly)

#### Scenario: run_daemon is async
- **WHEN** `run_daemon` is inspected
- **THEN** it is declared `async def run_daemon(config, logger) -> None`

#### Scenario: run_daemon awaits make_daemon and orch.start
- **WHEN** `run_daemon(config, logger)` is awaited
- **THEN** `make_daemon(config)` is awaited (without forwarding `logger`), SIGTERM/SIGINT handlers are registered on the running event loop, `orch.start()` is awaited, and the `finally` block awaits `orch.stop()`

#### Scenario: start() exception propagates after cleanup
- **WHEN** `orch.start()` raises an exception
- **THEN** the `finally` block's `orch.stop()` still runs (cancelling early background jobs, closing the HTTP session) before the exception propagates out of `run_daemon`

#### Scenario: entry points call asyncio.run
- **WHEN** any of `daemonize`, `daemon_systemd`, `daemon_sysv` is inspected
- **THEN** the entry point is a synchronous `def` that calls `asyncio.run(run_daemon(...))`

#### Scenario: daemonize enables the ISO 8601 timestamp
- **WHEN** `daemonize` (the foreground `yascheduler` launcher) calls `configure_logger`
- **THEN** it passes `timestamp=True`, so foreground output lines begin with a local ISO 8601 timestamp

#### Scenario: daemon_sysv enables the ISO 8601 timestamp
- **WHEN** `daemon_sysv` (the file-logging launcher) calls `configure_logger`
- **THEN** it passes `timestamp=True`, so file output lines begin with a local ISO 8601 timestamp

#### Scenario: daemon_systemd does NOT enable the ISO 8601 timestamp
- **WHEN** `daemon_systemd` (the journald-supervised launcher) calls `configure_logger`
- **THEN** it passes `timestamp=False` (or omits the argument), so stderr-into-journald output lines do NOT carry a duplicate leading timestamp

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

### Requirement: yasubmit parses flags via argparse

`submit()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasubmit",
description="Submit task to yascheduler via AiiDA script")` exposing one
positional argument:
- `script` (positional, type validator that returns `Path(s)` if `s` is an
  existing file or raises `argparse.ArgumentTypeError`): the path to the AiiDA
  script file. A missing file is an argparse error (exit `2`), not a runtime
  error (exit `1`).

#### Scenario: yasubmit prog is yasubmit in help and errors
- **WHEN** `yasubmit --help` or any argparse error is shown
- **THEN** the program name displayed is `yasubmit` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasubmit validates script content in the body

After argparse succeeds, `submit()` SHALL validate the script *content* in the
body (exit `1` on failure, NOT exit `2`). The validations are:
- The script's parsed `script_params` dict MUST contain an `ENGINE` key. If
  absent, `submit()` SHALL raise `ValueError("Script has not defined an
  engine")`, print `Error: Script has not defined an engine` to stderr, and
  exit `1`.
- The `ENGINE` value MUST be a known engine name in `config.engines`. If
  `config.engines.get(engine_name)` returns `None`, `submit()` SHALL raise
  `ValueError(f"Engine {engine_name} is not supported")`, print the message to
  stderr, and exit `1`.

#### Scenario: yasubmit exits 1 when ENGINE key is missing
- **WHEN** `yasubmit script.in` is invoked with a script containing `LABEL = Test` but no `ENGINE = ...` line
- **THEN** `Error: Script has not defined an engine` is printed to stderr, nothing is printed to stdout, and the process exits `1`

#### Scenario: yasubmit exits 1 when engine is unknown
- **WHEN** `yasubmit script.in` is invoked with a script containing `ENGINE = unknown` and `config.engines.get("unknown")` returns `None`
- **THEN** `Error: Engine unknown is not supported` is printed to stderr, nothing is printed to stdout, and the process exits `1`

### Requirement: yasubmit preserves AiiDA stdout compatibility

The success path of `yasubmit` SHALL print exactly `str(task_id)` to stdout —
no prefix, suffix, JSON envelope, or decoration. The failure path SHALL print
nothing to stdout and an error message to stderr.

#### Scenario: yasubmit success prints only the task id
- **WHEN** `yasubmit script.in` succeeds and `deps.submit(...)` returns `42`
- **THEN** stdout contains exactly `42` (possibly with a trailing newline from `print`), with no prefix, suffix, JSON envelope, or other decoration

#### Scenario: yasubmit failure prints nothing to stdout
- **WHEN** `yasubmit script.in` fails (ENGINE key missing, engine unknown, DB error, or any exception)
- **THEN** stdout is empty; the error message is on stderr; the process exits `1` (or `2` for argparse errors)

#### Scenario: AiiDA plugin is unchanged
- **WHEN** the AiiDA scheduler entrypoint is inspected
- **THEN** the entrypoint still returns `f"yasubmit {submit_script}"` and parses `int(stdout.strip())` (the AiiDA contract is not touched)

### Requirement: Daemon launcher argparse and defaults

Each daemon launcher SHALL build its own argparse parser via the shared helpers
and call `run_daemon` with ready arguments. The three launchers are `daemonize`,
`daemon_systemd`, and `daemon_sysv`. Each SHALL set `prog="yascheduler"` so
`--help` shows the product name. Each SHALL accept `--config` (default
`CONFIG_FILE`, `type=existing_path`) and `--log-level` (default `INFO`, choices
`["DEBUG","INFO","WARNING","ERROR","CRITICAL"]`). Each SHALL accept `--log-file`
(default `None` → stderr for `daemonize` and `daemon_systemd`; default
`LOG_FILE` for `daemon_sysv`).

`daemonize` (the foreground `yascheduler` console_script) SHALL accept the short
flag `-l`/`--log-level`.

`daemon_sysv` SHALL additionally accept `-p`/`--pid-file` (default `PID_FILE`)
and SHALL keep the short flag `-l`/`--log-file`. `--config` and
`--log-level` SHALL be long-only in `daemon_sysv`.

`daemon_sysv` SHALL wrap the daemon execution in a `python-daemon`
`DaemonContext` with `working_directory="/"`. `daemonize` and `daemon_systemd`
SHALL run in the foreground (no `python-daemon`).

#### Scenario: daemonize accepts -l as --log-level alias
- **WHEN** `yascheduler -l DEBUG` is invoked
- **THEN** `args.log_level == "DEBUG"` (the `-l` short flag aliases `--log-level`; backward compatibility)

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
- **THEN** `args.pid_file == "/var/run/yascheduler.pid"` and `args.log_file == "/var/log/yascheduler.log"` (compatible with the installed `yascheduler.sh` init script)

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

- `0` — success (clean shutdown for daemons, completed operation for CLI
  commands), and `--help`.
- `1` — runtime error caught by the top-level `try/except Exception`; the entry
  point prints `Error: <exception>` to stderr and calls `sys.exit(1)`.
- `2` — argparse error (unknown flag, missing positional, invalid choice) or
  `existing_path` `ArgumentTypeError` (missing `--config` file). argparse and
  the type validator handle this natively; the `except Exception` block does
  not catch `SystemExit` (which is not an `Exception` subclass), so argparse's
  exit propagates.

#### Scenario: daemon runtime error exits 1 with Error message
- **WHEN** `make_daemon(config)` raises `Exception("db connection refused")`
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

The `yanodes` command SHALL list nodes and their currently running tasks. The
command is a synchronous entry point that calls
`asyncio.run(_show_nodes_async(argv))` with `argv: list[str] | None = None`.
Output row order SHALL preserve the order returned by `uow.nodes.list_all()`
(no sorting). Each node SHALL produce exactly one output row (table) or one
output object (JSON).

#### Scenario: yanodes entry point uses asyncio.run
- **WHEN** the `show_nodes` callable is inspected
- **THEN** it is a synchronous `def show_nodes(argv: list[str] | None = None)` that calls `asyncio.run(_show_nodes_async(argv))`

#### Scenario: yanodes joins nodes to tasks by node_id
- **WHEN** the in-memory join runs
- **THEN** each node is matched to its running task by matching `allocated_node_id` to `node.node_id` (the join key is `node_id`, not `ip`)

### Requirement: yanodes parses flags via argparse

`show_nodes()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yanodes",
description="Show nodes and their running tasks")` exposing:
- `--json` (`store_true`): emit JSON instead of the default table. Selects the
  renderer; not a filter.
- `--enabled` (`store_true`): include only nodes where `node.enabled` is True.
- `--disabled` (`store_true`): include only nodes where `node.enabled` is False.
- `--busy` (`store_true`): include only nodes that have ≥1 RUNNING task with
  `allocated_node_id == node.node_id`.
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

#### Scenario: yanodes --cloud and --no-cloud are mutually exclusive
- **WHEN** `yanodes --cloud hetzner --no-cloud` is invoked
- **THEN** argparse prints a usage error to stderr and exits `2` (mutex group violation)

#### Scenario: yanodes filters compose by AND
- **WHEN** `yanodes --enabled --busy --cloud hetzner` is invoked
- **THEN** only nodes that are enabled AND busy AND have `cloud == "hetzner"` are listed

#### Scenario: yanodes --enabled lists only enabled nodes
- **WHEN** `yanodes --enabled` is invoked against a node set containing both enabled and disabled nodes
- **THEN** only the enabled nodes appear in the output

### Requirement: yanodes default table output format

The default output of `yanodes` (when `--json` is not given) SHALL be a
fixed-width text table rendered with stdlib string formatting only (no external
dependencies such as `rich` or `tabulate`). The table SHALL have a header row
followed by one data row per node, in the order returned by
`uow.nodes.list_all()` (which is `ORDER BY node_id`). Column widths SHALL be
computed from the data so the table is self-aligning regardless of value
lengths.

The columns SHALL be: `NODE_ID`, `HOSTNAME`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`,
`TASK_ID`, `LABEL`. `NODE_ID` is the first column (identity first). Display-only
transformations SHALL apply to the table cells:

| column   | raw value       | table cell                       |
| -------- | --------------- | -------------------------------- |
| NODE_ID  | `node.node_id`    | `str(node.node_id)` (the bare int, via `NodeId.__str__`) |
| HOSTNAME | `node.hostname`   | as-is                            |
| PORT     | `node.port`       | `-` when `22`, else the int      |
| NCPUS    | `node.ncpus`      | `MAX` when `None` (or legacy `0`), else the int |
| ENABLED  | `node.enabled`    | `yes` when True, `no` when False |
| CLOUD    | `node.cloud`      | `-` when None, else the string   |
| TASK_ID  | `task.task_id`     | `-` when free, else the int      |
| LABEL    | `task.label`       | `-` when free, else the string   |

A node is "free" when no RUNNING task has `allocated_node_id == node.node_id`;
it is "busy" when exactly one RUNNING task does (the one-task-per-node
invariant).

#### Scenario: yanodes table has a header row
- **WHEN** `yanodes` is invoked (with or without filter flags)
- **THEN** the first line of output is the header row `NODE_ID`, `HOSTNAME`, `PORT`, `NCPUS`, `ENABLED`, `CLOUD`, `TASK_ID`, `LABEL` (column separators and exact spacing follow the fixed-width computation)

#### Scenario: yanodes table shows a busy node
- **WHEN** a node with `node_id=1`, `hostname="[IP]"`, `port=22`, `ncpus=4`, `enabled=True`, `cloud=None` has a RUNNING task with `task_id=7`, `label="my_job"`
- **THEN** one row is emitted with NODE_ID=`1`, HOSTNAME=`[IP]`, PORT=`-`, NCPUS=`4`, ENABLED=`yes`, CLOUD=`-`, TASK_ID=`7`, LABEL=`my_job`

#### Scenario: yanodes table shows MAX for None ncpus
- **WHEN** a node has `ncpus=None`
- **THEN** the NCPUS cell is `MAX`

#### Scenario: yanodes table shows MAX for legacy zero ncpus
- **WHEN** a node has `ncpus=0` (a pre-migration row viewed before migration 013 runs)
- **THEN** the NCPUS cell is `MAX` (backward-compatible with the legacy sentinel)

#### Scenario: yanodes table no external deps
- **WHEN** the implementation of the table renderer is inspected
- **THEN** it uses only stdlib string formatting (f-string width specifiers, `str.ljust`, or equivalent) and does NOT import `rich`, `tabulate`, or any other third-party formatting library

### Requirement: yanodes --json output format

When `--json` is given, `yanodes` SHALL emit `json.dumps(list_of_objects)` where
each object represents one node with raw domain values (NO display
transformations — no `-`, no `MAX`, no `yes`/`no`). The object schema SHALL be:

```
{"node_id": int, "hostname": str, "port": int, "ncpus": int | null, "enabled": bool,
 "cloud": str | null, "jump_host": str | null, "jump_port": int,
 "jump_username": str, "external_id": str | null, "status": str,
 "created_at": str, "updated_at": str,
 "occupied_by": {"task_id": int, "label": str} | null}
```

One object per node, in the order returned by `uow.nodes.list_all()`.

#### Scenario: yanodes --json emits a list of objects
- **WHEN** `yanodes --json` is invoked against a non-empty node set
- **THEN** the output is valid JSON parseable as a list of objects, one per node, in `list_all()` order

#### Scenario: yanodes --json includes node_id
- **WHEN** a node with `node_id=NodeId(5)` is listed
- **THEN** the JSON object's `node_id` field is `5` (the bare int via `.value`)

#### Scenario: yanodes --json uses hostname key not ip
- **WHEN** a node with `hostname="10.0.0.1"` is listed via `yanodes --json`
- **THEN** the JSON object has a `"hostname"` key with value `"10.0.0.1"` and does NOT have an `"ip"` key

#### Scenario: yanodes --json emits null ncpus for None
- **WHEN** a node with `ncpus=None` is listed via `yanodes --json`
- **THEN** its object's `"ncpus"` is JSON `null`

#### Scenario: yanodes --json emits positive int ncpus
- **WHEN** a node with `ncpus=8` is listed via `yanodes --json`
- **THEN** its object's `"ncpus"` is the int `8`

#### Scenario: yanodes --json includes new node fields
- **WHEN** a node with `jump_host=None`, `jump_port=22`, `jump_username="root"`, `external_id=None`, `status=NodeStatus.OTHER`, `created_at=<datetime>`, `updated_at=<datetime>` is listed via `yanodes --json`
- **THEN** the JSON object includes `jump_host: null`, `jump_port: 22`, `jump_username: "root"`, `external_id: null`, `status: "OTHER"`, `created_at: <isoformat>`, `updated_at: <isoformat>`

#### Scenario: yanodes --json empty result is empty list
- **WHEN** `yanodes --json` is invoked and no node matches the filters
- **THEN** the output is `[]` and the process exits `0`

### Requirement: yanodes joins nodes to running tasks in memory

`show_nodes()` SHALL perform the node-to-running-task join in memory within a
single UoW: it SHALL read `uow.nodes.list_all()` and
`uow.tasks.list_by_status({TaskStatus.RUNNING})` (two reads within one UoW),
  build a `tasks_by_node_id` dict mapping `allocated_node_id` to the single
  running task on that node, and look up each node's task via
  `tasks_by_node_id.get(node.node_id)`.

#### Scenario: yanodes join is O(n+m)
- **WHEN** the implementation of the in-memory join is inspected
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
transformations), so that scripts can consume the output without reverse-mapping
display tokens. `yanodes --json` is the first instance of the convention;
`yastatus --json` is the second instance.

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
argparse type validator parses the grammar
`[user@]host[:port][~ncpus]` where host is IPv4 or bracketed IPv6, port is
1..65535 (default 22), ncpus is non-negative (absent or ~0 → None). Malformed
input raises `argparse.ArgumentTypeError` (exit 2).

#### Scenario: yasetnode full spec user@host:port~ncpus
- **WHEN** a positional argument `"deploy@[IP]:2222~4"` is parsed
- **THEN** the result carries `host_spec` with host `[IP]`, username `deploy`, port `2222`, ncpus `4`

#### Scenario: yasetnode bracketed IPv6 with port
- **WHEN** a positional argument `"[fe80::1]:2222"` is parsed
- **THEN** the result carries `host_spec` with host `"fe80::1"`, username `None`, port `2222`, ncpus `None`

#### Scenario: yasetnode tilde-zero maps to None ncpus
- **WHEN** a positional argument `"[IP]~0"` is parsed
- **THEN** the result carries `host_spec` with host `[IP]`, username `None`, port `22`, ncpus `None` (the `0` is normalized to unlimited sentinel)

#### Scenario: yasetnode malformed host exits 2
- **WHEN** `yasetnode ::1` is invoked (unbracketed IPv6)
- **THEN** the positional type validator raises `argparse.ArgumentTypeError`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode prog is yasetnode in help and errors
- **WHEN** `yasetnode --help` or any argparse error is shown
- **THEN** the program name displayed is `yasetnode` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yasetnode parses flags via argparse

`manage_node()` SHALL parse `argv` with `argparse.ArgumentParser(prog="yasetnode")`
exposing:
- `host` (positional, host-grammar type): node target — node_id or host spec.
- `--skip-setup` (`store_true`): skip remote setup. Valid ONLY on add path.
- `--remove-soft` / `--remove-hard` (`store_true`, mutually exclusive): soft or
  hard remove.

`--skip-setup` with either remove flag, or node_id positional on add path, SHALL
call `parser.error(...)` (exit 2). Flags use `action="store_true"`. Parser
accepts `argv: list[str] | None = None` (None → `sys.argv`).

#### Scenario: yasetnode --remove-soft --remove-hard exits 2
- **WHEN** `yasetnode [IP] --remove-soft --remove-hard` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yasetnode --skip-setup --remove-hard exits 2
- **WHEN** `yasetnode [IP] --skip-setup --remove-hard` is invoked
- **THEN** the body-level `parser.error(...)` fires, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode node_id positional with add path exits 2
- **WHEN** `yasetnode 5` is invoked (a node_id positional with no `--remove-soft`/`--remove-hard`)
- **THEN** the body-level `parser.error(...)` fires (a node cannot be added by id), argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yasetnode argv parameter reads sys.argv when None
- **WHEN** `manage_node()` is invoked with `argv=None` (the console_script default)
- **THEN** `parser.parse_args(None)` is called, which reads `sys.argv[1:]`

#### Scenario: yasetnode argv parameter accepts explicit list
- **WHEN** `manage_node(["[IP]", "--remove-hard"])` is invoked
- **THEN** `parser.parse_args(["[IP]", "--remove-hard"])` is called, with no reading of `sys.argv`

### Requirement: yasetnode output channels and verbatim success messages

On success, `manage_node()` SHALL print the following messages verbatim to
stdout, emitted **after** `await uow.commit()` succeeds:

| path | message (verbatim) |
| --- | --- |
| add, before setup | `Setup host...` |
| add, after commit | `Added host to yascheduler: {host}:{port}` |
| remove-hard, per task | `An associated task {task_id} at {host} is now marked done!` |
| remove-hard, after commit | `Removed host from yascheduler: {host}` |
| remove-soft, has tasks | `A task associated, prevent from assigning the new tasks` / `Prevented from assigning the new tasks: {host}` |
| remove-soft, no tasks | `No tasks associated, remove node immediately` / `Removed host from yascheduler: {host}` |

`{host}` is the parsed `HostSpec.host` (host spec path) or resolved `node.hostname`
(node_id path). On failure, print `Error: <message>` to stderr and exit 1.

#### Scenario: yasetnode add success prints verbatim messages to stdout after commit
- **WHEN** `yasetnode [IP]` succeeds (without `--skip-setup`)
- **THEN** stdout contains `Setup host...` and `Added host to yascheduler: [IP]:22`, in that order

#### Scenario: yasetnode remove-hard prints per-task messages after commit
- **WHEN** `yasetnode [IP] --remove-hard` succeeds against a node with RUNNING task ids `[1, 2]`
- **THEN** stdout contains `An associated task 1 at [IP] is now marked done!` and `An associated task 2 at [IP] is now marked done!` and `Removed host from yascheduler: [IP]`, all emitted after `uow.commit()` returns

### Requirement: yasetnode positional discriminates node_id from host

The positional argument parser SHALL discriminate:
- if the input is pure-digit, it is a `node_id`;
- otherwise it is a host spec matching the grammar `[user@]host[:port][~ncpus]`.

A node cannot be added by id (adding requires a real host). On the add path,
a pure-digit positional with no remove flag SHALL call
`parser.error(...)` (exit `2`).

On the remove path, the validation UoW resolves the `Node` early —
`uow.nodes.get_by_id(node_id)` on the node_id path, or listing all nodes and
filtering by `hostname` on the host spec path (hostname is not a unique key).
If the node is not found, a "not in DB" error exits `1`. If found, the `Node`
is passed to the remove helpers, which use `node.node_id` for mutators and
`node.hostname` for stdout messages.

#### Scenario: yasetnode pure-digit positional is a node_id
- **WHEN** a positional `"5"` is parsed
- **THEN** the result identifies `node_id=5`

#### Scenario: yasetnode add-by-id is rejected
- **WHEN** `yasetnode 5` is invoked (no `--remove-soft`/`--remove-hard`)
- **THEN** argparse surfaces `parser.error(...)` with exit `2` and a message stating a node cannot be added by id

#### Scenario: yasetnode remove-by-id unknown id is a body error
- **WHEN** `yasetnode 999 --remove-hard` is invoked and no node with node_id=999 exists
- **THEN** `get_by_id` returns `None` and the body raises a "not in DB" error with exit `1`

### Requirement: yasetnode gateway lifecycle and resource safety

On the add path, `manage_node()` SHALL create a node in the DB, connect to it
via SSH, perform optional remote setup, and mark the node enabled. The jump
host, jump username, and jump port are read from `config.remote` (with
sensible defaults) and stored on the `Node`.

On connect failure, the partially-created row SHALL be removed (no residual
`enabled=FALSE` row). Gateway/jump resources SHALL be released when the add
path completes or fails (no leak). On the update path (setting `enabled=True`),
a second commit SHALL confirm the final state.

#### Scenario: yasetnode constructs repository once and passes to add helper

- **WHEN** `yasetnode [IP]` is invoked on the add path
- **THEN** exactly one `SSHMachineRepository()` is constructed (at the top of `manage_node`), and that instance is passed as a parameter to the add helper

#### Scenario: yasetnode add-path stamps jump from config.remote before insert

- **WHEN** the add helper is called with a valid host spec and `config.remote.jump_host="bastion.example.com"`, `config.remote.jump_username="jumper"`, `config.remote.jump_port=2222`
- **THEN** the `NewNode` passed to `insert` carries `jump_host="bastion.example.com"`, `jump_username="jumper"`, `jump_port=2222`; the subsequent `repository.connect(node=T, client_keys=...)` call passes no `jump_host` / `jump_username` arguments, and the tunnel leg is built from `T.jump_*`

#### Scenario: yasetnode add-path uses default jump_port when [remote] key absent

- **WHEN** the add helper is called with a valid host spec and the `[remote]` section does NOT set `jump_port`
- **THEN** the `NewNode` passed to `insert` carries `jump_port=22` (the `RemoteDefaults.jump_port` default)

#### Scenario: yasetnode add-path encodes absent ncpus as None

- **WHEN** the add helper is called with a host spec whose `~ncpus` clause is absent (so `HostSpec.ncpus is None`)
- **THEN** the `NewNode` passed to `insert` carries `ncpus=None` (the value is NOT coerced to `0`); the persisted tmp row stores SQL `NULL`

#### Scenario: yasetnode add-path encodes explicit ncpus

- **WHEN** the add helper is called with a host spec `host~8` (so `HostSpec.ncpus == 8`)
- **THEN** the `NewNode` passed to `insert` carries `ncpus=8`; the persisted tmp row stores `8`

#### Scenario: yasetnode add-path insert-create-connect lifecycle

- **WHEN** the add helper is called with a valid host spec
- **THEN** the row is inserted FIRST (before any SSH work) with `enabled=False`; after successful connect and optionally `session.setup_node(config.engines)`, the node's `enabled` is updated to `True`

#### Scenario: yasetnode add-path rolls back tmp row on connect failure

- **WHEN** `repository.connect(node=T, client_keys=...)` raises `MachineConnectionError` (or any `Exception`) during the add helper
- **THEN** the tmp row is best-effort removed; no `enabled=TRUE` row remains; the orchestrator never saw the row (it was `enabled=FALSE`)

### Requirement: yasetnode dispatches add and remove paths

After argparse succeeds, `manage_node()` SHALL open a short read-only validation
UoW, resolve the target `Node`, and close it. It SHALL then dispatch to exactly
one helper, each opening its OWN UoW:
- If `already_there` and no remove flag: raise `ValueError` → exit 1.
- If NOT `already_there` and a remove flag: raise `ValueError` → exit 1.
- If `--remove-hard`: list RUNNING task ids, mark DONE, remove node, commit.
- If `--remove-soft`: disable if RUNNING tasks exist, else remove; commit.
- Otherwise (add): resolve username, call the add helper.

The remove helpers SHALL accept `node: Node` (not `ip: str`).

#### Scenario: yasetnode opens a validation UoW then dispatches via per-helper UoW
- **WHEN** `yasetnode` is invoked with a valid host spec and a add/remove flag combination
- **THEN** `Config.from_config_parser(args.config)` is called, `make_cli_deps(config)` is called to obtain `CLIDeps`, an `SSHMachineRepository` is constructed at the top of `manage_node` (before any UoW is opened), a short read-only UoW is opened to resolve the target `Node`, and the body dispatches to exactly one helper; each helper opens its OWN UoW via `deps.uow_factory()` to perform its mutations, commit, and print. On the add path, the repository is passed to the add helper.

### Requirement: yastatus queries task status

The `yastatus` command SHALL query and display task status, optionally with
remote machine output (verbose mode) and convergence info, resolving nodes via
a single batch lookup by `allocated_node_id`. In view/json mode, the command
SHALL open a single query-phase UoW, read tasks, and read nodes via
`uow.nodes.get_by_ids(...)`. The UoW is closed before any SSH work. The JSON
output SHALL emit a nested `node` object (NOT flat `allocated_ip`/`port`/`cloud`
fields).

#### Scenario: yastatus queries tasks and resolves nodes
- **WHEN** yastatus is invoked
- **THEN** it opens a single query-phase UoW, reads tasks, reads nodes via batch lookup, and renders the output

### Requirement: yastatus default output format (AiiDA compatibility)

`_MAP_STATUS_YASCHEDULER` SHALL have keys `{TO_DO, RUNNING, DONE}`.

The default renderer SHALL be `print(f"{task.task_id}   {task.status.name}")`
per task.

#### Scenario: yastatus default output is two-column
- **WHEN** `yastatus` is invoked against tasks with ids 1 (RUNNING), 2 (TO_DO), 3 (DONE)
- **THEN** the default invocation (no `-j`) excludes DONE and prints exactly `1   RUNNING` and `2   TO_DO` (one line per RUNNING/TO_DO task, in the order returned by `list_by_status`)

#### Scenario: yastatus -j includes DONE tasks in default format
- **WHEN** `yastatus -j 3` is invoked and task 3 has status DONE
- **THEN** the default renderer prints `3   DONE` (DONE is a valid AiiDA state and is included because `-j` queries by id, not by status)

#### Scenario: AiiDA plugin is unchanged
- **WHEN** the AiiDA scheduler entrypoint is inspected
- **THEN** the joblist command still returns `yastatus` or `yastatus --jobs <ids>` and the joblist output parser still does `for job_id, status in job.split()` with `_MAP_STATUS_YASCHEDULER` (the AiiDA contract is not touched)

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
  renderer.
- `-o/--convergence` (`action="store_true"`): NOT in the mutex group (it
  modifies `-v`, so `-o -v` must remain valid). A body-check after `parse_args`
  SHALL reject `-o` without `-v` via `parser.error("--convergence requires --view")`
  (exit 2).

`--help` shows the standard argparse help screen (argparse default). The parser
SHALL use `action="store_true"` for all boolean flags.

#### Scenario: yastatus -v -i mutually exclusive
- **WHEN** `yastatus -v -i` is invoked
- **THEN** argparse prints a usage error to stderr (mutex group violation) and exits `2`

#### Scenario: yastatus -o without -v exits 2
- **WHEN** `yastatus -o` is invoked (without `-v`)
- **THEN** the body-check calls `parser.error("--convergence requires --view")`, argparse prints a usage error to stderr, and the process exits `2`

#### Scenario: yastatus prog is yastatus in help and errors
- **WHEN** `yastatus --help` or any argparse error is shown
- **THEN** the program name displayed is `yastatus` (NOT the console_script path derived from `sys.argv[0]`)

### Requirement: yastatus --json output format

When `--json` is given, `yastatus` SHALL emit `json.dumps(list_of_objects)` where
each object represents one task with raw domain values (NO display
transformations — no `MAX`, no `-`, no banner). The object schema SHALL be
exactly these fields:

```
{"task_id": int, "status": str, "label": str, "engine": str,
 "local_folder": str | null, "remote_folder": str | null,
 "created_at": str, "updated_at": str,
 "node": {"hostname": str, "port": int, "username": str,
          "cloud": str | null, "jump_host": str | null,
          "jump_port": int, "jump_username": str,
          "external_id": str | null, "status": str,
          "created_at": str, "updated_at": str} | null}
```

The `node` object is `null` when the task has no allocated node; otherwise it
carries the resolved `Node` fields. One object per task, in the order returned
by the query (`list_by_status` or `list_by_jobs`).

#### Scenario: yastatus --json emits a list of objects
- **WHEN** `yastatus --json` is invoked against a non-empty task set
- **THEN** the output is valid JSON parseable as a list of objects, one per task, in query order

#### Scenario: yastatus --json empty result is empty list
- **WHEN** `yastatus --json` is invoked and the query returns no tasks
- **THEN** the output is `[]` and the process exits `0`

#### Scenario: yastatus --json composes with -j
- **WHEN** `yastatus -j 1 2 --json` is invoked
- **THEN** `list_by_jobs(job_ids=["1", "2"])` is called and the JSON renderer prints the result (the `-j` filter composes with `--json`)

#### Scenario: yastatus --json node object uses hostname key
- **WHEN** a task with an allocated node that has `hostname="10.0.0.1"` is rendered via `yastatus --json`
- **THEN** the `node` object has a `"hostname"` key with value `"10.0.0.1"` and does NOT have an `"ip"` key

### Requirement: yastatus view mode connects via SSH with correct node params

When `-v` (or `-v -o`) is given, `yastatus` SHALL, for each RUNNING task with
an allocated node, connect to the remote machine via `SSHMachineRepository`
(resolving a `MachineSession` via `repository.get_session` / a fresh
`repository.connect`), display a tail of the remote `OUTPUT` file, optionally
download and parse a CRYSTAL convergence snippet (when `-o` is also given), and
disconnect. The connection SHALL use the `Node` values for login user, port,
and jump-leg parameters — `connect` reads them from the node. The convergence
snippet SHALL be cleaned up after display (no leaked temp files).

#### Scenario: yastatus -v uses node.username not cloud username

- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `username="yascheduler"` and `cloud="hetzner"`, and the `hetzner` cloud config has `username="hcloud-user"`
- **THEN** `repository.connect(node=node, ...)` is called with a `node` whose `username == "yascheduler"` (the node's username, NOT the cloud's), and no separate `username` argument is passed

#### Scenario: yastatus -v reads jump from Node not from CloudConfig

- **WHEN** `yastatus -v` is invoked against a RUNNING task allocated to a node with `cloud="hetzner"` and `jump_host="jump.example.com"` (stamped at creation), and the `hetzner` cloud config still has `jump_host="jump.example.com"` (unchanged)
- **THEN** `repository.connect(node=node, client_keys=...)` is called with no `jump_host` / `jump_username` arguments, and the tunnel leg is built from `node.jump_host` / `node.jump_username`

#### Scenario: yastatus -v follows Node jump even when CloudConfig changed

- **WHEN** `yastatus -v` is invoked against a node with `jump_host="old-bastion.example.com"` (stamped at creation), and the `hetzner` cloud config has since been edited to `jump_host="new-bastion.example.com"`
- **THEN** the tunnel leg uses `node.jump_host == "old-bastion.example.com"` (Node is the source of truth, not the live config)

### Requirement: Non-daemon CLI commands render through the structured log formatter

The five non-daemon CLI commands SHALL configure the ROOT logger through a
single shared non-daemon logger setup function before any other work, instead
of inlining root-logger configuration per command. The five commands are
yasubmit, yanodes, yastatus, yasetnode, and yainit.

The shared non-daemon logger setup SHALL: set the ROOT logger level to the
resolved `--log-level` value; ensure a `StreamHandler(sys.stderr)` exists on the
ROOT logger only when no handler is already present (so an outer test harness
that pre-attaches a handler remains authoritative); wire a `LogFormatter`
(timestamping disabled) onto any `StreamHandler` it adds; and call
`logging.captureWarnings(True)` so `warnings.warn(...)` output is routed
through logging.

The non-daemon logger setup SHALL NOT set the `asyncssh` logger to `ERROR` and
SHALL NOT add a `FileHandler`; the daemon-only side effects belong exclusively
to `configure_logger`.

When a non-daemon CLI emits a structured DEBUG trace record via
`logger.debug(msg, extra={...})` on its module-local logger, the rendered
output SHALL match the trace layout produced by `LogFormatter`, NOT the stdlib
default format. When a non-daemon CLI emits an INFO/WARN/ERROR record, the
rendered output SHALL match the regular layout produced by `LogFormatter`.

#### Scenario: yasubmit renders DEBUG trace records through LogFormatter

- **WHEN** `yasubmit` is invoked with `--log-level DEBUG` and its execution emits a structured DEBUG record via `logger.debug(msg, extra={...})`
- **THEN** the stderr line is the `LogFormatter` trace layout `[<module>][<funcName>]:<lineno> <message> <sorted key=value pairs>`, not the stdlib default format

#### Scenario: yanodes renders INFO records through LogFormatter

- **WHEN** `yanodes` is invoked with `--log-level INFO` and its execution emits an INFO record
- **THEN** the stderr line is the `LogFormatter` regular layout `<LEVEL> <name>: <message>`, not the stdlib default format

#### Scenario: yastatus renders DEBUG trace records through LogFormatter

- **WHEN** `yastatus` is invoked with `--log-level DEBUG` and its execution emits a structured DEBUG record
- **THEN** the stderr line is the `LogFormatter` trace layout, not the stdlib default format

#### Scenario: yasetnode renders DEBUG trace records through LogFormatter

- **WHEN** `yasetnode` is invoked with `--log-level DEBUG` and its execution emits a structured DEBUG record
- **THEN** the stderr line is the `LogFormatter` trace layout, not the stdlib default format

#### Scenario: yainit renders WARNING records through LogFormatter

- **WHEN** `yainit` is invoked with `--log-level WARNING` (or higher) and its execution emits a WARNING record
- **THEN** the stderr line is the `LogFormatter` regular layout `<LEVEL> <name>: <message>`

#### Scenario: non-daemon CLI LogFormatter does NOT prepend a timestamp

- **WHEN** any of the five non-daemon CLI commands renders a record via its wired `LogFormatter`
- **THEN** the output line does NOT carry a leading ISO 8601 timestamp (timestamping is reserved for non-journald daemon output)

#### Scenario: non-daemon CLI logger setup does NOT suppress asyncssh

- **WHEN** any of the five non-daemon CLI commands runs its shared logger setup
- **THEN** the `asyncssh` logger level is NOT changed (it is left at its inherited default), unlike `configure_logger` which sets `asyncssh` to `ERROR`

#### Scenario: non-daemon CLI logger setup does NOT add a FileHandler

- **WHEN** any of the five non-daemon CLI commands runs its shared logger setup
- **THEN** the ROOT logger has at most a `StreamHandler(sys.stderr)` and NO `FileHandler`

#### Scenario: non-daemon CLI logger setup preserves a pre-attached handler

- **GIVEN** an outer test harness has already attached a handler to the ROOT logger
- **WHEN** a non-daemon CLI command runs its shared logger setup
- **THEN** the pre-attached handler is NOT removed and NO additional `StreamHandler(sys.stderr)` is added (the `if not root.handlers` guard holds)

#### Scenario: non-daemon CLI logger setup enables captureWarnings

- **WHEN** any of the five non-daemon CLI commands runs its shared logger setup
- **THEN** `logging.captureWarnings(True)` is in effect, so subsequent `warnings.warn(...)` calls are routed through logging instead of being printed directly to stderr

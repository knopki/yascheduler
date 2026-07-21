## MODIFIED Requirements

### Requirement: Shared daemon core for entry points

The system SHALL provide the shared daemon runtime consumed by all three daemon
entry points:

- `configure_logger(log_file: str | Path | None, level: int) -> logging.Logger`
  — configures the ROOT logger: always adds a `StreamHandler(sys.stderr)`, adds
  a `FileHandler(log_file)` only when `log_file is not None`, sets `backoff` and
  `asyncssh` loggers to `ERROR`, and calls `logging.captureWarnings(True)`.
  SHALL NOT call `logging.basicConfig`.
- `async def run_daemon(config: Config, logger: logging.Logger) -> None` — the
  async daemon core: awaits `make_daemon(config)` to build the
  `Orchestrator`, registers SIGTERM/SIGINT handlers on the running event loop
  (cancel outstanding tasks, sleep 250ms for SSL close, log "Done"), then
  awaits `orch.start()` wrapped in a `try/finally` whose `finally` clause awaits
  `orch.stop()`. Signal-handler registration lives in `run_daemon` (not the
  entry points) because `loop.add_signal_handler` requires a running loop. The
  `logger` parameter is used ONLY for signal-handler messages inside
  `run_daemon`; it SHALL NOT be forwarded to `make_daemon`.

Each daemon entry point SHALL be a synchronous `def` that builds its own
argparse parser via the shared helpers, calls `configure_logger`, loads
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
- **THEN** `make_daemon(config)` is awaited (without forwarding `logger`), SIGTERM/SIGINT handlers are registered on the running event loop, `orch.start()` is awaited, and the `finally` block awaits `orch.stop()`

#### Scenario: start() exception propagates after cleanup

- **WHEN** `orch.start()` raises an exception
- **THEN** the `finally` block's `orch.stop()` still runs (cancelling early background jobs, closing the HTTP session) before the exception propagates out of `run_daemon`

#### Scenario: entry points call asyncio.run

- **WHEN** any of `daemonize`, `daemon_systemd`, `daemon_sysv` is inspected
- **THEN** the entry point is a synchronous `def` that calls `asyncio.run(run_daemon(...))`

### Requirement: Daemon and CLI exit-code contract

All six CLI commands and the three daemon launchers SHALL follow the uniform
exit-code contract:

- `0` — success (clean shutdown for daemons, completed operation for CLI
  commands), and `--help`.
- `1` — runtime error caught by the top-level `try/except Exception`; the entry
  point prints `Error: <exception>` to stderr and calls `sys.exit(1)`.
- `2` — argparse error (unknown flag, missing positional, invalid choice) or
  `existing_path` `ArgumentTypeError` (missing `--config` file). argparse and
  the type validator handle this natively; the `except Exception` block SHALL
  NOT catch `SystemExit` (which is not an `Exception` subclass), so argparse's
  exit propagates.

The daemon entry points SHALL wrap `make_daemon`, `Config.from_config_parser`,
and `asyncio.run(run_daemon(...))` in `try: ... except Exception as e:
print(f"Error: {e}", file=sys.stderr); sys.exit(1)`. A bare traceback without
an `Error:` message is a defect.

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

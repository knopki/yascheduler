## MODIFIED Requirements

### Requirement: Shared daemon core for entry points

The `yascheduler/entrypoints/cli/daemon_common.py` module SHALL provide the shared daemon
runtime consumed by all three daemon entry points (`daemonize`, `daemon_systemd`,
`daemon_sysv`):

- `configure_logger(log_file: str | Path | None, level: int) -> logging.Logger` — configures
  the **root** logger (NOT just `yascheduler` + 2 third-party loggers), so warnings from
  `aiohttp`, `pg8000`, and `asyncio` reach the log file:
  - Adds a `StreamHandler(sys.stderr)` to the root logger (always).
  - Adds a `FileHandler(log_file)` to the root logger (only when `log_file is not None`).
  - Sets the `backoff` and `asyncssh` loggers to `ERROR` (suppress retry/key-exchange noise)
    but lets them propagate to the root handlers.
  - Calls `logging.captureWarnings(True)` so `warnings.warn` reaches the root handlers.
  - SHALL NOT call `logging.basicConfig` (it would install an uncontrolled `StreamHandler`).
- `async def run_daemon(config: Config, logger: logging.Logger) -> None` — the async daemon
  core: `await make_daemon(config, logger)` to build the `Orchestrator`, register
  SIGTERM/SIGINT handlers on the running event loop (cancel outstanding tasks, sleep 250ms
  for SSL connections to close, log "Done"), and `await orch.start()`.

Each daemon entry point (`daemonize`, `daemon_systemd`, `daemon_sysv`) SHALL be a synchronous
`def` that builds its own argparse parser via the `args.py` helpers, calls
`configure_logger(args.log_file, level)`, loads `Config.from_config_parser(args.config)`, and
invokes `asyncio.run(run_daemon(config, logger))`.

The daemon entry points SHALL NOT register signal handlers themselves; `run_daemon` owns
signal registration because `loop.add_signal_handler` requires a running event loop.

#### Scenario: configure_logger writes to stderr when log_file is None
- **WHEN** `configure_logger(log_file=None, level=logging.INFO)` is called
- **THEN** the root logger has a `StreamHandler(sys.stderr)` and no `FileHandler`

#### Scenario: configure_logger writes to file and stderr when log_file is set
- **WHEN** `configure_logger(log_file="/tmp/y.log", level=logging.INFO)` is called
- **THEN** the root logger has both a `StreamHandler(sys.stderr)` and a `FileHandler` pointed at `/tmp/y.log`

#### Scenario: configure_logger suppresses backoff and asyncssh
- **WHEN** `configure_logger(log_file=None, level=logging.INFO)` is called
- **THEN** the `backoff` and `asyncssh` loggers have level `ERROR` (warnings below ERROR are not emitted)

#### Scenario: configure_logger does not call basicConfig
- **WHEN** `configure_logger(...)` is called
- **THEN** `logging.basicConfig` is not invoked; handlers are added explicitly to the root logger

#### Scenario: run_daemon is async
- **WHEN** `run_daemon` is inspected
- **THEN** it is declared `async def run_daemon(config, logger) -> None`

#### Scenario: run_daemon awaits make_daemon and orch.start
- **WHEN** `run_daemon(config, logger)` is awaited
- **THEN** `make_daemon(config, logger)` is awaited to build the `Orchestrator`, SIGTERM/SIGINT handlers are registered on the running event loop, and `orch.start()` is awaited

#### Scenario: run_daemon owns signal handlers
- **WHEN** a daemon entry point is invoked
- **THEN** the entry point does NOT call `loop.add_signal_handler`; `run_daemon` registers SIGTERM/SIGINT handlers after `make_daemon` returns

#### Scenario: entry points call asyncio.run
- **WHEN** any of `daemonize.py`, `daemon_systemd.py`, `daemon_sysv.py` is inspected
- **THEN** the entry point is a synchronous `def` that calls `asyncio.run(run_daemon(...))`

#### Scenario: configure_logger captures warnings
- **WHEN** `configure_logger(...)` is called
- **THEN** `logging.captureWarnings(True)` has been called, so `warnings.warn` records are routed through the root logger handlers

## MODIFIED Requirements

### Requirement: Shared daemon core for entry points

The system SHALL provide the shared daemon runtime consumed by all three daemon
entry points:

- `configure_logger(log_file: str | Path | None, level: int) -> logging.Logger`
  — configures the ROOT logger: always adds a `StreamHandler(sys.stderr)`, adds
  a `FileHandler(log_file)` only when `log_file is not None`, wires a `LogFormatter`
  onto both handlers so trace records and user-facing records render with their
  distinct layouts, sets `backoff` and `asyncssh` loggers to `ERROR`, and calls
  `logging.captureWarnings(True)`. SHALL NOT call `logging.basicConfig`.
- `async def run_daemon(config: Config, logger: logging.Logger) -> None` — the
  async daemon core: awaits `make_daemon(config, logger)` to build the
  `Orchestrator`, registers SIGTERM/SIGINT handlers on the running event loop
  (cancel outstanding tasks, sleep 250ms for SSL close, log "Done"), then
  awaits `orch.start()` wrapped in a `try/finally` whose `finally` clause awaits
  `orch.stop()`. Signal-handler registration lives in `run_daemon` (not the
  entry points) because `loop.add_signal_handler` requires a running loop.

Each daemon entry point SHALL be a synchronous `def` that builds its own
argparse parser via the shared helpers, calls `configure_logger`, loads
`Config.from_config_parser(args.config)`, and invokes
`asyncio.run(run_daemon(config, logger))`. The entry points SHALL NOT register
signal handlers themselves.

#### Scenario: configure_logger writes to stderr when log_file is None
- **WHEN** `configure_logger(log_file=None, level=logging.INFO)` is called
- **THEN** the root logger has a `StreamHandler(sys.stderr)` and no `FileHandler`
- **AND** the `StreamHandler` is configured with a `LogFormatter`

#### Scenario: configure_logger writes to file and stderr when log_file is set
- **WHEN** `configure_logger(log_file="/tmp/y.log", level=logging.INFO)` is called
- **THEN** the root logger has both a `StreamHandler(sys.stderr)` and a `FileHandler` pointed at `/tmp/y.log`
- **AND** both handlers are configured with a `LogFormatter` (single formatter, no per-handler format variants)

#### Scenario: configure_logger does not call basicConfig
- **WHEN** `configure_logger(...)` is invoked
- **THEN** `logging.basicConfig` is NOT called (handlers and level are set explicitly)

#### Scenario: run_daemon is async
- **WHEN** `run_daemon` is inspected
- **THEN** it is declared `async def run_daemon(config, logger) -> None`

#### Scenario: run_daemon awaits make_daemon and orch.start
- **WHEN** `run_daemon(config, logger)` is awaited
- **THEN** `make_daemon(config, logger)` is awaited, SIGTERM/SIGINT handlers are registered on the running event loop, `orch.start()` is awaited, and the `finally` block awaits `orch.stop()`

#### Scenario: start() exception propagates after cleanup
- **WHEN** `orch.start()` raises an exception
- **THEN** the `finally` block's `orch.stop()` still runs (cancelling early background jobs, closing the HTTP session) before the exception propagates out of `run_daemon`

#### Scenario: entry points call asyncio.run
- **WHEN** any of `daemonize`, `daemon_systemd`, `daemon_sysv` is inspected
- **THEN** the entry point is a synchronous `def` that calls `asyncio.run(run_daemon(...))`
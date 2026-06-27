# Daemon Common

## Purpose

Define the shared daemon runtime consumed by all three daemon entry points
(`daemonize`, `daemon_systemd`, `daemon_sysv`): logger configuration and the
async daemon core that integrates `make_daemon`, signal handling, and
orchestrator startup.

## Requirements

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
  for SSL connections to close, log "Done"), and `await orch.start()`. The signal-handling
  body SHALL move verbatim from the former `daemonize.py`; only its call site moves.

Each daemon entry point (`daemonize`, `daemon_systemd`, `daemon_sysv`) SHALL be a synchronous
`def` that builds its own argparse parser via the `args.py` helpers, calls
`configure_logger(args.log_file, level)`, loads `Config.from_config_parser(args.config)`, and
invokes `asyncio.run(run_daemon(config, logger))`. The entry points SHALL NOT use `@to_sync`
(the thread-offload branch never fires for console_scripts; `asyncio.run` is explicit and
matches the five CLI commands' shape).

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

#### Scenario: entry points call asyncio.run, not @to_sync
- **WHEN** any of `daemonize.py`, `daemon_systemd.py`, `daemon_sysv.py` is inspected
- **THEN** the entry point is a synchronous `def` that calls `asyncio.run(run_daemon(...))`; `@to_sync` is not used

#### Scenario: configure_logger captures warnings
- **WHEN** `configure_logger(...)` is called
- **THEN** `logging.captureWarnings(True)` has been called, so `warnings.warn` records are routed through the root logger handlers

### Requirement: Daemon shutdown cleanup guarantee

`run_daemon` (`yascheduler/entrypoints/cli/daemon_common.py`) SHALL guarantee that the cleanup body of `orch.stop()` executes exactly once on every exit path: normal return of `orch.start()`, an exception raised by `orch.start()`, or a signal-driven shutdown where the SIGTERM/SIGINT handler calls `orch.stop()` first and the subsequent `finally` block calls it again as a no-op. The `orch.stop()` function itself may be called more than once (e.g. signal handler then `finally`), but only the first call executes the cleanup body; subsequent calls return immediately as a no-op per the `orchestrator` capability's idempotency requirement.

The `await orch.start()` call SHALL be wrapped in a `try/finally` block whose `finally` clause awaits `orch.stop()`. The signal-handling registration (SIGTERM/SIGINT) SHALL remain unchanged and SHALL still call `orch.stop()` from the handler; the `finally` is the safety net for the non-signal exit paths.

`run_daemon` SHALL NOT swallow exceptions from `orch.start()`: a `start()` exception SHALL propagate out of `run_daemon` after the `finally` cleanup runs (re-raising is the default `try/finally` behavior; no `except` clause is added).

#### Scenario: start() returns normally triggers cleanup
- **WHEN** `orch.start()` returns normally (e.g. every background job terminated with a non-`CancelledError` exception and `_shutdown_barrier`'s `gather(..., return_exceptions=True)` completed)
- **THEN** the `finally` block awaits `orch.stop()`, which closes SSH connections, the HTTP session, and cloud clients, and `run_daemon` returns cleanly without leaking resources

#### Scenario: start() raises triggers cleanup
- **WHEN** `orch.start()` raises an exception
- **THEN** the `finally` block awaits `orch.stop()` (cancelling any early background jobs already added to `_bg_jobs`) before the exception propagates out of `run_daemon`

#### Scenario: signal handler runs stop() then finally is a no-op
- **WHEN** a SIGTERM/SIGINT is received while `orch.start()` is running and the signal handler calls `orch.stop()` (first execution, body runs)
- **THEN** `orch.start()` subsequently returns, the `finally` block awaits `orch.stop()` again, and the second invocation is a no-op (no double close of the HTTP session, no double disconnect) because `Orchestrator.stop()` is idempotent per the `orchestrator` capability

#### Scenario: make_daemon succeeds and start() raises still cleans up early jobs
- **WHEN** `make_daemon` returns an `Orchestrator` with an open `http_session` and `orch.start()` raises after adding only some background jobs (e.g. `_print_stats` and the connect-machine coordinator) to `_bg_jobs`
- **THEN** the `finally` block's `orch.stop()` cancels those early jobs and closes the `http_session` that `make_daemon` created, preventing a leak of the early jobs and the HTTP session

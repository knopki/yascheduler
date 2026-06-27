# FILE: yascheduler/entrypoints/cli/daemon_common.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Shared daemon core — configure_logger and run_daemon, consumed by all three daemon entry points (daemonize, daemon_systemd, daemon_sysv).
#   SCOPE: Root-logger configuration (StreamHandler→stderr always + FileHandler when set; backoff/asyncssh suppressed; captureWarnings) and the async daemon runtime (make_daemon + SIGTERM/SIGINT handlers + `try/finally`-wrapped `orch.start()` guaranteeing `orch.stop()` runs on any exit path — normal start return, start exception, or signal-driven shutdown where the handler's `stop()` runs first and the `finally`'s `stop()` is an idempotent no-op).
#   DEPENDS: M-DI, M-ENTRYPOINTS-CONFIG-PARSER, M-APPLICATION-ORCHESTRATOR
#   LINKS: M-DAEMON-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   configure_logger - Configure the ROOT logger: stderr StreamHandler always + FileHandler when log_file set; backoff/asyncssh → ERROR; captureWarnings(True); NO basicConfig.
#   run_daemon - Async daemon core: await make_daemon, register SIGTERM/SIGINT handlers on the running loop, await orch.start() under try/finally so orch.stop() runs on every exit path.
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - run_daemon wraps `await orch.start()` in `try/finally: await orch.stop()` so cleanup runs on every exit path (normal start return, start exception, signal). The signal handler's `stop()` is the first execution; the `finally`'s `stop()` is an idempotent no-op per the Orchestrator contract (fix-daemon-resource-leak-on-start-return).
#   PREVIOUS_CHANGE: v1.0.1 - post-review fix: signal-handler closure now binds `sig` by value via a factory (was a bare closure suppressed by bugbear B023; both handlers dispatched SIGINT because the loop variable was captured by reference).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING, Any

from yascheduler.entrypoints import make_daemon

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from yascheduler.application import Orchestrator
    from yascheduler.entrypoints import Config


# START_CONTRACT: configure_logger
#   PURPOSE: Configure the ROOT logger so warnings from aiohttp/pg8000/asyncio reach the log file (not just yascheduler + 2 third-party loggers).
#   INPUTS: { log_file: str | Path | None - log file path or None (stderr only), level: int - root logger level (e.g. logging.INFO) }
#   OUTPUTS: { logging.Logger - the configured root logger }
#   SIDE_EFFECTS: Adds a StreamHandler(sys.stderr) to the root logger (always); adds a FileHandler(log_file) to the root logger when log_file is not None; sets the backoff and asyncssh loggers to ERROR (suppress retry/key-exchange noise) but lets them propagate to the root handlers; calls logging.captureWarnings(True); does NOT call logging.basicConfig.
#   LINKS: M-DAEMON-COMMON
# END_CONTRACT: configure_logger
def configure_logger(log_file: str | Path | None, level: int) -> logging.Logger:
    # START_BLOCK_ROOT_HANDLERS
    root = logging.getLogger()
    root.setLevel(level)
    # Always log to stderr; systemd captures it into journald, sysv uses the file below.
    root.addHandler(logging.StreamHandler(sys.stderr))
    if log_file is not None:
        root.addHandler(logging.FileHandler(log_file))
    # END_BLOCK_ROOT_HANDLERS

    # START_BLOCK_SUPPRESS_NOISY_THIRD_PARTY
    # backoff retries and asyncssh key-exchange chatter are noisy below ERROR; let them
    # propagate to the root handlers but suppress their DEBUG/INFO/WARNING output.
    logging.getLogger("backoff").setLevel(logging.ERROR)
    logging.getLogger("asyncssh").setLevel(logging.ERROR)
    # END_BLOCK_SUPPRESS_NOISY_THIRD_PARTY

    # START_BLOCK_CAPTURE_WARNINGS
    logging.captureWarnings(True)
    # END_BLOCK_CAPTURE_WARNINGS

    return root


# START_CONTRACT: run_daemon
#   PURPOSE: Async daemon core — build the Orchestrator via make_daemon, register SIGTERM/SIGINT handlers on the running loop, and start the orchestrator.
#   INPUTS: { config: Config - daemon configuration, logger: logging.Logger - root logger for signal-handler messages }
#   OUTPUTS: { None - runs the event loop until stopped }
#   SIDE_EFFECTS: Awaits make_daemon(config, logger) to build the Orchestrator; registers SIGTERM/SIGINT handlers on the running event loop (cancel outstanding tasks, sleep 250ms for SSL connections to close, log "Done"); awaits orch.start(); guarantees `orch.stop()` runs on any exit path (normal `start()` return, `start()` exception, signal) via `try/finally` — the signal handler's `stop()` is the first execution; the `finally`'s `stop()` is a no-op (idempotent per the orchestrator contract).
#   LINKS: M-DAEMON-COMMON, M-DI, M-APPLICATION-ORCHESTRATOR
# END_CONTRACT: run_daemon
async def run_daemon(config: Config, logger: logging.Logger) -> None:
    # START_BUILD_ORCHESTRATOR
    orch = await make_daemon(config, logger)
    # END_BUILD_ORCHESTRATOR

    # START_BLOCK_REGISTER_SIGNAL_HANDLERS
    loop = asyncio.get_running_loop()
    current_task = asyncio.current_task()
    shielded: Sequence[asyncio.Task[Any]] = (
        [current_task] if current_task is not None else []
    )

    async def on_signal(
        orch: Orchestrator,
        shield: Sequence[asyncio.Task[Any]],
        sig: signal.Signals,
    ) -> None:
        signame = signal.strsignal(sig)
        logger.info(f"Received signal {signame}")
        if sig in [signal.SIGTERM, signal.SIGINT]:
            await orch.stop()
            shielded_tasks = [*shield, asyncio.current_task()]
            tasks = [t for t in asyncio.all_tasks() if t not in shielded_tasks]
            logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Wait 250 ms for the underlying SSL connections to close.
            await asyncio.sleep(0.25)
            logger.info("Done")

    for sig in [signal.SIGTERM, signal.SIGINT]:
        # Build the handler in a factory so `sig` binds by value; a bare closure
        # would capture the loop variable by reference, dispatching the final
        # value (SIGINT) for both signals when fired.
        def _make_handler(sig: signal.Signals) -> Callable[[], asyncio.Task[Any]]:
            def handler() -> asyncio.Task[Any]:
                task = on_signal(orch, shielded, sig)
                return asyncio.create_task(task)

            return handler

        loop.add_signal_handler(sig, _make_handler(sig))
    # END_BLOCK_REGISTER_SIGNAL_HANDLERS

    # START_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP
    try:
        await orch.start()
    finally:
        await orch.stop()
    # END_BLOCK_RUN_ORCHESTRATOR_WITH_CLEANUP

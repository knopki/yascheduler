"""Shared daemon core — configure_logger and run_daemon, consumed by all three daemon entry points (daemonize, daemon_systemd, daemon_sysv)."""
# region MODULE_CONTRACT
# PURPOSE: Abstract the async daemon lifecycle — logger setup, orchestrator startup, signal handling, and cleanup — into a single shared core so all three daemon launchers  behave identically and reliably.
# SCOPE: Root-logger configuration and async daemon core lifecycle — orchestrator startup, signal handling, and cleanup.
# KEYWORDS: daemon, logger, signal, orchestration, common
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING, Any

from yascheduler.entrypoints import make_daemon
from yascheduler.shared import LogFormatter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from yascheduler.application import Orchestrator
    from yascheduler.entrypoints import Config


# region FUNC_configure_logger
# PURPOSE: Configure the ROOT logger so warnings from aiohttp/pg8000/asyncio reach the log file.
# INVARIANTS:
# - Configures ROOT logger, not yascheduler.
# - Always adds StreamHandler(sys.stderr).
# - Adds FileHandler(log_file) only when log_file is not None.
# - Both handlers share a single LogFormatter instance.
def configure_logger(log_file: str | Path | None, level: int) -> logging.Logger:
    """Configure the ROOT logger so warnings from aiohttp/pg8000/asyncio reach the log file (not just yascheduler + 2 third-party loggers)."""
    # region BLOCK_root_handlers
    root = logging.getLogger()
    root.setLevel(level)
    # Always log to stderr; systemd captures it into journald, sysv uses the file below.
    formatter = LogFormatter()
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    root.addHandler(sh)
    if log_file is not None:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(formatter)
        root.addHandler(fh)
    # endregion BLOCK_root_handlers

    # region BLOCK_suppress_noisy_third_party
    # asyncssh key-exchange chatter is noisy below ERROR; let it
    # propagate to the root handlers but suppress its DEBUG/INFO/WARNING output.
    logging.getLogger("asyncssh").setLevel(logging.ERROR)
    # endregion BLOCK_suppress_noisy_third_party

    # region BLOCK_capture_warnings
    logging.captureWarnings(True)
    # endregion BLOCK_capture_warnings

    return root


# endregion FUNC_configure_logger


# region FUNC_run_daemon
# PURPOSE: Async daemon core — build the Orchestrator via make_daemon, register SIGTERM/SIGINT handlers on the running loop, and start the orchestrator.
# INVARIANTS:
# - orch.start() is inside try whose finally always awaits orch.stop().
async def run_daemon(config: Config, logger: logging.Logger) -> None:
    """Async daemon core — build the Orchestrator via make_daemon, register SIGTERM/SIGINT handlers on the running loop, and start the orchestrator."""
    # region BLOCK_build_orchestrator
    orch = await make_daemon(config)
    # endregion BLOCK_build_orchestrator

    # region BLOCK_register_signal_handlers
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
        logger.info("Received signal %s", signame)
        if sig in [signal.SIGTERM, signal.SIGINT]:
            await orch.stop()
            shielded_tasks = [*shield, asyncio.current_task()]
            tasks = [t for t in asyncio.all_tasks() if t not in shielded_tasks]
            logger.info("Cancelling %d outstanding tasks", len(tasks))
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
    # endregion BLOCK_register_signal_handlers

    # region BLOCK_run_orchestrator_with_cleanup
    try:
        await orch.start()
    finally:
        await orch.stop()
    # endregion BLOCK_run_orchestrator_with_cleanup


# endregion FUNC_run_daemon

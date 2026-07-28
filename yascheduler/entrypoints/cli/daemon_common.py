"""Shared daemon core — run_daemon, consumed by daemon entry points."""
# region MODULE_CONTRACT
# PURPOSE: Abstract the async daemon lifecycle into a single shared core so all daemon launchers behave identically and reliably.
# SCOPE: Async daemon core lifecycle — orchestrator startup, signal handling, and cleanup.
# KEYWORDS: daemon, signal, orchestration, common
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING, Any

from yascheduler.entrypoints import make_daemon

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Sequence

    from yascheduler.application import Orchestrator
    from yascheduler.entrypoints import Config

__all__ = ["run_daemon"]


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

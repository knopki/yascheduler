# FILE: yascheduler/adapters/cli/daemonize.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: yascheduler CLI command — start the daemon with signal handling.
#   SCOPE: daemonize command — creates Orchestrator via DI, runs event loop.
#   DEPENDS: M-DI, M-CONFIG, M-VARIABLES, M-APPLICATION-ORCHESTRATOR
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   daemonize - Start yascheduler daemon via make_daemon()
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from adapters/cli/commands.py per-command split.
# END_CHANGE_SUMMARY

import argparse
import asyncio
import logging
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional, Union

from yascheduler.application.orchestrator import Orchestrator
from yascheduler.client import to_sync
from yascheduler.config import Config
from yascheduler.di import make_daemon
from yascheduler.variables import CONFIG_FILE


# START_CONTRACT: daemonize
#   PURPOSE: Start the yascheduler daemon with signal handling via make_daemon
#   INPUTS: { log_file: Optional[Union[str, Path]] - path to log file, or None }
#   OUTPUTS: { None - runs the event loop until stopped }
#   SIDE_EFFECTS: Creates Orchestrator via DI, sets up signal handlers, runs event loop
#   LINKS: M-CLI-COMMANDS, M-DI
# END_CONTRACT: daemonize
def daemonize(log_file: Optional[Union[str, Path]] = None) -> None:
    from yascheduler.scheduler import get_logger

    parser = argparse.ArgumentParser(description="Start yascheduler daemon")
    parser.add_argument(
        "-l",
        "--log-level",
        default="INFO",
        help="set log level",
        choices=logging._levelToName.values(),
    )
    args = parser.parse_args()

    logger = get_logger(log_file, level=logging._nameToLevel[args.log_level])
    config = Config.from_config_parser(CONFIG_FILE)

    async def on_signal(
        orch: Orchestrator, shield: Sequence[asyncio.Task], sig: signal.Signals
    ) -> None:
        signame = signal.strsignal(sig)
        logger.info(f"Received signal {signame}")
        if sig in [signal.SIGTERM, signal.SIGINT]:
            await orch.stop()
            shielded = [*shield, asyncio.current_task()]
            tasks = [t for t in asyncio.all_tasks() if t not in shielded]
            logger.info(f"Cancelling {len(tasks)} outstanding tasks")
            [task.cancel() for task in tasks]
            await asyncio.gather(*tasks, return_exceptions=True)
            # Wait 250 ms for the underlying SSL connections to close
            await asyncio.sleep(0.25)
            logger.info("Done")

    async def run() -> None:
        orch = await make_daemon(config, logger)

        loop = asyncio.get_running_loop()
        current_task = asyncio.current_task()

        shielded = [current_task] if current_task else []
        for sig in [signal.SIGTERM, signal.SIGINT]:

            def handler() -> asyncio.Task[Any]:
                task = on_signal(orch, shielded, sig)  # noqa: B023
                return asyncio.create_task(task)

            loop.add_signal_handler(sig, handler)

        await orch.start()

    to_sync(run)()

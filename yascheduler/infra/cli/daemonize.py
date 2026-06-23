# FILE: yascheduler/infra/cli/daemonize.py
# VERSION: 1.1.2
# START_MODULE_CONTRACT
#   PURPOSE: yascheduler CLI command — start the daemon with signal handling.
#   SCOPE: daemonize command — creates Orchestrator via DI, runs event loop, configures yascheduler logger.
#   DEPENDS: M-DI, M-CONFIG, M-SHARED, M-APPLICATION-ORCHESTRATOR
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   daemonize - Start yascheduler daemon via make_daemon()
#   _get_logger - Configure and return the yascheduler logger (inlined from scheduler.py)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.2 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.1.1 - Import to_sync/CONFIG_FILE from yascheduler.shared facade (shared-kernel-extraction).
# END_CHANGE_SUMMARY
# FIXME: split adapter and application layer (business logic)

import argparse
import asyncio
import logging
import signal
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional, Union

from yascheduler.application import Orchestrator
from yascheduler.config import Config
from yascheduler.di import make_daemon
from yascheduler.shared import CONFIG_FILE, to_sync


# START_CONTRACT: _get_logger
#   PURPOSE: Configure and return the yascheduler logger (inlined from scheduler.py)
#   INPUTS: { log_file: Optional[Union[str, Path]] - path to log file, or None; level: int - log level (default INFO) }
#   OUTPUTS: { logging.Logger - the configured yascheduler logger }
#   SIDE_EFFECTS: Sets basicConfig, captureWarnings, and configures backoff/asyncssh log levels.
#   LINKS: none
# END_CONTRACT: _get_logger
def _get_logger(
    log_file: Optional[Union[str, Path]] = None, level: int = logging.INFO
) -> logging.Logger:
    logging.basicConfig(level=logging.INFO)
    logging.captureWarnings(True)
    logger = logging.getLogger("yascheduler")
    logger.setLevel(level)

    third_party_level = logging.ERROR if level >= logging.INFO else logging.DEBUG

    backoff_logger = logging.getLogger("backoff")
    backoff_logger.setLevel(third_party_level)

    asyncssh_logger = logging.getLogger("asyncssh")
    asyncssh_logger.setLevel(third_party_level)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        backoff_logger.addHandler(fh)
        asyncssh_logger.addHandler(fh)

    return logger


# START_CONTRACT: daemonize
#   PURPOSE: Start the yascheduler daemon with signal handling via make_daemon
#   INPUTS: { log_file: Optional[Union[str, Path]] - path to log file, or None }
#   OUTPUTS: { None - runs the event loop until stopped }
#   SIDE_EFFECTS: Creates Orchestrator via DI, sets up signal handlers, runs event loop
#   LINKS: M-CLI-COMMANDS, M-DI
# END_CONTRACT: daemonize
def daemonize(log_file: Optional[Union[str, Path]] = None) -> None:
    parser = argparse.ArgumentParser(description="Start yascheduler daemon")
    parser.add_argument(
        "-l",
        "--log-level",
        default="INFO",
        help="set log level",
        choices=logging._levelToName.values(),
    )
    args = parser.parse_args()

    logger = _get_logger(log_file, level=logging._nameToLevel[args.log_level])
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

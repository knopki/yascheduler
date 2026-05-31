#!/usr/bin/env python
# FILE: yascheduler/scheduler.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Backward-compatible Scheduler wrapper delegating to Orchestrator and use cases.
#   SCOPE: Scheduler class (thin wrapper), get_logger, WebhookPayload.
#   DEPENDS: M-DB, M-CLOUD-MANAGER, M-CONFIG, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-SUBMIT, M-DI, M-WEBHOOK
#   LINKS: M-DB, M-APPLICATION-ORCHESTRATOR, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Scheduler - Backward-compatible async daemon wrapper (delegates to Orchestrator)
#   WebhookPayload - Re-exported from webhook module
#   get_logger - Configure and return the yascheduler logger
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.2 - Extract WebhookPayload to webhook.py; replace attrs with dataclasses.
#   PREVIOUS_CHANGE: v2.0.0 - Refactor: delegate all loop infrastructure to Orchestrator, submit to use case.
# END_CHANGE_SUMMARY


import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional, Union

from attrs import define, field

from .clouds import CloudAPIManager
from .compat import Self
from .config import Config
from .db import DB, TaskModel
from .di import make_cli_deps, make_daemon
from .application.orchestrator import Orchestrator
from .application.submit_task import submit_task
from .variables import CONFIG_FILE
from .webhook import WebhookPayload as WebhookPayload  # noqa: F401 — re-export

logging.basicConfig(level=logging.INFO)


def get_logger(log_file: Optional[Union[str, Path]] = None, level: int = logging.INFO):
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


@define
class Scheduler:
    config: Config = field()
    db: DB = field()
    clouds: CloudAPIManager = field()
    log: logging.Logger = field()
    _orchestrator: Orchestrator | None = field(default=None, init=False)

    # START_CONTRACT: create
    #   PURPOSE: Async factory: build Scheduler with DB, clouds, and Orchestrator.
    #   INPUTS: { config: Optional[Config], log: Optional[logging.Logger] }
    #   OUTPUTS: { Self - fully initialized Scheduler instance }
    #   SIDE_EFFECTS: Creates DB connection, initialises CloudAPIManager.
    #   LINKS: M-DB, M-CLOUD-MANAGER, M-CONFIG, M-DI
    # END_CONTRACT: create
    @classmethod
    async def create(
        cls,
        config: Optional[Config] = None,
        log: Optional[logging.Logger] = None,
    ) -> Self:
        if log:
            log = log.getChild(cls.__name__)
        else:
            log = logging.getLogger(cls.__name__)
        cfg = config or Config.from_config_parser(CONFIG_FILE)
        db = await DB.create(cfg.db)
        clouds = await CloudAPIManager.create(
            db=db,
            local_config=cfg.local,
            remote_config=cfg.remote,
            cloud_configs=cfg.clouds,
            engines=cfg.engines,
            log=log,
        )
        return cls(
            config=cfg,
            db=db,
            clouds=clouds,
            log=log,
        )

    # START_CONTRACT: create_new_task
    #   PURPOSE: Insert a new TO_DO task via the submit_task use case.
    #   INPUTS: { label, metadata, engine_name, webhook_onsubmit }
    #   OUTPUTS: { TaskModel - the created task record }
    #   SIDE_EFFECTS: Creates task in database via use case.
    #   LINKS: M-APPLICATION-SUBMIT
    # END_CONTRACT: create_new_task
    async def create_new_task(
        self,
        label: str,
        metadata: Mapping[str, Any],
        engine_name: str,
        webhook_onsubmit: bool = False,
    ) -> TaskModel:

        # Use submit_task use case via DI
        cli_deps = make_cli_deps(self.config)
        task_id = await submit_task(
            label=label,
            metadata=metadata,
            engine_name=engine_name,
            engines=cli_deps.engines,
            uow_factory=cli_deps.uow_factory,
            remote_tasks_dir=cli_deps.remote_tasks_dir,
        )

        # Backward compat: return TaskModel from legacy DB
        task = await self.db.get_task(task_id)
        assert task is not None
        return task

    # START_CONTRACT: start
    #   PURPOSE: Start the daemon via Orchestrator.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Creates and starts Orchestrator with all producer-consumer loops.
    #   LINKS: M-APPLICATION-ORCHESTRATOR, M-DI
    # END_CONTRACT: start
    async def start(self):
        self._orchestrator = await make_daemon(
            self.config, self.log, db=self.db, clouds=self.clouds
        )
        await self._orchestrator.start()

    # START_CONTRACT: stop
    #   PURPOSE: Graceful shutdown via Orchestrator.
    #   INPUTS: { None }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Cancels all loops, disconnects machines, stops clouds.
    #   LINKS: M-APPLICATION-ORCHESTRATOR
    # END_CONTRACT: stop
    async def stop(self):
        if self._orchestrator:
            await self._orchestrator.stop()
        else:
            await self.clouds.stop()
            await self.db.close()

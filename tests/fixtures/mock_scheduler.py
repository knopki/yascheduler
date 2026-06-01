# FILE: tests/fixtures/mock_scheduler.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Scheduler constructor helper and inline-INI config parser for scheduler unit tests.
#   SCOPE: make_scheduler function constructing Scheduler with injected mocks; create_test_config parsing INI string into Config.
#   DEPENDS: M-SCHEDULER, M-CONFIG-HUB
#   LINKS: M-SCHEDULER, M-CONFIG-HUB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_scheduler - Construct a Scheduler with injected db, config, clouds, remote_machines
#   create_test_config - Parse inline INI string into a Config object with default sections
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial scheduler mock fixture with inline config parser.
# END_CHANGE_SUMMARY
#

from __future__ import annotations

import io
import logging
from configparser import ConfigParser
from typing import TYPE_CHECKING, Any

from yascheduler.config import (
    Config,
    ConfigCloudAzure,
    ConfigCloudHetzner,
    ConfigCloudUpcloud,
    ConfigDb,
    ConfigLocal,
    ConfigRemote,
    EngineRepository,
)
from yascheduler.scheduler import Scheduler

if TYPE_CHECKING:
    from yascheduler.clouds.cloud_api_manager import CloudAPIManager
    from yascheduler.db import DB


def make_scheduler(
    db: DB,
    config: Config,
    clouds: CloudAPIManager | None = None,
    remote_machines: list[Any] | None = None,
) -> Scheduler:
    """Construct a refactored Scheduler with injected mocks.

    After refactoring, Scheduler no longer accepts remote_machines
    or manages queues directly. The orchestrator handles loop infrastructure.
    """
    log = logging.getLogger("test_scheduler")
    return Scheduler(
        config=config,
        db=db,
        clouds=clouds,  # type: ignore[arg-type]
        log=log,
    )


def create_test_config(ini_content: str) -> Config:
    """Parse an INI string into a Config object."""
    parser = ConfigParser()
    parser.read_file(io.StringIO(ini_content))
    for sec_name in ["db", "local", "remote", "clouds"]:
        if not parser.has_section(sec_name):
            parser.add_section(sec_name)
    local = ConfigLocal.from_config_parser_section(parser["local"])
    remote = ConfigRemote.from_config_parser_section(parser["remote"])
    cloud_prefixes = set(x.split("_")[0] for x in parser.options("clouds"))
    for prefix in cloud_prefixes:
        key = f"{prefix}_user"
        if key not in parser.options("clouds"):
            parser["clouds"][key] = remote.username
    cloud_variants = (ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud)
    return Config(
        db=ConfigDb.from_config_parser_section(parser["db"]),
        local=local,
        remote=remote,
        clouds=[
            x.from_config_parser_section(parser["clouds"])
            for x in cloud_variants
            if x.prefix in cloud_prefixes
        ],
        engines=EngineRepository.from_config_parser(parser, local.engines_dir),
    )

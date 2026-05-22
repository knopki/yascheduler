#!/usr/bin/env python3
# FILE: yascheduler/config/__init__.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Public re-exports from config submodules.
#   SCOPE: Re-exports Config, ConfigCloud*, ConfigDb, ConfigLocal, ConfigRemote,
#     Deploy, Engine, EngineRepository, LocalArchiveDeploy, LocalFilesDeploy,
#     RemoteArchiveDeploy.
#   DEPENDS: M-CONFIG, M-CONFIG-DB, M-CONFIG-LOCAL, M-CONFIG-REMOTE, M-CONFIG-CLOUD,
#     M-CONFIG-ENGINE, M-CONFIG-ENGINE-REPO
#   LINKS: M-CONFIG
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Config - application-wide configuration container
#   ConfigCloud - base cloud provider config
#   ConfigCloudAzure - Azure-specific cloud config
#   ConfigCloudHetzner - Hetzner-specific cloud config
#   ConfigCloudUpcloud - Upcloud-specific cloud config
#   ConfigDb - database connection config
#   ConfigLocal - local daemon settings
#   ConfigRemote - remote machine defaults
#   Deploy - deploy strategy base
#   Engine - engine config
#   EngineRepository - engine repository config
#   LocalArchiveDeploy - local archive deploy strategy
#   LocalFilesDeploy - local files deploy strategy
#   RemoteArchiveDeploy - remote archive deploy strategy
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Configuration module"""

from .cloud import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud
from .config import Config
from .db import ConfigDb
from .engine import (
    Deploy,
    Engine,
    LocalArchiveDeploy,
    LocalFilesDeploy,
    RemoteArchiveDeploy,
)
from .engine_repository import EngineRepository
from .local import ConfigLocal
from .remote import ConfigRemote

__all__ = [
    "Config",
    "ConfigCloud",
    "ConfigCloudAzure",
    "ConfigCloudHetzner",
    "ConfigCloudUpcloud",
    "ConfigDb",
    "ConfigLocal",
    "ConfigRemote",
    "Deploy",
    "Engine",
    "EngineRepository",
    "LocalArchiveDeploy",
    "LocalFilesDeploy",
    "RemoteArchiveDeploy",
]

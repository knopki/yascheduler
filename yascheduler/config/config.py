#!/usr/bin/env python3
# FILE: yascheduler/config/config.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Top-level configuration container aggregating all sub-configs.
#   SCOPE: Config frozen dataclass parsed from INI file, aggregates sub-configs.
#   DEPENDS: M-CONFIG-DB, M-CONFIG-LOCAL, M-CONFIG-REMOTE, M-CONFIG-CLOUD, M-CONFIG-ENGINE-REPO
#   LINKS: M-CONFIG-HUB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Config - Frozen config container parsed from INI file
#   Config.from_config_parser - Classmethod factory from INI file path or contents
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Main config module"""

from collections.abc import Sequence
from configparser import ConfigParser
from pathlib import PurePath
from typing import Union

from attrs import define, field, validators

from .cloud import ConfigCloud, ConfigCloudAzure, ConfigCloudHetzner, ConfigCloudUpcloud
from .db import ConfigDb
from .engine_repository import EngineRepository
from .local import ConfigLocal
from .remote import ConfigRemote


@define(frozen=True)
class Config:
    """Main config module"""

    db: ConfigDb = field(validator=[validators.instance_of(ConfigDb)])
    local: ConfigLocal = field(validator=[validators.instance_of(ConfigLocal)])
    remote: ConfigRemote = field(validator=[validators.instance_of(ConfigRemote)])
    clouds: Sequence[ConfigCloud]
    engines: EngineRepository = field(
        validator=[validators.instance_of(EngineRepository)]
    )

    # START_CONTRACT: from_config_parser
    #   PURPOSE: Parse config from INI file path or contents into a Config instance
    #   INPUTS: { files: Union[str, bytes, PurePath] - path or contents of INI config file }
    #   OUTPUTS: { Config - fully populated configuration object }
    #   SIDE_EFFECTS: Reads from filesystem when files is a path
    #   LINKS: M-CONFIG, M-CONFIG-DB, M-CONFIG-LOCAL, M-CONFIG-REMOTE, M-CONFIG-CLOUD, M-CONFIG-ENGINE-REPO
    # END_CONTRACT: from_config_parser
    @classmethod
    def from_config_parser(cls, files: Union[str, bytes, PurePath]) -> "Config":
        "Create Config from path or config file contents"
        config = ConfigParser()
        config.read(files)

        for sec_name in ["db", "local", "remote", "clouds"]:
            if not config.has_section(sec_name):
                config.add_section(sec_name)

        local = ConfigLocal.from_config_parser_section(config["local"])
        remote = ConfigRemote.from_config_parser_section(config["remote"])

        # config prefixes
        cloud_prefixes = set(map(lambda x: x.split("_")[0], config.options("clouds")))
        # inherit username
        for prefix in cloud_prefixes:
            key = f"{prefix}_user"
            if key not in config.options("clouds"):
                config["clouds"][key] = remote.username
        # available cloud config models
        cloud_variants = (
            ConfigCloudAzure,
            ConfigCloudHetzner,
            ConfigCloudUpcloud,
        )
        # intersection
        cloud_variants_match = filter(
            lambda x: x.prefix in cloud_prefixes, cloud_variants
        )
        # instantiate
        clouds = map(
            lambda x: x.from_config_parser_section(config["clouds"]),
            cloud_variants_match,
        )

        return cls(
            db=ConfigDb.from_config_parser_section(config["db"]),
            local=local,
            remote=remote,
            clouds=list(clouds),
            engines=EngineRepository.from_config_parser(config, local.engines_dir),
        )

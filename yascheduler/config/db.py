#!/usr/bin/env python3
# FILE: yascheduler/config/db.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Database connection configuration.
#   SCOPE: PostgreSQL connection parameters.
#   DEPENDS: M-CONFIG-UTILS
#   LINKS: M-CONFIG-DB
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ConfigDb - database connection config with user, password, database, host, port
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Database configuration"""

from collections.abc import Sequence
from configparser import SectionProxy

from attrs import define, fields

from .utils import make_default_field, warn_unknown_fields


@define(frozen=True)
class ConfigDb:
    """Database configuration"""

    user: str = make_default_field("yascheduler")
    password: str = make_default_field("password")
    database: str = make_default_field("database")
    host: str = make_default_field("localhost")
    port: int = make_default_field(5432)

    @classmethod
    def get_valid_config_parser_fields(cls) -> Sequence[str]:
        "Returns a list of valid config keys"
        return [f.name for f in fields(cls)]

    @classmethod
    def from_config_parser_section(cls, sec: SectionProxy) -> "ConfigDb":
        "Create config from config parser's section"
        warn_unknown_fields(cls.get_valid_config_parser_fields(), sec)
        return cls(
            sec.get("user"),  # type: ignore
            sec.get("password"),  # type: ignore
            sec.get("database"),  # type: ignore
            sec.get("host"),  # type: ignore
            sec.getint("port"),  # type: ignore
        )

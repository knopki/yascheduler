#!/usr/bin/env python3
# FILE: yascheduler/config/remote.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Remote machine defaults: data directories, SSH username, jump host.
#   SCOPE: Remote paths, SSH user, jump host.
#   DEPENDS: M-CONFIG-UTILS, M-COMPAT
#   LINKS: M-CONFIG-REMOTE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ConfigRemote - remote machine config with data paths, username, and jump host
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Remote configuration"""

from collections.abc import Sequence
from configparser import SectionProxy
from pathlib import PurePath
from typing import Optional

from attrs import define, field, fields

from ..compat import Self
from .utils import make_default_field, opt_str_val, warn_unknown_fields


@define(frozen=True)
class ConfigRemote:
    """Local configuration"""

    data_dir: PurePath = make_default_field(PurePath("./data"))
    tasks_dir: PurePath = make_default_field(PurePath("./data/tasks"))
    engines_dir: PurePath = make_default_field(PurePath("./data/engines"))
    username: str = make_default_field("root")
    jump_username: Optional[str] = field(default=None, validator=opt_str_val)
    jump_host: Optional[str] = field(default=None, validator=opt_str_val)

    @classmethod
    def get_valid_config_parser_fields(cls) -> Sequence[str]:
        "Returns a list of valid config keys"
        return [f.name for f in fields(cls)]

    # START_CONTRACT: from_config_parser_section
    #   PURPOSE: Create ConfigRemote instance from a config parser section
    #   INPUTS: { sec: SectionProxy - config parser section with remote config keys }
    #   OUTPUTS: { Self - remote machine configuration }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-REMOTE
    # END_CONTRACT: from_config_parser_section
    @classmethod
    def from_config_parser_section(cls, sec: SectionProxy) -> Self:
        "Create config from config parser's section"
        warn_unknown_fields(cls.get_valid_config_parser_fields(), sec)
        data_dir = PurePath(sec.get("data_dir", "./data"))
        return cls(
            data_dir=data_dir,
            engines_dir=PurePath(sec.get("engines_dir", str(data_dir / "engines"))),
            tasks_dir=PurePath(sec.get("tasks_dir", str(data_dir / "tasks"))),
            username=sec.get("user"),  # type: ignore
            jump_username=sec.get("jump_user", None),
            jump_host=sec.get("jump_host", None),
        )

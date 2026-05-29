#!/usr/bin/env python3
# FILE: yascheduler/config/local.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Local daemon settings: data paths, concurrency limits, webhook config, private key discovery.
#   SCOPE: Data paths, concurrency limits, webhook settings, private key discovery.
#   DEPENDS: M-CONFIG-UTILS
#   LINKS: M-SCHEDULER, M-CLOUD-API
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   ConfigLocal - local daemon config with data paths, webhook, and concurrency limits
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Local configuration"""

from collections.abc import Sequence
from configparser import SectionProxy
from pathlib import Path, PurePath
from typing import Optional

from attrs import define, field, fields, validators

from .utils import make_default_field, warn_unknown_fields


@define(frozen=True)
class ConfigLocal:
    """Local configuration"""

    data_dir: Path = make_default_field(Path("./data"))
    tasks_dir: Path = make_default_field(Path("./data/tasks"))
    engines_dir: Path = make_default_field(Path("./data/engines"))
    keys_dir: Path = make_default_field(Path("./data/keys"))
    webhook_url: Optional[str] = field(default=None)
    webhook_reqs_limit: int = make_default_field(5, extra_validators=[validators.ge(1)])
    conn_machine_limit: int = make_default_field(
        10, extra_validators=[validators.ge(1)]
    )
    conn_machine_pending: int = make_default_field(
        10, extra_validators=[validators.ge(1)]
    )
    allocate_limit: int = make_default_field(20, extra_validators=[validators.ge(1)])
    allocate_pending: int = make_default_field(1, extra_validators=[validators.ge(1)])
    consume_limit: int = make_default_field(20, extra_validators=[validators.ge(1)])
    consume_pending: int = make_default_field(1, extra_validators=[validators.ge(1)])
    deallocate_limit: int = make_default_field(5, extra_validators=[validators.ge(1)])
    deallocate_pending: int = make_default_field(1, extra_validators=[validators.ge(1)])

    # START_CONTRACT: get_private_keys
    #   PURPOSE: List private key file paths from the keys directory
    #   INPUTS: { None }
    #   OUTPUTS: { Sequence[PurePath] - list of private key file paths }
    #   SIDE_EFFECTS: None - reads filesystem
    #   LINKS: M-CONFIG-LOCAL
    # END_CONTRACT: get_private_keys
    def get_private_keys(self) -> Sequence[PurePath]:
        "List private key file paths"
        filepaths = filter(lambda x: x.is_file(), Path(self.keys_dir).iterdir())
        return list(filepaths)

    @classmethod
    def get_valid_config_parser_fields(cls) -> Sequence[str]:
        "Returns a list of valid config keys"
        return [f.name for f in fields(cls)]

    # START_CONTRACT: from_config_parser_section
    #   PURPOSE: Create ConfigLocal instance from a config parser section
    #   INPUTS: { sec: SectionProxy - config parser section with local config keys }
    #   OUTPUTS: { ConfigLocal - local daemon configuration }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-LOCAL
    # END_CONTRACT: from_config_parser_section
    @classmethod
    def from_config_parser_section(cls, sec: SectionProxy) -> "ConfigLocal":
        "Create config from config parser's section"

        warn_unknown_fields(cls.get_valid_config_parser_fields(), sec)

        data_dir = Path(sec.get("data_dir", "./data")).resolve()
        return ConfigLocal(
            data_dir,
            tasks_dir=Path(sec.get("tasks_dir", str(data_dir / "tasks"))).resolve(),
            engines_dir=Path(
                sec.get("engines_dir", str(data_dir / "engines"))
            ).resolve(),
            keys_dir=Path(sec.get("keys_dir", str(data_dir / "keys"))).resolve(),
            webhook_reqs_limit=sec.getint("webhook_reqs_limit"),  # type: ignore
            webhook_url=sec.get("webhook_url"),
            conn_machine_limit=sec.getint("conn_machine_limit"),  # type: ignore
            conn_machine_pending=sec.getint("conn_machine_pending"),  # type: ignore
            allocate_limit=sec.getint("allocate_limit"),  # type: ignore
            allocate_pending=sec.getint("allocate_pending"),  # type: ignore
            consume_limit=sec.getint("consume_limit"),  # type: ignore
            consume_pending=sec.getint("consume_pending"),  # type: ignore
            deallocate_limit=sec.getint("deallocate_limit"),  # type: ignore
            deallocate_pending=sec.getint("deallocate_pending"),  # type: ignore
        )

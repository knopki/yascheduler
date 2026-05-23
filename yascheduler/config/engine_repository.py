#!/usr/bin/env python3
# FILE: yascheduler/config/engine_repository.py
# VERSION: 1.6.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Immutable collection of engines with filtering by platform.
#   SCOPE: EngineRepository frozen dict with filter operations.
#   DEPENDS: M-CONFIG-ENGINE, M-COMPAT
#   LINKS: M-CONFIG-ENGINE-REPO
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   EngineRepository - Immutable repository of engines with filter and platform methods
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#
"""Repository for Engines"""

import json
from collections import UserDict
from collections.abc import Callable, Sequence
from configparser import ConfigParser
from itertools import chain
from pathlib import PurePath
from typing import Any

from attrs import asdict, define, field, validators

from ..compat import Self
from .engine import Engine


def _value_serializer(_: type, __: Any, value: Any) -> Any:
    "Serialize PurePath as string"
    if isinstance(value, PurePath):
        return str(value)
    return value


@define
class EngineRepository(UserDict[str, Engine]):
    """Repository of Engines"""

    engines_dir: PurePath = field()
    data: dict[str, Engine] = field(
        factory=dict,
        validator=[
            validators.deep_mapping(
                key_validator=validators.instance_of(str),
                value_validator=validators.instance_of(Engine),
            )
        ],
    )

    def __setitem__(self, _: str, __: Engine) -> None:
        raise NotImplementedError()

    def __delitem__(self, _: str) -> None:
        raise NotImplementedError()

    def __hash__(self) -> int:
        return hash(
            json.dumps(asdict(self, value_serializer=_value_serializer), sort_keys=True)
        )

    # START_CONTRACT: filter
    #   PURPOSE: Filter engines by predicate and return new repository
    #   INPUTS: { filter_func: Callable[[Engine], bool] - predicate function for filtering }
    #   OUTPUTS: { Self - new repository with matching engines only }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-ENGINE-REPO
    # END_CONTRACT: filter
    def filter(self, filter_func: Callable[[Engine], bool]) -> Self:
        "Filter Engines by callable and return new Repository"
        new_data = dict(filter(lambda x: filter_func(x[1]), self.data.items()))
        return self.__class__(
            data=new_data,
            engines_dir=self.engines_dir,
        )

    # START_CONTRACT: filter_platforms
    #   PURPOSE: Filter engines by supported platforms and return new repository
    #   INPUTS: { platforms: Sequence[str] - list of platform names to match against }
    #   OUTPUTS: { Self - new repository with engines supporting at least one given platform }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-ENGINE-REPO
    # END_CONTRACT: filter_platforms
    def filter_platforms(self, platforms: Sequence[str]) -> Self:
        "Filter Engines by platforms and return new Repository"
        return self.filter(lambda x: bool(set(x.platforms) & set(platforms)))

    def get_platform_packages(self) -> list[str]:
        "Collect all platform pacakges from engines"
        mapped = map(lambda x: x.platform_packages, self.values())
        return list(set(chain(*mapped)))

    # START_CONTRACT: from_config_parser
    #   PURPOSE: Parse all engine.* sections from an INI config into an EngineRepository
    #   INPUTS: { cfg: ConfigParser - parsed INI config, engines_dir: PurePath - engines directory path }
    #   OUTPUTS: { Self - repository populated with engines from config }
    #   SIDE_EFFECTS: None
    #   LINKS: M-CONFIG-ENGINE-REPO, M-CONFIG
    # END_CONTRACT: from_config_parser
    @classmethod
    def from_config_parser(cls, cfg: ConfigParser, engines_dir: PurePath) -> Self:
        "Create config from path or config file contents"
        snames = filter(lambda x: x.startswith("engine."), cfg.sections())
        data: dict[str, Engine] = {}
        for sname in snames:
            engine = Engine.from_config_parser_section(cfg[sname], engines_dir)
            data[engine.name] = engine
        return cls(engines_dir=engines_dir, data=data)

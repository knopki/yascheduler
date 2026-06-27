# FILE: yascheduler/domain/engine.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: Engine value object, EngineRepository collection, Deploy strategies as frozen stdlib dataclasses.
#   SCOPE: LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy, Deploy Union alias, Engine value object with validate_inputs, EngineRepository frozen collection with filter/filter_platforms/get_platform_packages.
#   DEPENDS: M-SHARED
#   LINKS: M-DOMAIN-MODEL, M-PLATFORM-LINUX, M-PLATFORM-WINDOWS, M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-CLOUD-PROVISIONER, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-SUBMIT, M-APPLICATION-ORCHESTRATOR, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   LocalFilesDeploy - Deploy local files configuration (frozen dataclass)
#   LocalArchiveDeploy - Deploy local archive configuration (frozen dataclass)
#   RemoteArchiveDeploy - Deploy remote archive configuration (frozen dataclass)
#   Deploy - Union type of all deploy configurations
#   Engine - Calculation engine value object with spawn command, platforms, deploy strategies, validate_inputs
#   EngineRepository - Frozen collection of engines with filter/filter_platforms/get_platform_packages
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Relocate Engine, Deploy*, EngineRepository from yascheduler.config to yascheduler.domain as frozen stdlib dataclasses; merge 7-field domain.model.Engine with 4 fields from config.Engine (deployable, platform_packages, check_cmd_code, sleep_interval); drop UserDict inheritance, __hash__, engines_dir; INI parsing moves to entrypoints.config_parser (engine-to-domain-frozen).
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import chain
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence, ValuesView
    from pathlib import PurePath

    from .model import TaskContext

from .exceptions import MissingInputFileError


@dataclass(frozen=True)
class LocalFilesDeploy:
    """Deploy local files configuration."""

    files: tuple[PurePath, ...] = ()


@dataclass(frozen=True)
class LocalArchiveDeploy:
    """Deploy local archive configuration."""

    file: PurePath


@dataclass(frozen=True)
class RemoteArchiveDeploy:
    """Deploy remote archive configuration."""

    url: str


Deploy = Union[
    LocalFilesDeploy,
    LocalArchiveDeploy,
    RemoteArchiveDeploy,
]


@dataclass(frozen=True)
class Engine:
    """Calculation engine specification with spawn command, platforms, deploy strategies."""

    name: str
    spawn: str
    input_files: tuple[str, ...] = ()
    output_files: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    check_cmd: str | None = None
    check_pname: str | None = None
    deployable: tuple[Deploy, ...] = ()
    platform_packages: tuple[str, ...] = ()
    check_cmd_code: int = 0
    sleep_interval: int = 10

    # START_CONTRACT: Engine.validate_inputs
    #   PURPOSE: Validate that all required input files exist in the task context.
    #   INPUTS: { ctx: TaskContext - Task metadata containing input file data in ctx.extra }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None
    #   RAISES: MissingInputFileError - if any input_file is missing from ctx.extra
    #   LINKS: M-DOMAIN-EXCEPTIONS: MissingInputFileError
    # END_CONTRACT: Engine.validate_inputs
    def validate_inputs(self, ctx: TaskContext) -> None:
        """Verify all required engine input files exist in the task context."""
        for filename in self.input_files:
            if filename not in ctx.extra:
                raise MissingInputFileError(self.name, filename)


@dataclass(frozen=True)
class EngineRepository:
    """Frozen collection of engines keyed by name.

    Replaces the former config.EngineRepository (UserDict with neutralized
    mutators + unused __hash__ + engines_dir). The target surface is the 7
    methods below; UserDict-inherited methods (items, keys, __len__, __iter__)
    are intentionally NOT carried over.
    """

    data: Mapping[str, Engine] = field(default_factory=dict)

    def get(self, name: str) -> Engine | None:
        return self.data.get(name)

    def __getitem__(self, name: str) -> Engine:
        return self.data[name]

    def __contains__(self, name: object) -> bool:
        return name in self.data

    def values(self) -> ValuesView[Engine]:
        return self.data.values()

    # START_CONTRACT: EngineRepository.filter
    #   PURPOSE: Filter engines by predicate and return a new frozen repository.
    #   INPUTS: { fn: Callable[[Engine], bool] - predicate function for filtering }
    #   OUTPUTS: { EngineRepository - new repository with matching engines only }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-ENGINE
    # END_CONTRACT: EngineRepository.filter
    def filter(self, fn: Callable[[Engine], bool]) -> EngineRepository:
        return EngineRepository(data={k: v for k, v in self.data.items() if fn(v)})

    # START_CONTRACT: EngineRepository.filter_platforms
    #   PURPOSE: Filter engines by supported platforms and return a new frozen repository.
    #   INPUTS: { platforms: Sequence[str] - list of platform names to match against }
    #   OUTPUTS: { EngineRepository - new repository with engines supporting at least one given platform }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-ENGINE
    # END_CONTRACT: EngineRepository.filter_platforms
    def filter_platforms(self, platforms: Sequence[str]) -> EngineRepository:
        return self.filter(lambda e: bool(set(e.platforms) & set(platforms)))

    # START_CONTRACT: EngineRepository.get_platform_packages
    #   PURPOSE: Collect the unique union of platform_packages across all engines.
    #   INPUTS: { None }
    #   OUTPUTS: { list[str] - unique platform packages (order-independent) }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-ENGINE
    # END_CONTRACT: EngineRepository.get_platform_packages
    def get_platform_packages(self) -> list[str]:
        mapped = map(lambda e: e.platform_packages, self.values())
        return list(set(chain(*mapped)))

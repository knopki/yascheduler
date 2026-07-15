"""Define calculation engine value objects and deploy strategy types."""
# FILE: yascheduler/domain/engine.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Define calculation engine value objects and deploy strategy types.
#   SCOPE: Engine types (Engine value object, EngineRepository collection, Deploy strategy types) and their contracts.
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
#   LAST_CHANGE: v1.1.0 - Engine.validate_inputs takes extra: Mapping[str, object] (was ctx: TaskContext); reads the task's extra dict directly.
#   PREVIOUS_CHANGE: v1.0.0 - Relocate Engine, Deploy*, EngineRepository from yascheduler.config to yascheduler.domain as frozen stdlib dataclasses; merge 7-field domain.model.Engine with 4 fields from config.Engine; drop UserDict inheritance, __hash__, engines_dir; INI parsing moves to entrypoints.config_parser.
# END_CHANGE_SUMMARY

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import chain
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence, ValuesView
    from pathlib import PurePath

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
    #   PURPOSE: Validate that all required input files exist in the task extra payload.
    #   INPUTS: { extra: Mapping[str, object] - the task's extra dict (input-file payloads, file names as keys) }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None
    #   RAISES: MissingInputFileError - if any input_file is missing from extra
    #   LINKS: M-DOMAIN-EXCEPTIONS: MissingInputFileError
    # END_CONTRACT: Engine.validate_inputs
    def validate_inputs(self, extra: Mapping[str, object]) -> None:
        """Verify all required engine input files exist in the task extra payload."""
        for filename in self.input_files:
            if filename not in extra:
                raise MissingInputFileError(self.name, filename)


@dataclass(frozen=True)
class EngineRepository:
    """Frozen collection of engines keyed by name.

    Exposes get, __getitem__, __contains__, values, filter,
    filter_platforms, and get_platform_packages.
    """

    data: Mapping[str, Engine] = field(default_factory=dict)

    def get(self, name: str) -> Engine | None:
        """Return the engine for the given name, or ``None``."""
        return self.data.get(name)

    def __getitem__(self, name: str) -> Engine:
        return self.data[name]

    def __contains__(self, name: object) -> bool:
        return name in self.data

    def values(self) -> ValuesView[Engine]:
        """Return a view of all engine values."""
        return self.data.values()

    # START_CONTRACT: EngineRepository.filter
    #   PURPOSE: Filter engines by predicate and return a new frozen repository.
    #   INPUTS: { fn: Callable[[Engine], bool] - predicate function for filtering }
    #   OUTPUTS: { EngineRepository - new repository with matching engines only }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-ENGINE
    # END_CONTRACT: EngineRepository.filter
    def filter(self, fn: Callable[[Engine], bool]) -> EngineRepository:
        """Filter engines by predicate and return a new frozen repository."""
        return EngineRepository(data={k: v for k, v in self.data.items() if fn(v)})

    # START_CONTRACT: EngineRepository.filter_platforms
    #   PURPOSE: Filter engines by supported platforms and return a new frozen repository.
    #   INPUTS: { platforms: Sequence[str] - list of platform names to match against }
    #   OUTPUTS: { EngineRepository - new repository with engines supporting at least one given platform }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-ENGINE
    # END_CONTRACT: EngineRepository.filter_platforms
    def filter_platforms(self, platforms: Sequence[str]) -> EngineRepository:
        """Filter engines by supported platforms and return a new frozen repository."""
        return self.filter(lambda e: bool(set(e.platforms) & set(platforms)))

    # START_CONTRACT: EngineRepository.get_platform_packages
    #   PURPOSE: Collect the unique union of platform_packages across all engines.
    #   INPUTS: { None }
    #   OUTPUTS: { list[str] - unique platform packages (order-independent) }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-ENGINE
    # END_CONTRACT: EngineRepository.get_platform_packages
    def get_platform_packages(self) -> list[str]:
        """Collect the unique union of platform_packages across all engines."""
        mapped = (e.platform_packages for e in self.values())
        return list(set(chain(*mapped)))

## MODIFIED Requirements

### Requirement: Engine value object

The system SHALL provide an `Engine` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/engine.py` (re-exported from
`yascheduler.domain.model` and `yascheduler.domain`) with fields:
`name: str`, `spawn: str`, `input_files: tuple[str, ...] = ()`,
`output_files: tuple[str, ...] = ()`, `platforms: tuple[str, ...] = ()`,
`check_cmd: str | None = None`, `check_pname: str | None = None`,
`deployable: tuple[Deploy, ...] = ()`, `platform_packages: tuple[str, ...] = ()`,
`check_cmd_code: int = 0`, `sleep_interval: int = 10`.

The 4 fields `deployable`, `platform_packages`, `check_cmd_code`,
`sleep_interval` SHALL have defaults so existing
`Engine(name=..., spawn=..., input_files=..., platforms=...)` constructor
calls continue to work without modification.

`Engine` SHALL NOT import `ConfigParser` or `SectionProxy` and SHALL NOT carry
`from_config_parser_section` or `get_valid_config_parser_fields` methods; INI
parsing is provided by `entrypoints/config_parser.py::parse_engine_section`
and `parse_engines`.

#### Scenario: Validate inputs when all files present
- **WHEN** `engine.validate_inputs(ctx)` is called and all `input_files` exist in `ctx.extra`
- **THEN** no exception is raised

#### Scenario: Validate inputs when file missing
- **WHEN** `engine.validate_inputs(ctx)` is called and a required input file is missing from `ctx.extra`
- **THEN** `MissingInputFileError` is raised

#### Scenario: Engine constructed with defaults for the 4 merge fields
- **WHEN** `Engine(name="cp2k", spawn="cp2k", input_files=("inp",))` is constructed without `deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`
- **THEN** `deployable == ()`, `platform_packages == ()`, `check_cmd_code == 0`, `sleep_interval == 10`

#### Scenario: Engine is immutable
- **WHEN** `engine.name = "other"` is attempted on an `Engine` instance
- **THEN** `FrozenInstanceError` is raised (frozen dataclass)

#### Scenario: Engine has no INI parser methods
- **WHEN** `Engine` is inspected for class attributes
- **THEN** it has no `from_config_parser_section` classmethod and no `get_valid_config_parser_fields` classmethod

## ADDED Requirements

### Requirement: EngineRepository domain collection

The system SHALL provide an `EngineRepository` value object as an immutable
`@dataclass(frozen=True)` in `yascheduler/domain/engine.py` (re-exported from
`yascheduler.domain.model` and `yascheduler.domain`) with a single field
`data: Mapping[str, Engine]` (default empty dict). `EngineRepository` SHALL
NOT inherit from `UserDict`, SHALL NOT define `__hash__`, and SHALL NOT carry
an `engines_dir` field.

`EngineRepository` SHALL provide: `get(name: str) -> Engine | None`,
`__getitem__(name: str) -> Engine`, `__contains__(name: object) -> bool`,
`values() -> ValuesView[Engine]`,
`filter(fn: Callable[[Engine], bool]) -> EngineRepository`,
`filter_platforms(platforms: Sequence[str]) -> EngineRepository`,
`get_platform_packages() -> list[str]`.

`filter` and `filter_platforms` SHALL return a new frozen `EngineRepository`
instance; the original SHALL NOT be mutated.

#### Scenario: EngineRepository constructed with data
- **WHEN** `EngineRepository(data={"fleur": engine})` is constructed
- **THEN** `repo["fleur"] is engine`, `repo.get("fleur") is engine`, `"fleur" in repo` is True, `repo.get("missing") is None`, and `list(repo.values()) == [engine]`

#### Scenario: filter returns new frozen instance
- **WHEN** `repo.filter(lambda e: "linux" in e.platforms)` is called on an `EngineRepository` with two engines (one linux, one windows)
- **THEN** a new `EngineRepository` is returned containing only the linux engine; the original `repo` is unchanged and still contains both engines

#### Scenario: filter_platforms returns new frozen instance
- **WHEN** `repo.filter_platforms(("linux",))` is called on an `EngineRepository` with engines whose `platforms` include `("linux",)` and `("windows",)`
- **THEN** a new `EngineRepository` is returned containing only engines with `linux` in their platforms; the original is unchanged

#### Scenario: get_platform_packages collects unique packages
- **WHEN** `repo.get_platform_packages()` is called on an `EngineRepository` with two engines whose `platform_packages` are `("fleur", "python")` and `("python", "mpi")`
- **THEN** the returned list contains each unique package exactly once (order-independent)

#### Scenario: EngineRepository has no engines_dir field
- **WHEN** an `EngineRepository` instance is inspected for attributes
- **THEN** it has no `engines_dir` attribute; the field does not exist on the class

#### Scenario: EngineRepository is unhashable
- **WHEN** `hash(repo)` is called on an `EngineRepository` instance
- **THEN** `TypeError` is raised (frozen dataclass with `Mapping` field is unhashable; `__hash__` is not defined)

### Requirement: Engine domain types importable from yascheduler.domain.model

The system SHALL re-export `Engine`, `EngineRepository`,
`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`, and `Deploy`
from `yascheduler.domain.model` for backward compatibility with existing
`from yascheduler.domain.model import Engine` imports.

#### Scenario: Import Engine and EngineRepository from domain.model
- **WHEN** `from yascheduler.domain.model import Engine, EngineRepository` is executed
- **THEN** both symbols resolve without ImportError (re-exported from `domain/engine.py`)
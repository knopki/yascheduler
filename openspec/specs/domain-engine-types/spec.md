# Domain Engine Types

## Purpose

Defines the engine domain value objects for yascheduler: Engine, Deploy strategies,
EngineRepository frozen collection, and their import paths.

## Requirements

### Requirement: Engine domain value object with deploy strategies

The system SHALL provide `Engine`, `LocalFilesDeploy`, `LocalArchiveDeploy`,
`RemoteArchiveDeploy`, and `Deploy` (Union alias) as frozen stdlib
dataclasses in `yascheduler/domain/engine.py`. `Engine` SHALL have fields:
`name: str`, `spawn: str`, `input_files: tuple[str, ...] = ()`,
`output_files: tuple[str, ...] = ()`, `platforms: tuple[str, ...] = ()`,
`check_cmd: str | None = None`, `check_pname: str | None = None`,
`deployable: tuple[Deploy, ...] = ()`, `platform_packages: tuple[str, ...] = ()`,
`check_cmd_code: int = 0`, `sleep_interval: int = 10`. The 4 fields
`deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval` SHALL
have defaults so existing `Engine(name=..., spawn=..., input_files=..., platforms=...)`
constructor calls continue to work.

`Engine` SHALL provide
`validate_inputs(extra: Mapping[str, object]) -> None` (was
`validate_inputs(ctx: TaskContext) -> None`) that raises
`MissingInputFileError` if any `input_file` is missing from `extra`. The
`TaskContext` parameter is gone (the value object is removed per the
`domain-entities` delta); the engine reads the task's input-file payload
directly from the `extra: Mapping[str, object]` argument (file names as
keys, file contents as values). Callers pass `task.extra` (the `extra`
typed column on `Task`).

The `Engine` value object SHALL NOT import `ConfigParser` or `SectionProxy`
and SHALL NOT carry `from_config_parser_section` or `get_valid_config_parser_fields`
methods. The `Engine` value object SHALL NOT import `TaskContext` (removed).

#### Scenario: Engine constructed with all fields
- **WHEN** `Engine(name="fleur", spawn="{task_path} {engine_path} {ncpus}", input_files=("inp",), output_files=("out",), platforms=("linux",), check_cmd="which fleur", check_pname=None, deployable=(LocalArchiveDeploy(file=Path("/e/fleur.tar")),), platform_packages=("fleur",), check_cmd_code=0, sleep_interval=10)` is constructed
- **THEN** all fields are accessible as attributes and the instance is immutable (frozen dataclass)

#### Scenario: Engine constructed with defaults for the 4 merge fields
- **WHEN** `Engine(name="cp2k", spawn="cp2k", input_files=("inp",))` is constructed without `deployable`, `platform_packages`, `check_cmd_code`, `sleep_interval`
- **THEN** `deployable == ()`, `platform_packages == ()`, `check_cmd_code == 0`, `sleep_interval == 10`

#### Scenario: Engine is immutable
- **WHEN** `engine.name = "other"` is attempted on an `Engine` instance
- **THEN** `FrozenInstanceError` is raised (frozen dataclass)

#### Scenario: validate_inputs reads extra dict not TaskContext
- **WHEN** `engine.validate_inputs(extra={"inp": "ATOMS", "fort.9": "..."})` is called on an Engine whose `input_files=("inp",)`
- **THEN** no exception is raised (the required input file is present in `extra`); no `TaskContext` is constructed or referenced

#### Scenario: validate_inputs raises MissingInputFileError on missing key
- **WHEN** `engine.validate_inputs(extra={"other": "..."})` is called on an Engine whose `input_files=("inp",)`
- **THEN** `MissingInputFileError` is raised naming the engine and the missing input file `inp`

### Requirement: EngineRepository frozen collection

The system SHALL provide `EngineRepository` as a frozen stdlib dataclass in
`yascheduler/domain/engine.py` with a single field
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
instance; the original SHALL NOT be mutated. `EngineRepository` SHALL NOT
provide `items`, `keys`, `__len__`, or `__iter__` (no `UserDict`-inherited
surface).

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

#### Scenario: EngineRepository has no UserDict-inherited methods
- **WHEN** an `EngineRepository` instance is inspected
- **THEN** `hasattr(repo, "items")`, `hasattr(repo, "keys")`, `len(repo)`, and `iter(repo)` are not part of the public surface (accessing them raises `AttributeError` or `TypeError`)

#### Scenario: EngineRepository is unhashable
- **WHEN** `hash(repo)` is called on an `EngineRepository` instance
- **THEN** `TypeError` is raised (frozen dataclass with `Mapping` field is unhashable; `__hash__` is not defined)

#### Scenario: EngineRepository has no engines_dir field
- **WHEN** an `EngineRepository` instance is inspected for attributes
- **THEN** it has no `engines_dir` attribute; the field does not exist on the class

### Requirement: Engine types importable from yascheduler.domain

The system SHALL re-export `Engine`, `LocalFilesDeploy`, `LocalArchiveDeploy`,
`RemoteArchiveDeploy`, `Deploy`, and `EngineRepository` from
`yascheduler.domain` (the layer facade). `yascheduler.domain.model` SHALL
re-export them for backward compatibility with existing
`from yascheduler.domain.model import Engine` imports.

#### Scenario: Import Engine from domain facade
- **WHEN** `from yascheduler.domain import Engine, EngineRepository, Deploy, LocalFilesDeploy, LocalArchiveDeploy, RemoteArchiveDeploy` is executed
- **THEN** all six symbols resolve without ImportError

#### Scenario: Import Engine from domain.model for backward compat
- **WHEN** `from yascheduler.domain.model import Engine, EngineRepository` is executed
- **THEN** both symbols resolve without ImportError (re-exported from `domain/engine.py`)

### Requirement: Engine INI parser in entrypoints

The system SHALL provide `parse_engine_section(sec: SectionProxy, engines_dir: PurePath) -> Engine`,
`parse_engines(cfg: ConfigParser, engines_dir: PurePath) -> EngineRepository`,
and `engine_valid_fields() -> Sequence[str]` as free functions in
`entrypoints/config_parser.py`. The validators `_check_spawn`, `_check_check_`,
`_check_at_least_one_elem` SHALL run parser-side (raising `ValueError` on
invalid INI), not in `Engine.__post_init__`.

`engine_valid_fields()` SHALL return the valid INI keys for an `[engine.*]`
section, including the deploy alias fields (`deploy_local_files`,
`deploy_local_archive`, `deploy_remote_archive`) and excluding the `name` and
`deployable` dataclass fields.

#### Scenario: parse_engine_section builds Engine from INI
- **WHEN** `parse_engine_section(cfg["engine.fleur"], engines_dir)` is called with a section containing `spawn`, `input_files`, `output_files`, `platforms`, `check_cmd`, `deploy_local_archive=fleur.tar`
- **THEN** an `Engine` is returned with `name="fleur"`, `deployable=(LocalArchiveDeploy(file=engines_dir/"fleur"/"fleur.tar"),)`, and the other fields populated from the section

#### Scenario: parse_engine_section rejects unknown spawn placeholders
- **WHEN** `parse_engine_section` is called with a `spawn` value containing `{unknown_placeholder}`
- **THEN** `ValueError` is raised by the parser-side `_check_spawn` validator

#### Scenario: parse_engine_section rejects missing check methods
- **WHEN** `parse_engine_section` is called with neither `check_cmd` nor `check_pname` set
- **THEN** `ValueError` is raised by the parser-side `_check_check_` validator

#### Scenario: parse_engines collects all engine sections
- **WHEN** `parse_engines(cfg, engines_dir)` is called with a `ConfigParser` containing `[engine.fleur]` and `[engine.cp2k]` sections
- **THEN** an `EngineRepository` is returned with `data` containing both engines keyed by name

#### Scenario: engine_valid_fields returns INI key list
- **WHEN** `engine_valid_fields()` is called
- **THEN** the returned sequence includes `spawn`, `input_files`, `output_files`, `platforms`, `platform_packages`, `check_cmd`, `check_pname`, `check_cmd_code`, `sleep_interval`, `deploy_local_files`, `deploy_local_archive`, `deploy_remote_archive` and excludes `name` and `deployable`

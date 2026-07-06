# Spec Delta: domain-engine-types

## MODIFIED Requirements

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

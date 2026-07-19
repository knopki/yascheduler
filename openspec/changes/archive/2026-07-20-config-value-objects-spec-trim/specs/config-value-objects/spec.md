# Delta: config-value-objects

## MODIFIED Requirements

### Requirement: LocalSettings value object

The system SHALL provide a `LocalSettings` frozen stdlib dataclass with fields
`data_dir: Path` (default `Path("./data")`), `tasks_dir: Path` (default
`Path("./data/tasks")`), `engines_dir: Path` (default `Path("./data/engines")`),
`keys_dir: Path` (default `Path("./data/keys")`), `webhook_url: str | None`
(default `None`), `webhook_reqs_limit: int` (default `5`),
`conn_machine_limit: int` (default `10`), `conn_machine_pending: int` (default
`10`), `allocate_limit: int` (default `20`), `allocate_pending: int` (default
`1`), `consume_limit: int` (default `20`), `consume_pending: int` (default
`1`), `deallocate_limit: int` (default `5`), `deallocate_pending: int` (default
`1`).

The dataclass SHALL be frozen with no INI parsing methods. Validation (limits
`ge(1)`, `webhook_reqs_limit` `ge(0)`) SHALL raise `ValueError` on violation.

`LocalSettings` SHALL be importable from `yascheduler.domain`.

#### Scenario: LocalSettings frozen
- **WHEN** an attempt is made to assign `settings.data_dir = Path("/other")` on a `LocalSettings` instance
- **THEN** `FrozenInstanceError` is raised

#### Scenario: LocalSettings importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import LocalSettings`
- **THEN** the symbol resolves without ImportError

#### Scenario: LocalSettings rejects negative limit
- **WHEN** `LocalSettings(allocate_limit=0)` is constructed
- **THEN** `ValueError` is raised

#### Scenario: LocalSettings has no cloud_package_upgrade field
- **WHEN** `dataclasses.fields(LocalSettings)` is introspected for a field named `cloud_package_upgrade`
- **THEN** no such field exists (the knob was relocated to the per-provider `ConfigCloud*` DTOs)

#### Scenario: legacy [local] cloud_package_upgrade warns as unknown
- **WHEN** a `[local]` section containing `cloud_package_upgrade = false` is parsed
- **THEN** parsing succeeds (no error raised) and a `ConfigWarning` is emitted naming `cloud_package_upgrade` as an unknown field
- **AND** the resulting `LocalSettings` carries no `cloud_package_upgrade` attribute

### Requirement: RemoteDefaults value object

The system SHALL provide a `RemoteDefaults` frozen stdlib dataclass with fields
`data_dir: PurePath` (default `PurePath("./data")`), `tasks_dir: PurePath`
(default `PurePath("./data/tasks")`), `engines_dir: PurePath` (default
`PurePath("./data/engines")`), `username: str` (default `"root"`),
`jump_username: str | None` (default `None`), `jump_host: str | None` (default
`None`), `jump_port: int` (default `22`).

The dataclass SHALL be frozen with no INI parsing methods. `RemoteDefaults`
SHALL be importable from `yascheduler.domain`.

#### Scenario: RemoteDefaults frozen

- **WHEN** an attempt is made to assign `defaults.username = "ops"` on a `RemoteDefaults` instance
- **THEN** `FrozenInstanceError` is raised

#### Scenario: RemoteDefaults importable from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import RemoteDefaults`
- **THEN** the symbol resolves without ImportError

#### Scenario: RemoteDefaults jump_port default

- **WHEN** a `RemoteDefaults` is constructed without an explicit `jump_port`
- **THEN** `jump_port == 22`

### Requirement: [remote] section jump_port parsing and validation

The `[remote]` INI section parser SHALL read the optional `jump_port` key as an
integer (default `22`) and surface it on `RemoteDefaults.jump_port`. The parser
SHALL validate the range 1–65535 (mirroring the `yascheduler_nodes.jump_port`
DB `CHECK` constraint) at parse time, raising `ValueError` on any value outside
that range or on a non-integer value.

The `jump_port` key SHALL be added to the `[remote]` valid-field set so
unknown-field warnings do not fire on it.

#### Scenario: jump_port defaults to 22 when [remote] key absent

- **GIVEN** an INI with a `[remote]` section that does NOT set `jump_port`
- **WHEN** `parse_config(path)` constructs the `Config`
- **THEN** `config.remote.jump_port == 22`

#### Scenario: jump_port read from [remote] section

- **GIVEN** an INI with `[remote] jump_port = 2222`
- **WHEN** `parse_config(path)` constructs the `Config`
- **THEN** `config.remote.jump_port == 2222`

#### Scenario: [remote] parser rejects jump_port below 1

- **GIVEN** an INI with `[remote] jump_port = 0`
- **WHEN** `parse_config(path)` is called
- **THEN** `ValueError` is raised

#### Scenario: [remote] parser rejects jump_port at or above 65536

- **GIVEN** an INI with `[remote] jump_port = 65536`
- **WHEN** `parse_config(path)` is called
- **THEN** `ValueError` is raised

#### Scenario: [remote] parser rejects non-integer jump_port

- **GIVEN** an INI with `[remote] jump_port = ssh`
- **WHEN** `parse_config(path)` is called
- **THEN** `ValueError` is raised

### Requirement: PostgresDbConfig value object

The system SHALL provide a `PostgresDbConfig` frozen stdlib dataclass with
fields `user: str` (default `"yascheduler"`), `password: str` (default
`"password"`), `database: str` (default `"database"`), `host: str` (default
`"localhost"`), `port: int` (default `5432`).

The dataclass SHALL be frozen with no INI parsing methods. Validation (`port`
`ge(1)`) SHALL raise `ValueError` on violation.

`PostgresDbConfig` SHALL be importable from `yascheduler.infra.persistence`.

#### Scenario: PostgresDbConfig frozen
- **WHEN** an attempt is made to assign `cfg.port = 5433` on a `PostgresDbConfig` instance
- **THEN** `FrozenInstanceError` is raised

#### Scenario: PostgresDbConfig importable from persistence facade
- **WHEN** a consumer imports `from yascheduler.infra.persistence import PostgresDbConfig`
- **THEN** the symbol resolves without ImportError

#### Scenario: PostgresDbConfig rejects invalid port
- **WHEN** `PostgresDbConfig(port=0)` is constructed
- **THEN** `ValueError` is raised

### Requirement: Config aggregate

The system SHALL provide a `Config` frozen stdlib dataclass with fields `db:
PostgresDbConfig`, `local: LocalSettings`, `remote: RemoteDefaults`, `clouds:
Sequence[ConfigCloud]`, `engines: EngineRepository`.

The dataclass SHALL be frozen. `Config` SHALL be importable from
`yascheduler.entrypoints`. No module in `yascheduler.application` or
`yascheduler.infra` SHALL import `Config`.

The `Config` aggregate SHALL NOT carry INI parsing methods; parsing is owned
by `parse_config`.

The `clouds` field SHALL be typed `Sequence[ConfigCloud]` where `ConfigCloud`
is the infra Union of the 4 concrete `ConfigCloud*` DTOs.

#### Scenario: Config frozen
- **WHEN** an attempt is made to assign `config.engines = other_engines` on a `Config` instance
- **THEN** `FrozenInstanceError` is raised

#### Scenario: Config importable from entrypoints facade
- **WHEN** a consumer imports `from yascheduler.entrypoints import Config`
- **THEN** the symbol resolves without ImportError

#### Scenario: Application layer does not import Config
- **WHEN** any module in `yascheduler/application/` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` import appears

#### Scenario: Infra layer does not import Config
- **WHEN** any module in `yascheduler/infra/` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` import appears

#### Scenario: Config.clouds typed against the infra ConfigCloud Union
- **WHEN** the `clouds` field annotation on the `Config` dataclass is inspected
- **THEN** the annotation is `Sequence[ConfigCloud]` (not `Sequence[CloudConfig]`)

#### Scenario: Config.clouds runtime value is list[ConfigCloud]
- **WHEN** `parse_config(path)` constructs a `Config` instance for a valid INI file
- **THEN** `config.clouds` is a `list` whose every element is an instance of one of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`

### Requirement: shared.compat re-exports StrEnum

The system SHALL re-export `StrEnum` from `yascheduler.shared.compat` using a
version branch: `from enum import StrEnum` on Python 3.11+ and
`from typing_extensions import StrEnum` below 3.11. `StrEnum` SHALL be included
in `__all__`.

#### Scenario: StrEnum is importable from shared.compat
- **WHEN** `from yascheduler.shared.compat import StrEnum` is executed on any supported Python version (>=3.9)
- **THEN** `StrEnum` is a class that can be subclassed to define a string enum

#### Scenario: StrEnum is in __all__
- **WHEN** `yascheduler.shared.compat.__all__` is inspected
- **THEN** `StrEnum` is included alongside `Self` and `Unpack`

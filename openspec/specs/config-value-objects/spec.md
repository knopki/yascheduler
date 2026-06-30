# Config Value Objects

## Purpose

The frozen config value objects — `LocalSettings`, `RemoteDefaults`,
`PostgresDbConfig`, and the `Config` aggregate — defined as stdlib
dataclasses with `__post_init__` validation, no INI-parsing methods, and the
composition-root-only consumption rule for `Config`. Replaces the former
`app-settings`/`db-config`/`config-aggregate` specs.

## Requirements

### Requirement: LocalSettings value object

The system SHALL provide a `LocalSettings` frozen stdlib dataclass in
`yascheduler/domain/settings.py` with fields `data_dir: Path` (default
`Path("./data")`), `tasks_dir: Path` (default `Path("./data/tasks")`),
`engines_dir: Path` (default `Path("./data/engines")`), `keys_dir: Path`
(default `Path("./data/keys")`), `webhook_url: str | None` (default `None`),
`webhook_reqs_limit: int` (default `5`), `conn_machine_limit: int` (default
`10`), `conn_machine_pending: int` (default `10`), `allocate_limit: int`
(default `20`), `allocate_pending: int` (default `1`), `consume_limit: int`
(default `20`), `consume_pending: int` (default `1`), `deallocate_limit: int`
(default `5`), `deallocate_pending: int` (default `1`).

The dataclass SHALL be `@dataclass(frozen=True)` with no INI parsing methods
and no attrs dependency. Validation (limits `ge(1)`, `webhook_reqs_limit`
`ge(0)`) SHALL run in `__post_init__` raising `ValueError` on violation.

`LocalSettings` SHALL be importable from `yascheduler.domain`.

#### Scenario: LocalSettings frozen
- **WHEN** an attempt is made to assign `settings.data_dir = Path("/other")` on a `LocalSettings` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: LocalSettings importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import LocalSettings`
- **THEN** the symbol resolves without ImportError

#### Scenario: LocalSettings rejects negative limit
- **WHEN** `LocalSettings(allocate_limit=0)` is constructed
- **THEN** `ValueError` is raised in `__post_init__`

### Requirement: RemoteDefaults value object

The system SHALL provide a `RemoteDefaults` frozen stdlib dataclass in
`yascheduler/domain/settings.py` with fields `data_dir: PurePath` (default
`PurePath("./data")`), `tasks_dir: PurePath` (default `PurePath("./data/tasks")`),
`engines_dir: PurePath` (default `PurePath("./data/engines")`), `username: str`
(default `"root"`), `jump_username: str | None` (default `None`), `jump_host:
str | None` (default `None`).

The dataclass SHALL be `@dataclass(frozen=True)` with no INI parsing methods
and no attrs dependency. `RemoteDefaults` SHALL be importable from
`yascheduler.domain`.

#### Scenario: RemoteDefaults frozen
- **WHEN** an attempt is made to assign `defaults.username = "ops"` on a `RemoteDefaults` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: RemoteDefaults importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import RemoteDefaults`
- **THEN** the symbol resolves without ImportError

### Requirement: PostgresDbConfig value object

The system SHALL provide a `PostgresDbConfig` frozen stdlib dataclass in
`yascheduler/infra/persistence/db_config.py` with fields `user: str` (default
`"yascheduler"`), `password: str` (default `"password"`), `database: str`
(default `"database"`), `host: str` (default `"localhost"`), `port: int`
(default `5432`).

The dataclass SHALL be `@dataclass(frozen=True)` with no INI parsing methods
and no attrs dependency. Validation (`port` `ge(1)`) SHALL run in
`__post_init__` raising `ValueError` on violation.

`PostgresDbConfig` SHALL be importable from `yascheduler.infra.persistence`.
`postgres_uow.py` and `postgres_schema.py` SHALL import it via an intra-package
relative import (`from .db_config import PostgresDbConfig`).

#### Scenario: PostgresDbConfig frozen
- **WHEN** an attempt is made to assign `cfg.port = 5433` on a `PostgresDbConfig` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: PostgresDbConfig importable from persistence facade
- **WHEN** a consumer imports `from yascheduler.infra.persistence import PostgresDbConfig`
- **THEN** the symbol resolves without ImportError

#### Scenario: PostgresDbConfig rejects invalid port
- **WHEN** `PostgresDbConfig(port=0)` is constructed
- **THEN** `ValueError` is raised in `__post_init__`

#### Scenario: PostgresUnitOfWork uses intra-package import
- **WHEN** `postgres_uow.py` is inspected for its `ConfigDb` import
- **THEN** it imports `PostgresDbConfig` from `.db_config` (intra-package)

#### Scenario: apply_schema uses intra-package import
- **WHEN** `postgres_schema.py::apply_schema` is inspected for its config type
- **THEN** the signature is `apply_schema(config: PostgresDbConfig)` and the import is `from .db_config import PostgresDbConfig`

### Requirement: Config aggregate

The system SHALL provide a `Config` frozen stdlib dataclass in
`yascheduler/entrypoints/config.py` with fields `db: PostgresDbConfig`, `local:
LocalSettings`, `remote: RemoteDefaults`, `clouds: Sequence[ConfigCloud]`,
`engines: EngineRepository`.

The dataclass SHALL be `@dataclass(frozen=True)` with no attrs dependency.
`Config` SHALL be importable from `yascheduler.entrypoints`. No module in
`yascheduler.application` or `yascheduler.infra` SHALL import `Config` — the
aggregate is a composition-root concept consumed only by `entrypoints`.

The `Config` aggregate SHALL NOT carry INI parsing methods; parsing is owned by
`parse_config` in `yascheduler.entrypoints.config_parser`.

The `clouds` field SHALL be typed `Sequence[ConfigCloud]` where `ConfigCloud`
is the infra Union of the 4 concrete `ConfigCloud*` DTOs (imported
`TYPE_CHECKING`-only from `yascheduler.infra.cloud.cloud_configs`). Application-
layer consumers (`Orchestrator`, `deallocate_nodes`) type their parameters
against the domain `CloudConfig` Protocol and receive `Sequence[ConfigCloud]`
values assignable to `Sequence[CloudConfig]` via covariance plus the explicit
DTO→Protocol inheritance on the `ConfigCloud*` DTOs.

#### Scenario: Config frozen
- **WHEN** an attempt is made to assign `config.engines = other_engines` on a `Config` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: Config importable from entrypoints facade
- **WHEN** a consumer imports `from yascheduler.entrypoints import Config`
- **THEN** the symbol resolves without ImportError

#### Scenario: Application layer does not import Config
- **WHEN** any module in `yascheduler/application/` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears

#### Scenario: Infra layer does not import Config
- **WHEN** any module in `yascheduler/infra/` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` import appears

#### Scenario: Config.clouds typed against the infra ConfigCloud Union
- **WHEN** `yascheduler/entrypoints/config.py` is inspected for the `clouds` field annotation on the `Config` dataclass
- **THEN** the annotation is `Sequence[ConfigCloud]` (not `Sequence[CloudConfig]`), with `ConfigCloud` imported `TYPE_CHECKING`-only from `yascheduler.infra.cloud.cloud_configs`

#### Scenario: Config.clouds runtime value is list[ConfigCloud]
- **WHEN** `parse_config(path)` constructs a `Config` instance for a valid INI file
- **THEN** `config.clouds` is a `list` whose every element is an instance of one of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI`
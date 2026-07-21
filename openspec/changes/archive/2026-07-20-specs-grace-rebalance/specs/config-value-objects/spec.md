## MODIFIED Requirements

### Requirement: LocalSettings value object

The system SHALL provide a `LocalSettings` frozen stdlib dataclass that
holds the daemon concurrency limits, local paths, and webhook settings. The
dataclass SHALL be frozen with no INI parsing methods.

Validation: the concurrency-limit fields SHALL be `ge(1)` and
`webhook_reqs_limit` SHALL be `ge(0)`, raising `ValueError` on violation.

`LocalSettings` SHALL be importable from `yascheduler.domain`.

The field inventory, the per-field defaults, and the `frozen=True` declaration
live in the `CLASS_LocalSettings` GRACE INVARIANTS — they are shape, not
behavior.

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

The system SHALL provide a `RemoteDefaults` frozen stdlib dataclass that
holds the remote-side SSH defaults (paths, username, jump-host settings).
The dataclass SHALL be frozen with no INI parsing methods.

`RemoteDefaults` SHALL be importable from `yascheduler.domain`.

The field inventory and per-field defaults live in the
`CLASS_RemoteDefaults` GRACE INVARIANTS.

#### Scenario: RemoteDefaults frozen

- **WHEN** an attempt is made to assign `defaults.username = "ops"` on a `RemoteDefaults` instance
- **THEN** `FrozenInstanceError` is raised

#### Scenario: RemoteDefaults importable from domain facade

- **WHEN** a consumer imports `from yascheduler.domain import RemoteDefaults`
- **THEN** the symbol resolves without ImportError

#### Scenario: RemoteDefaults jump_port default

- **WHEN** a `RemoteDefaults` is constructed without an explicit `jump_port`
- **THEN** `jump_port == 22`

### Requirement: PostgresDbConfig value object

The system SHALL provide a `PostgresDbConfig` frozen stdlib dataclass that
holds the PostgreSQL connection parameters. The dataclass SHALL be frozen
with no INI parsing methods.

Validation: `port` SHALL be `ge(1)`, raising `ValueError` on violation.

`PostgresDbConfig` SHALL be importable from `yascheduler.infra.persistence`.

The field inventory and per-field defaults live in the
`CLASS_PostgresDbConfig` GRACE INVARIANTS.

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

The system SHALL provide a `Config` frozen stdlib dataclass that aggregates
the per-section value objects. `Config` SHALL be importable from
`yascheduler.entrypoints`. No module in `yascheduler.application` or
`yascheduler.infra` SHALL import `Config`.

The `Config` aggregate SHALL NOT carry INI parsing methods; parsing is owned
by `parse_config`.

The `clouds` field SHALL be typed `Sequence[ConfigCloud]` where `ConfigCloud`
is the infra Union of the 4 concrete `ConfigCloud*` DTOs.

The field inventory and the `frozen=True` declaration live in the
`CLASS_Config` GRACE INVARIANTS.

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

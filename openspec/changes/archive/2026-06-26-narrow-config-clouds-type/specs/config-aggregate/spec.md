# Config Aggregate — Delta

## MODIFIED Requirements

### Requirement: Config aggregate

The system SHALL provide a `Config` frozen stdlib dataclass in
`yascheduler/entrypoints/config.py` with fields `db: PostgresDbConfig`, `local:
LocalSettings`, `remote: RemoteDefaults`, `clouds: Sequence[ConfigCloud]`,
`engines: EngineRepository`.

The dataclass SHALL be `@dataclass(frozen=True)` with no attrs dependency.
`Config` SHALL be importable from `yascheduler.entrypoints`. No module in
`yascheduler.application` or `yascheduler.infra` SHALL import `Config` — the
aggregate is a composition-root concept consumed only by `entrypoints`.

The `Config` aggregate SHALL NOT carry INI parsing methods. Parsing is owned by
`parse_config` in `yascheduler.entrypoints.config_parser`.

The `clouds` field SHALL be typed `Sequence[ConfigCloud]` where `ConfigCloud`
is the infra Union of the 4 concrete `ConfigCloud*` DTOs (imported
`TYPE_CHECKING`-only from `yascheduler.infra.cloud.cloud_configs`). The
composition root knows the concrete Union because it wires infra sinks
(`resolve_adapter`, `CloudProvisionerImpl.configs`) that read provider-specific
fields; application-layer consumers (`Orchestrator`, `deallocate_nodes`)
continue to type their parameters against the domain `CloudConfig` Protocol
and receive `Sequence[ConfigCloud]` values assignable to `Sequence[CloudConfig]`
via covariance + the explicit DTO→Protocol inheritance established by the
`resolve-type-bridge-debt` D1 decision.

#### Scenario: Config frozen
- **WHEN** an attempt is made to assign `config.engines = other_engines` on a `Config` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: Config importable from entrypoints facade
- **WHEN** a consumer imports `from yascheduler.entrypoints import Config`
- **THEN** the symbol resolves without ImportError

#### Scenario: Application layer does not import Config
- **WHEN** any module in `yascheduler/application/` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears (the orchestrator receives unpacked `LocalSettings` / `RemoteDefaults`, not the aggregate)

#### Scenario: Infra layer does not import Config
- **WHEN** any module in `yascheduler/infra/` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` import appears

#### Scenario: Config.clouds typed against the infra ConfigCloud Union
- **WHEN** `yascheduler/entrypoints/config.py` is inspected for the `clouds` field annotation on the `Config` dataclass
- **THEN** the annotation is `Sequence[ConfigCloud]` (not `Sequence[CloudConfig]`), with `ConfigCloud` imported `TYPE_CHECKING`-only from `yascheduler.infra.cloud.cloud_configs`

#### Scenario: Config.clouds runtime value is list[ConfigCloud]
- **WHEN** `parse_config(path)` constructs a `Config` instance for a valid INI file
- **THEN** `config.clouds` is a `list` whose every element is an instance of one of `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudVastAI` (the `parse_clouds` producer returns `list[ConfigCloud]`; the narrowed field type matches the runtime type)
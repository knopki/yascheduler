# Config Aggregate

## Purpose

The `Config` frozen aggregate that composes the DB, local, remote, cloud, and
engine value objects, consumed only by the composition root (entrypoints layer).

## Requirements

### Requirement: Config aggregate

The system SHALL provide a `Config` frozen stdlib dataclass in
`yascheduler/entrypoints/config.py` with fields `db: PostgresDbConfig`, `local:
LocalSettings`, `remote: RemoteDefaults`, `clouds: Sequence[CloudConfig]`,
`engines: EngineRepository`.

The dataclass SHALL be `@dataclass(frozen=True)` with no attrs dependency.
`Config` SHALL be importable from `yascheduler.entrypoints`. No module in
`yascheduler.application` or `yascheduler.infra` SHALL import `Config` — the
aggregate is a composition-root concept consumed only by `entrypoints`.

The `Config` aggregate SHALL NOT carry INI parsing methods. Parsing is owned by
`parse_config` in `yascheduler.entrypoints.config_parser`.

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
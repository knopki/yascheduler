## MODIFIED Requirements

### Requirement: LocalSettings value object

The system SHALL provide a `LocalSettings` frozen stdlib dataclass that
holds the daemon concurrency limits, local paths, and webhook settings. The
dataclass SHALL be frozen with no INI parsing methods.

Validation: the concurrency-limit fields SHALL be `ge(1)` and
`webhook_reqs_limit` SHALL be `ge(0)`, raising `ValueError` on violation.

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

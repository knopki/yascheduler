## MODIFIED Requirements

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

`LocalSettings` SHALL NOT carry the `cloud_package_upgrade` field — that knob
is a cloud-only concern and has been relocated to the per-provider
`ConfigCloud*` DTOs (see the `cloud-config` capability). A legacy
`[local] cloud_package_upgrade` INI key, if present, SHALL surface as an
"unknown field" `ConfigWarning` (via `_local_valid_fields()` introspection,
which derives from `dataclasses.fields(LocalSettings)`), not as an error.

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

#### Scenario: LocalSettings has no cloud_package_upgrade field
- **WHEN** `dataclasses.fields(LocalSettings)` is introspected for a field named `cloud_package_upgrade`
- **THEN** no such field exists (the knob was relocated to the per-provider `ConfigCloud*` DTOs)

#### Scenario: legacy [local] cloud_package_upgrade warns as unknown
- **WHEN** a `[local]` section containing `cloud_package_upgrade = false` is parsed by `_parse_local_section`
- **THEN** parsing succeeds (no error raised) and a `ConfigWarning` is emitted naming `cloud_package_upgrade` as an unknown field (because `_local_valid_fields()` no longer lists it)
- **AND** the resulting `LocalSettings` carries no `cloud_package_upgrade` attribute

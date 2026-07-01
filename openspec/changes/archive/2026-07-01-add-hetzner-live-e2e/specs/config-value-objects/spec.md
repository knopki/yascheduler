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
(default `5`), `deallocate_pending: int` (default `1`), and
`cloud_package_upgrade: bool` (default `True`).

The dataclass SHALL be `@dataclass(frozen=True)` with no INI parsing methods
and no attrs dependency. Validation (limits `ge(1)`, `webhook_reqs_limit`
`ge(0)`) SHALL run in `__post_init__` raising `ValueError` on violation. The
`cloud_package_upgrade` field SHALL require no `__post_init__` validation
(any `bool` is accepted).

`LocalSettings` SHALL be importable from `yascheduler.domain`.

The `[local]` INI section parser (`_parse_local_section` in
`entrypoints/config_parser.py`) SHALL read the optional
`cloud_package_upgrade` key via `sec.getboolean("cloud_package_upgrade")`,
defaulting to `True` when the key is absent (preserving the pre-change
behavior). Because `_local_valid_fields()` introspects the dataclass, the new
key SHALL NOT trigger an "unknown field" warning.

#### Scenario: LocalSettings frozen
- **WHEN** an attempt is made to assign `settings.data_dir = Path("/other")` on a `LocalSettings` instance
- **THEN** `dataclasses.FrozenInstanceError` is raised

#### Scenario: LocalSettings importable from domain facade
- **WHEN** a consumer imports `from yascheduler.domain import LocalSettings`
- **THEN** the symbol resolves without ImportError

#### Scenario: LocalSettings rejects negative limit
- **WHEN** `LocalSettings(allocate_limit=0)` is constructed
- **THEN** `ValueError` is raised in `__post_init__`

#### Scenario: LocalSettings defaults cloud_package_upgrade to True
- **WHEN** `LocalSettings()` is constructed with no `cloud_package_upgrade` argument
- **THEN** `settings.cloud_package_upgrade is True`

#### Scenario: [local] cloud_package_upgrade parsed and defaulted
- **WHEN** a `[local]` section without `cloud_package_upgrade` is parsed
- **THEN** the resulting `LocalSettings.cloud_package_upgrade is True`
- **WHEN** a `[local]` section with `cloud_package_upgrade = false` is parsed
- **THEN** the resulting `LocalSettings.cloud_package_upgrade is False`
- **AND** no "unknown field" warning is emitted for the key

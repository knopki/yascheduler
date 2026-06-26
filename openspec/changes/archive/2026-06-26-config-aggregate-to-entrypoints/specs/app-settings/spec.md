## ADDED Requirements

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
(`from_config_parser_section`, `get_valid_config_parser_fields`) and no attrs
dependency. Validation (limits `ge(1)`, `webhook_reqs_limit` `ge(0)`) SHALL run
in `__post_init__` raising `ValueError` on violation.

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
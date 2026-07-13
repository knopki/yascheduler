## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: [remote] section jump_port parsing and validation

The `[remote]` INI section parser SHALL read the optional `jump_port` key as an
integer (default `22`) and surface it on `RemoteDefaults.jump_port`. The parser
SHALL validate the range 1–65535 (mirroring the `yascheduler_nodes.jump_port`
DB `CHECK` constraint) at parse time, raising `ValueError` on any value outside
that range or on a non-integer value. This follows the existing
`getint` + range-check parser idiom (e.g. `max_nodes`, `idle_tolerance` in the
cloud per-prefix parsers), NOT `__post_init__` validation on `RemoteDefaults`.

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

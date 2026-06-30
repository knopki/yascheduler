## MODIFIED Requirements

### Requirement: parse_config assembly

The system SHALL provide a `parse_config(path: Path) -> Config` function in
`yascheduler/entrypoints/config_parser.py` (or a sibling
`entrypoints/_config_utils.py` if the parser module would exceed the
GRACE-lite 500-line soft limit) that reads the INI file via `ConfigParser`
(with `DEFAULTSEC` interpolation enabled so `%(key)s` works across sections) and
assembles the five `Config` fields.

The per-section parser helpers (`_parse_db_section`, `_parse_local_section`,
`_parse_remote_section`, `parse_engines`, `parse_clouds`) SHALL live in
`yascheduler/entrypoints/config_parser.py` (or the sibling utils module). They
SHALL NOT live in `yascheduler.shared` (shared kernel restriction) and the
value objects they construct SHALL NOT carry parser methods.

The `parse_engine_section(sec, engines_dir) -> Engine` helper SHALL validate
the `spawn` key BEFORE constructing the `Engine` value object: when
`spawn` is absent or empty, the helper SHALL raise `ConfigError` with a message
naming the offending `[engine.*]` section. `warn_unknown_fields(sec, valid_keys,
*, on_warning=warn_config) -> None` SHALL emit a `ConfigWarning` for each
unknown key; it is called from the parser functions, not from the value objects.

The `parse_config` assembly SHALL NOT carry a `cast("Sequence[CloudConfig]",
clouds)` bridge when building the `Config` aggregate — the explicit
DTO→`CloudConfig` Protocol inheritance on the `ConfigCloud*` DTOs makes the
`Sequence[ConfigCloud] → Sequence[CloudConfig]` assignment typecheck without a
cast.

#### Scenario: parse_config round-trips a full INI
- **WHEN** `parse_config(path)` is called with a valid INI containing `[db]`, `[local]`, `[remote]`, `[engine.fleur]`, and `[cloud.hetzner]` sections
- **THEN** the returned `Config` has `db`, `local`, `remote`, `clouds`, `engines` populated with the parsed values

#### Scenario: Value objects carry no parser methods
- **WHEN** `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`, `Engine`, `EngineRepository`, `ConfigCloud*` are inspected
- **THEN** no such methods exist on the dataclasses; parsing is invoked only via the `entrypoints/config_parser.py` functions

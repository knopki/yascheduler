## ADDED Requirements

### Requirement: parse_config assembly

The system SHALL provide a `parse_config(path: str | bytes | PurePath) -> Config`
function in `yascheduler/entrypoints/config_parser.py` that reads an INI file,
parses each section via per-section parser functions, and returns a frozen
`Config` aggregate.

`parse_config` SHALL orchestrate:
- `_parse_db_section(sec) -> PostgresDbConfig` for the `[db]` section
- `_parse_local_section(sec) -> LocalSettings` for the `[local]` section
- `_parse_remote_section(sec) -> RemoteDefaults` for the `[remote]` section
- `parse_engines(cfg, engines_dir) -> EngineRepository` for `[engine.*]` sections
  (from P2)
- `parse_clouds(cfg, remote) -> Sequence[CloudConfig]` for `[cloud.*]` sections
  (from P3, dispatching via the `CLOUD_CONFIG_PARSERS` registry)

Validation (`ge(1)` for limits, `instance_of` for types, `opt_str_val` for
optional strings, `default_if_none` for None-coercion) SHALL run inside the
parser functions, not in the dataclass `__post_init__` of the value objects.
The value objects (`LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`,
`Config`) SHALL stay pure.

The parser helpers `make_default_field`, `warn_unknown_fields`, `opt_str_val`,
`ConfigWarning`, and `config_repr` SHALL live in
`yascheduler/entrypoints/config_parser.py` (or a sibling
`entrypoints/_config_utils.py` if the parser module would exceed the
GRACE-lite 500-line soft limit). They SHALL NOT live in `yascheduler.config`
(the package is deleted) or in `yascheduler.shared` (shared kernel restriction).

#### Scenario: parse_config round-trips a full INI
- **WHEN** `parse_config(path)` is called with a valid INI containing `[db]`, `[local]`, `[remote]`, `[engine.fleur]`, and `[cloud.hetzner]` sections
- **THEN** the returned `Config` has `db`, `local`, `remote`, `clouds`, `engines` populated with the parsed values

#### Scenario: parse_config warns on unknown keys
- **WHEN** `parse_config(path)` is called with an INI containing an unknown key in `[local]`
- **THEN** a `ConfigWarning` is emitted via `warn_unknown_fields`

#### Scenario: parse_config uses cloud registry
- **WHEN** `parse_config(path)` is called with an INI containing `[cloud.vastai]`
- **THEN** the cloud is parsed via the `CLOUD_CONFIG_PARSERS` registry entry for `vastai` (no hardcoded variant list in `parse_config`)

#### Scenario: value objects have no parser methods
- **WHEN** `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig` are inspected for `from_config_parser_section` / `get_valid_config_parser_fields`
- **THEN** no such methods exist on the dataclasses; parsing is invoked only via the `entrypoints/config_parser.py` functions

#### Scenario: yascheduler.config package does not exist
- **WHEN** `python -c "import yascheduler.config"` is executed
- **THEN** `ModuleNotFoundError` is raised
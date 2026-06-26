## MODIFIED Requirements

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing via the `parse_config` function and
the per-section parser functions in
`yascheduler/entrypoints/config_parser.py`:

- `_parse_db_section`, `_parse_local_section`, `_parse_remote_section`
  round-trip `[db]`, `[local]`, `[remote]` sections into
  `PostgresDbConfig`, `LocalSettings`, `RemoteDefaults` with defaults and
  overrides.
- `parse_engines` round-trips `[engine.*]` sections into
  `EngineRepository` (from P2).
- `parse_clouds` round-trips `[cloud.*]` sections into
  `Sequence[CloudConfig]` via the `CLOUD_CONFIG_PARSERS` registry (from
  P3), including `ConfigCloudAzure`, `ConfigCloudHetzner`,
  `ConfigCloudUpcloud`, `ConfigCloudVastAI`.
- `ConfigCloudAzure` rejects `username="root"` with `ValueError` (parser-side
  validation).
- `parse_config(path)` full assembly produces a frozen `Config` aggregate
  with all five fields populated; empty sections use defaults.
- `warn_unknown_fields` emits `ConfigWarning` for unknown keys (called from
  the parser functions, not from the value objects).
- The value objects (`LocalSettings`, `RemoteDefaults`, `PostgresDbConfig`,
  `Config`, `Engine`, `EngineRepository`, `ConfigCloud*`) SHALL be asserted
  frozen (`@dataclass(frozen=True)`) with no `from_config_parser_section` or
  `get_valid_config_parser_fields` methods.

Test fixtures SHALL construct `Config` instances via `dataclasses.replace`
or a `ConfigBuilder` helper, not via direct attribute assignment
(`config.engines = ...`), because `Config` is frozen.

#### Scenario: parse_config round-trips all sections
- **WHEN** `parse_config(path)` is called with a full INI
- **THEN** the returned `Config` has `db`, `local`, `remote`, `clouds`, `engines` populated with the parsed values and is frozen

#### Scenario: Value objects have no parser methods
- **WHEN** `LocalSettings`, `RemoteDefaults`, `PostgresDbConfig` are inspected
- **THEN** they have no `from_config_parser_section` or `get_valid_config_parser_fields` classmethods; parsing lives in `entrypoints/config_parser.py`

#### Scenario: Config mutation via replace
- **WHEN** a test needs a `Config` with a different `engines` field
- **THEN** it uses `dataclasses.replace(config, engines=new_engines)` (not `config.engines = new_engines`, which raises `FrozenInstanceError`)

#### Scenario: ConfigBuilder helper for high-density test files
- **WHEN** a test file has ≥4 `replace` call sites
- **THEN** it MAY use a `ConfigBuilder` helper defined in `tests/unit/conftest.py` to avoid repetition; the builder produces a frozen `Config` instance

#### Scenario: VastAI round-trips via registry
- **WHEN** `parse_config(path)` is called with an INI containing `[cloud.vastai]`
- **THEN** the cloud is parsed via the `CLOUD_CONFIG_PARSERS` registry entry for `vastai` and appears in `config.clouds`
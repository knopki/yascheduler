## MODIFIED Requirements

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

The `parse_engine_section(sec, engines_dir) -> Engine` helper SHALL validate
the `spawn` key BEFORE constructing the `Engine` value object: when
`sec.get("spawn")` returns `None` (the `[engine.*]` section omits the `spawn`
key), `parse_engine_section` SHALL raise `ValueError(f"Engine {name} has no
spawn command")` (where `name = sec.name[7:]`) before calling `Engine(...)`.
This hoist replaces the prior pattern of constructing `Engine(spawn=None)` and
relying on the post-construction validator `_check_spawn(engine,
engine.spawn)` to call `value.format(...)` on `None`, which raised
`AttributeError` (an uninformative diagnostic) instead of a named, actionable
`ValueError`. The `Engine.spawn` field remains `str` (non-Optional) — the
domain invariant is unchanged; only the parser-side validation timing and
exception type are tightened.

The `Engine(...)` constructor call in `parse_engine_section` SHALL NOT carry
a `# type: ignore[arg-type]` annotation on the `spawn=spawn` argument — the
hoisted `ValueError` raises before the constructor when `spawn` is `None`,
so by the time `Engine(...)` is reached, `spawn` is narrowed to `str`.

The `parse_config` assembly SHALL NOT carry a `cast("Sequence[CloudConfig]",
clouds)` bridge when building the `Config` aggregate — the explicit
DTO→`CloudConfig` Protocol inheritance (per the `cloud-config-dtos` capability)
makes the `Sequence[ConfigCloud] → Sequence[CloudConfig]` assignment typecheck
without a cast.

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

#### Scenario: parse_engine_section raises ValueError on missing spawn
- **WHEN** `parse_engine_section(sec, engines_dir)` is called with a `[engine.fleur]`
  section that omits the `spawn` key (i.e., `sec.get("spawn")` returns `None`)
- **THEN** `ValueError` is raised with a message containing the engine name
  (e.g., `fleur`) and the phrase `has no spawn command`; the `Engine` value
  object is NOT constructed (the exception is raised before the `Engine(...)`
  call)

#### Scenario: parse_engine_section raises ValueError not AttributeError on missing spawn
- **WHEN** the same call as the prior scenario is made
- **THEN** the raised exception is `ValueError` (not `AttributeError`); the
  message is actionable (names the engine and the missing key), replacing
  the prior `AttributeError: 'NoneType' object has no attribute 'format'`
  raised from `_check_spawn(engine, None)` after the `Engine(spawn=None)`
  construction

#### Scenario: Engine constructor call has no type: ignore on spawn
- **WHEN** `parse_engine_section`'s `Engine(...)` constructor call is inspected
- **THEN** the `spawn=spawn` argument does NOT carry a `# type: ignore[arg-type]`
  annotation (the hoisted `ValueError` narrows `spawn` to `str` before the
  constructor is reached)

#### Scenario: parse_config has no cast bridge for clouds
- **WHEN** `parse_config`'s `Config(...)` constructor call is inspected
- **THEN** the `clouds=clouds` argument does NOT carry a
  `cast("Sequence[CloudConfig]", clouds)` wrapper (the explicit
  DTO→Protocol inheritance makes the cast dead weight)
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
DTO→`CloudConfig` Protocol inheritance (per the `cloud-config` capability)
makes the `Sequence[ConfigCloud] → Sequence[CloudConfig]` assignment typecheck
without a cast.

#### Scenario: parse_config round-trips a full INI
- **WHEN** `parse_config(path)` is called with a valid INI containing `[db]`, `[local]`, `[remote]`, `[engine.fleur]`, and `[cloud.hetzner]` sections
- **THEN** the returned `Config` has `db`, `local`, `remote`, `clouds`, `engines` populated with the parsed values

#### Scenario: parse_config warns on unknown keys
- **WHEN** `parse_config(path)` is called with an INI containing an unknown key in `[local]`
- **THEN** a `ConfigWarning` is emitted via `warn_unknown_fields`
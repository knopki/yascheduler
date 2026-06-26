# Cloud Config Parsers

## Purpose

The CLOUD_CONFIG_PARSERS registry and parse_cloud_section / parse_clouds / cloud_valid_fields functions in `yascheduler/entrypoints/config_parser.py` for INI-driven, open/closed cloud provider config assembly.

## Requirements

### Requirement: Cloud config parser registry

The system SHALL define a `CLOUD_CONFIG_PARSERS: dict[str, Callable[[SectionProxy],
CloudConfig]]` registry in `yascheduler/entrypoints/config_parser.py` mapping each
cloud provider prefix (`az`, `hetzner`, `upcloud`, `vastai`) to its parser function.

The registry lives at the composition-root layer (`entrypoints`) so the
`infra → entrypoints` dependency direction stays R3-legal (the registry references
parser functions, which are composition-root concerns; the DTOs live in
`infra/cloud/cloud_configs.py`).

Adding a new cloud provider SHALL require only:
1. Defining a frozen dataclass DTO in `infra/cloud/cloud_configs.py`.
2. Defining a parser function in `entrypoints/config_parser.py`.
3. Registering one entry in `CLOUD_CONFIG_PARSERS`.

No edit to `Config.from_config_parser` (the aggregate root) SHALL be required to add
a provider — the registry is the open/closed seam.

#### Scenario: Registry maps all four provider prefixes
- **WHEN** `CLOUD_CONFIG_PARSERS` is inspected
- **THEN** it contains exactly the keys `az`, `hetzner`, `upcloud`, `vastai` mapped
  to callable parser functions

#### Scenario: Adding a provider does not touch the aggregate root
- **WHEN** a contributor adds a new provider `foo` by adding a `ConfigCloudFoo` DTO, a
  `_parse_foo_section` parser, and a `"foo": _parse_foo_section` registry entry
- **THEN** no edit to `Config.from_config_parser` is required; the new provider's
  `[cloud.foo]` sections round-trip into `Config.clouds` via registry iteration

### Requirement: Cloud section parser functions

The system SHALL define `parse_cloud_section(sec: SectionProxy, prefix: str) ->
CloudConfig` and `parse_clouds(cfg: ConfigParser, remote: ConfigRemote) ->
list[CloudConfig]` in `yascheduler/entrypoints/config_parser.py`.

`parse_clouds` SHALL:
1. Derive `cloud_prefixes` from `[clouds]` section options (splitting each option name
   on `_` and taking the first segment).
2. Inherit `remote.username` into `[clouds]` for any prefix whose `{prefix}_user` key
   is absent (preserving the current `Config.from_config_parser` behavior).
3. For each prefix present in `cloud_prefixes`, dispatch to
   `CLOUD_CONFIG_PARSERS[prefix](cfg["clouds"])` to build the DTO.
4. Return the list of constructed DTOs.

`parse_cloud_section` SHALL dispatch to `CLOUD_CONFIG_PARSERS[prefix]` and return the
parsed DTO. Unknown prefixes raise `KeyError` (the registry is the source of truth for
supported providers).

Validation (`warn_unknown_fields`, `validators.ge(0)`, `validators.ge(1)`,
`_check_az_user`, `opt_str_val`) SHALL run inside the per-prefix parser functions
before constructing the DTO — not in dataclass `__post_init__`.

The per-prefix parser functions (`_parse_azure_section`, `_parse_hetzner_section`,
`_parse_upcloud_section`, `_parse_vastai_section`) and the `cloud_valid_fields(prefix)`
helper (replacing the per-DTO `get_valid_config_parser_fields` classmethods) SHALL be
module-private (prefixed `_` for the parsers; `cloud_valid_fields` is public for test
use) and live in `entrypoints/config_parser.py`.

#### Scenario: parse_clouds dispatches via registry
- **WHEN** `parse_clouds(cfg, remote)` is called with a config parser whose `[clouds]`
  section contains `az_*`, `hetzner_*`, and `vastai_*` keys
- **THEN** `CLOUD_CONFIG_PARSERS["az"]`, `CLOUD_CONFIG_PARSERS["hetzner"]`, and
  `CLOUD_CONFIG_PARSERS["vastai"]` are each called once; the returned list contains
  one `ConfigCloudAzure`, one `ConfigCloudHetzner`, and one `ConfigCloudVastAI` (in
  registry-iteration order)

#### Scenario: parse_clouds inherits remote username
- **WHEN** `parse_clouds(cfg, remote)` is called and `[clouds]` lacks `hetzner_user` but
  `remote.username == "root"`
- **THEN** the parser reads `hetzner_user = "root"` (inherited) when constructing
  `ConfigCloudHetzner`

#### Scenario: parse_cloud_section raises on unknown prefix
- **WHEN** `parse_cloud_section(sec, "unknown")` is called
- **THEN** `KeyError` is raised (the registry has no entry for `unknown`)

#### Scenario: warn_unknown_fields runs parser-side
- **WHEN** `parse_clouds(cfg, remote)` is called with an `[clouds]` section containing
  an unknown key `az_bogus_key`
- **THEN** `warn_unknown_fields` emits a `ConfigWarning` from inside the parser, not
  from a `__post_init__` on the DTO

#### Scenario: VastAI section round-trips via registry
- **WHEN** `parse_clouds(cfg, remote)` is called with a config parser whose `[clouds]`
  section contains `vastai_*` keys
- **THEN** the returned list contains a `ConfigCloudVastAI` instance with
  `prefix == "vastai"` (the registry-driven path; replaces the prior hardcoded
  `cloud_variants` tuple append from P1)

### Requirement: Config.from_config_parser delegates cloud assembly

`Config.from_config_parser` SHALL delegate cloud assembly to `parse_clouds(cfg,
remote)` via a lazy import inside the method (same pattern as the engine-assembly
seam established by P2). The `cloud_variants` tuple, the `cloud_prefixes` derivation,
the username-inheritance loop, and the `cloud_variants_match` filter SHALL be removed
from `Config.from_config_parser` — they move into `parse_clouds`.

The lazy import is documented with a TODO referencing P4 (when `Config` moves to
`entrypoints` and the import becomes intra-package). `Config` stays constructible in
one call — `Config.from_config_parser(path)` returns a fully populated `Config` with
`clouds` populated via the registry.

#### Scenario: Config.from_config_parser calls parse_clouds
- **WHEN** `Config.from_config_parser(path)` is called with a config file containing
  `[clouds]` with `az_*` keys
- **THEN** `parse_clouds(cfg, remote)` is invoked (lazy import) and the resulting
  `list[CloudConfig]` is assigned to `Config.clouds`

#### Scenario: cloud_variants tuple removed
- **WHEN** `config/config.py::Config.from_config_parser` is inspected for the
  `cloud_variants = (ConfigCloudAzure, ...)` tuple
- **THEN** the tuple is absent (replaced by registry iteration inside `parse_clouds`)

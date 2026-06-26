## MODIFIED Requirements

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing:
- `ConfigDb`, `ConfigLocal`, `ConfigRemote` defaults and overrides
- `ConfigLocal` is a stdlib `@dataclass(frozen=True)` with `__post_init__` validation (no attrs dependency, no `get_private_keys` method)
- Cloud config parsing (Hetzner, UpCloud, Azure, VastAI) via the registry-driven
  `parse_clouds` / `parse_cloud_section` functions from
  `yascheduler.entrypoints.config_parser` (not via `ConfigCloudX.from_config_parser_section`
  classmethods, which are removed)
- `ConfigCloud*` DTOs are stdlib `@dataclass(frozen=True)` with no INI-parsing methods
  and no attrs dependency (importable from `yascheduler.infra.cloud`)
- `AzureImageReference.from_urn` rejects malformed URN with `ValueError`
- `ConfigCloudAzure` rejects `username="root"` with `ValueError` (raised parser-side by
  `_check_az_user`, not in `__post_init__`)
- `Engine` rejects unknown spawn placeholders, missing check methods, empty input_files
- `EngineRepository.filter`, `filter_platforms`, immutability
- `Config.from_config_parser` full assembly and empty section defaults
- `Config.from_config_parser` delegates cloud assembly to `parse_clouds(cfg, remote)`
  via lazy import; the `cloud_variants` tuple is removed
- `Config.from_config_parser` recognises `[cloud.vastai]` sections via the
  `CLOUD_CONFIG_PARSERS` registry (regression coverage; the prior P1 band-aid of
  appending to the `cloud_variants` tuple is replaced by the registry path)
- `warn_unknown_fields` emits `ConfigWarning` for unknown keys (called parser-side)

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

#### Scenario: VastAI cloud section round-trips through Config.from_config_parser
- **WHEN** `Config.from_config_parser` is called with a config parser containing a `[cloud.vastai]` section with valid VastAI keys
- **THEN** the resulting `Config.clouds` contains a `ConfigCloudVastAI` instance with `prefix == "vastai"` (routed via `CLOUD_CONFIG_PARSERS["vastai"]`)

#### Scenario: ConfigLocal is a stdlib frozen dataclass without get_private_keys
- **WHEN** `ConfigLocal` is introspected
- **THEN** it is a stdlib `@dataclass(frozen=True)`, has no `get_private_keys` attribute, and retains the `keys_dir: Path` field

#### Scenario: ConfigCloud DTOs are stdlib frozen dataclasses without parser methods
- **WHEN** any `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud`, or
  `ConfigCloudVastAI` is introspected
- **THEN** it is a stdlib `@dataclass(frozen=True)`, has no `from_config_parser_section`
  attribute, has no `get_valid_config_parser_fields` attribute, and raises on field
  assignment after construction

#### Scenario: parse_clouds dispatches via CLOUD_CONFIG_PARSERS registry
- **WHEN** `parse_clouds(cfg, remote)` is called with a config parser whose `[clouds]`
  section contains `az_*` and `hetzner_*` keys
- **THEN** the returned list contains one `ConfigCloudAzure` and one
  `ConfigCloudHetzner`, each constructed via the registry entry for its prefix

#### Scenario: parse_clouds inherits remote username for missing prefix user
- **WHEN** `parse_clouds(cfg, remote)` is called and `[clouds]` lacks `hetzner_user` but
  `remote.username == "root"`
- **THEN** the constructed `ConfigCloudHetzner.username == "root"` (inherited)

#### Scenario: CloudConfig Protocol satisfied structurally by ConfigCloud DTOs
- **WHEN** each of the four `ConfigCloud*` DTOs is constructed with valid fields and
  checked with `isinstance(dto, CloudConfig)` (imported from `yascheduler.domain`)
- **THEN** every check returns `True`

#### Scenario: ConfigCloud DTOs importable from infra cloud facade
- **WHEN** a test imports `from yascheduler.infra.cloud import ConfigCloudAzure,
  ConfigCloudHetzner, ConfigCloudUpcloud, ConfigCloudVastAI, AzureImageReference,
  ConfigCloud`
- **THEN** all six symbols resolve without ImportError (the canonical import path
  after relocation; `from yascheduler.config.cloud import ...` raises ImportError)
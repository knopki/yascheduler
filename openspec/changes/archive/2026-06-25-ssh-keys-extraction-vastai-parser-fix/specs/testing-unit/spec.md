## MODIFIED Requirements

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing:
- `ConfigDb`, `ConfigLocal`, `ConfigRemote` defaults and overrides
- `ConfigLocal` is a stdlib `@dataclass(frozen=True)` with `__post_init__` validation (no attrs dependency, no `get_private_keys` method)
- Cloud config parsing (Hetzner, UpCloud, Azure, VastAI)
- `AzureImageReference.from_urn` rejects malformed URN with `ValueError`
- `ConfigCloudAzure` rejects `username="root"` with `ValueError`
- `Engine` rejects unknown spawn placeholders, missing check methods, empty input_files
- `EngineRepository.filter`, `filter_platforms`, immutability
- `Config.from_config_parser` full assembly and empty section defaults
- `Config.from_config_parser` recognises `[cloud.vastai]` sections and produces a `ConfigCloudVastAI` entry (regression coverage for the previously silently-dropped VastAI section)
- `warn_unknown_fields` emits `ConfigWarning` for unknown keys

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

#### Scenario: VastAI cloud section round-trips through Config.from_config_parser
- **WHEN** `Config.from_config_parser` is called with a config parser containing a `[cloud.vastai]` section with valid VastAI keys
- **THEN** the resulting `Config.clouds` contains a `ConfigCloudVastAI` instance with `prefix == "vastai"`

#### Scenario: ConfigLocal is a stdlib frozen dataclass without get_private_keys
- **WHEN** `ConfigLocal` is introspected
- **THEN** it is a stdlib `@dataclass(frozen=True)`, has no `get_private_keys` attribute, and retains the `keys_dir: Path` field
## MODIFIED Requirements

### Requirement: Config parsing and validation

Tests SHALL verify INI config parsing:
- `ConfigDb`, `ConfigLocal`, `ConfigRemote` defaults and overrides
- Cloud config parsing (Hetzner, UpCloud, Azure)
- `AzureImageReference.from_urn` rejects malformed URN with `ValueError`
- `ConfigCloudAzure` rejects `username="root"` with `ValueError`
- `parse_engines` from `entrypoints/config_parser.py` parses `engine.*`
  sections into an `EngineRepository`, rejecting unknown spawn placeholders,
  missing check methods, and empty `input_files` (parser-side validation)
- `EngineRepository.filter`, `filter_platforms`, immutability (frozen
  dataclass with `Mapping[str, Engine]` data; `filter` returns a new instance;
  no `UserDict`-inherited methods; no `__hash__`; no `engines_dir`)
- `Config.from_config_parser` full assembly and empty section defaults
- `warn_unknown_fields` emits `ConfigWarning` for unknown keys

`Engine` and `EngineRepository` construction and behavior tests SHALL target
`yascheduler.domain` imports (`from yascheduler.domain import Engine,
EngineRepository`), not `yascheduler.config`. Direct
`Engine.from_config_parser_section` / `EngineRepository.from_config_parser`
calls SHALL NOT appear in tests; `parse_engines` / `parse_engine_section`
from `entrypoints/config_parser.py` are the parser entry points.

#### Scenario: AzureImageReference.from_urn rejects malformed URN
- **WHEN** `AzureImageReference.from_urn("bad-urn")` is called
- **THEN** `ValueError` is raised

#### Scenario: parse_engines rejects unknown spawn placeholders
- **WHEN** `parse_engines(cfg, engines_dir)` is called with an `engine.*` section whose `spawn` value contains `{unknown_placeholder}`
- **THEN** `ValueError` is raised by the parser-side `_check_spawn` validator

#### Scenario: parse_engines rejects missing check methods
- **WHEN** `parse_engines(cfg, engines_dir)` is called with an `engine.*` section that sets neither `check_cmd` nor `check_pname`
- **THEN** `ValueError` is raised by the parser-side `_check_check_` validator

#### Scenario: parse_engines rejects empty input_files
- **WHEN** `parse_engines(cfg, engines_dir)` is called with an `engine.*` section whose `input_files` is empty or unset
- **THEN** `ValueError` is raised by the parser-side `_check_at_least_one_elem` validator

#### Scenario: EngineRepository filter returns new instance
- **WHEN** `repo.filter(lambda e: "linux" in e.platforms)` is called on an `EngineRepository` with mixed-platform engines
- **THEN** a new `EngineRepository` is returned containing only matching engines; the original is unchanged

#### Scenario: EngineRepository filter_platforms returns new instance
- **WHEN** `repo.filter_platforms(("linux",))` is called on an `EngineRepository` with mixed-platform engines
- **THEN** a new `EngineRepository` is returned containing only engines with `linux` in their platforms; the original is unchanged

#### Scenario: EngineRepository is immutable
- **WHEN** `repo.data = {}` is attempted on an `EngineRepository` instance
- **THEN** `FrozenInstanceError` is raised (frozen dataclass)

#### Scenario: EngineRepository has no engines_dir field
- **WHEN** an `EngineRepository` instance is inspected for attributes
- **THEN** `hasattr(repo, "engines_dir")` is False

#### Scenario: Engine has no INI parser methods
- **WHEN** `Engine` is inspected for class attributes
- **THEN** `hasattr(Engine, "from_config_parser_section")` is False and `hasattr(Engine, "get_valid_config_parser_fields")` is False
## Purpose

Specification for unit tests covering INI to config parsing across all yascheduler config sub-modules: `ConfigDb`, `ConfigLocal`, `ConfigRemote`, cloud configs (`ConfigCloudHetzner`, `ConfigCloudUpcloud`, `ConfigCloudAzure`, `AzureImageReference`), `Engine`, `EngineRepository`, `warn_unknown_fields`, and top-level `Config.from_config_parser`.

## Requirements

### Requirement: ConfigDb parsing
Tests SHALL verify `ConfigDb.from_config_parser_section` produces correct values from INI section and applies defaults when keys are absent.

#### Scenario: Full config with overrides
- **WHEN** parsed from `[db]\nuser=myuser\npassword=secret\ndatabase=mydb\nhost=db.example.com\nport=5433`
- **THEN** `ConfigDb(user="myuser", password="secret", database="mydb", host="db.example.com", port=5433)`

#### Scenario: Defaults when section is empty
- **WHEN** parsed from `[db]\n`
- **THEN** `ConfigDb(user="yascheduler", password="password", database="database", host="localhost", port=5432)`

### Requirement: ConfigLocal parsing
Tests SHALL verify `ConfigLocal.from_config_parser_section` resolves paths and applies numeric defaults with validation.

#### Scenario: Custom data_dir propagates to derived paths
- **WHEN** parsed from `[local]\ndata_dir=/opt/data`
- **THEN** `tasks_dir`, `engines_dir`, `keys_dir` are resolved under `/opt/data`

#### Scenario: Default values
- **WHEN** parsed from `[local]\n`
- **THEN** all limit fields have expected defaults and paths resolve under `./data`

### Requirement: ConfigRemote parsing
Tests SHALL verify `ConfigRemote.from_config_parser_section` with and without jump host.

#### Scenario: With jump host
- **WHEN** parsed from `[remote]\nuser=admin\njump_user=jumper\njump_host=bastion.example.com`
- **THEN** `username="admin"`, `jump_username="jumper"`, `jump_host="bastion.example.com"`

#### Scenario: Without jump host
- **WHEN** parsed from `[remote]\nuser=root`
- **THEN** `jump_username=None`, `jump_host=None`

### Requirement: Cloud config parsing
Tests SHALL verify parsing for each cloud provider: `ConfigCloudAzure`, `ConfigCloudHetzner`, `ConfigCloudUpcloud` from prefixed INI keys.

#### Scenario: Hetzner config
- **WHEN** parsed from `[clouds]\nhetzner_token=abc123\nhetzner_user=root\n`
- **THEN** `ConfigCloudHetzner(token="abc123", username="root")` with defaults for other fields

#### Scenario: Azure rejects root user
- **WHEN** `ConfigCloudAzure` is constructed with `username="root"`
- **THEN** `ValueError` is raised

#### Scenario: AzureImageReference from URN
- **WHEN** `AzureImageReference.from_urn("Publisher:Offer:SKU:1.0")`
- **THEN** all four fields are set correctly

#### Scenario: AzureImageReference rejects short URN
- **WHEN** `AzureImageReference.from_urn("a:b:c")`
- **THEN** `ValueError` is raised

#### Scenario: Upcloud config
- **WHEN** parsed from `[clouds]\nupcloud_login=user\nupcloud_password=pass\n`
- **THEN** `ConfigCloudUpcloud(login="user", password="pass")` with defaults

### Requirement: Engine parsing and validation
Tests SHALL verify `Engine.from_config_parser_section` parsing and cross-field validators.

#### Scenario: Valid engine
- **WHEN** parsed from a complete `[engine.test]` section with spawn, check_cmd, input_files, output_files
- **THEN** an `Engine` is returned with all fields populated

#### Scenario: Invalid spawn template
- **WHEN** `Engine` spawn contains `{unknown}` placeholder
- **THEN** `ValueError` mentioning the placeholder name is raised

#### Scenario: Missing check methods
- **WHEN** `Engine` is constructed with `check_cmd=None` and `check_pname=None`
- **THEN** `ValueError` is raised

#### Scenario: Empty input_files
- **WHEN** `Engine` is constructed with `input_files=()`
- **THEN** `ValueError` is raised

### Requirement: EngineRepository filtering
Tests SHALL verify `EngineRepository.filter` and `filter_platforms` return new repositories with correct subset.

#### Scenario: Filter by platform
- **WHEN** repository contains engines for "linux" and "windows", filtered by `["linux"]`
- **THEN** only linux engines remain

#### Scenario: Immutability
- **WHEN** `__setitem__` or `__delitem__` is called on EngineRepository
- **THEN** `NotImplementedError` is raised

### Requirement: Config.from_config_parser assembly
Tests SHALL verify the top-level `Config.from_config_parser` assembles all sub-configs from a complete INI file.

#### Scenario: Full config
- **WHEN** parsed from a valid INI with `[db]`, `[local]`, `[remote]`, `[clouds]` sections
- **THEN** `Config` contains correct `ConfigDb`, `ConfigLocal`, `ConfigRemote`, `clouds`, and `engines`

#### Scenario: Empty sections get defaults
- **WHEN** parsed from an INI with only section headers (no keys)
- **THEN** `Config` is still valid with all defaults

### Requirement: warn_unknown_fields emits ConfigWarning
Tests SHALL verify that `warn_unknown_fields` emits a `ConfigWarning` when unknown keys are present.

#### Scenario: Unknown key triggers warning
- **WHEN** a section contains a key not in the known list
- **THEN** `ConfigWarning` is emitted mentioning the unknown field

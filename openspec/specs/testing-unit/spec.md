## Purpose

Requirements for unit tests covering config parsing, data models, and database operations. Tests validate behavioral contracts without external dependencies (no real DB, SSH, or filesystem).

## Requirements

### Requirement: Config sub-module parsing
Tests SHALL verify that each config sub-module (`ConfigDb`, `ConfigLocal`, `ConfigRemote`, cloud configs, `Engine`, `EngineRepository`) correctly parses from INI sections and applies documented defaults when keys are absent.

#### Scenario: Defaults applied when section is empty
- **WHEN** a config sub-module is parsed from a section with no keys
- **THEN** all fields have their documented default values

#### Scenario: Overrides applied from INI keys
- **WHEN** a config sub-module is parsed from a section with explicit keys
- **THEN** fields reflect the provided values

### Requirement: Config validation rules
Tests SHALL verify that config parsing enforces cross-field and single-field validation rules.

#### Scenario: Azure rejects root username
- **WHEN** `ConfigCloudAzure` is constructed with `username="root"`
- **THEN** `ValueError` is raised

#### Scenario: AzureImageReference rejects malformed URN
- **WHEN** `AzureImageReference.from_urn` receives a string with fewer than 4 colon-separated parts
- **THEN** `ValueError` is raised

#### Scenario: Engine rejects invalid spawn template
- **WHEN** `Engine` spawn contains an unrecognized placeholder
- **THEN** `ValueError` mentioning the placeholder name is raised

#### Scenario: Engine requires check method
- **WHEN** `Engine` is constructed with both `check_cmd` and `check_pname` as None
- **THEN** `ValueError` is raised

#### Scenario: Engine requires non-empty input_files
- **WHEN** `Engine` is constructed with `input_files=()`
- **THEN** `ValueError` is raised

### Requirement: EngineRepository filtering and immutability
Tests SHALL verify that `EngineRepository.filter` and `filter_platforms` return new repositories with correct subsets, and that the repository is immutable.

#### Scenario: Filter by platform returns subset
- **WHEN** repository is filtered by platform list
- **THEN** only engines matching requested platforms remain

#### Scenario: EngineRepository is immutable
- **WHEN** `__setitem__` or `__delitem__` is called
- **THEN** `NotImplementedError` is raised

### Requirement: Config top-level assembly
Tests SHALL verify that `Config.from_config_parser` assembles all sub-configs from a complete INI file, and remains valid with empty sections.

#### Scenario: Full assembly from complete INI
- **WHEN** parsed from a valid INI with all required sections
- **THEN** `Config` contains correct sub-configs for db, local, remote, clouds, and engines

#### Scenario: Empty sections produce valid Config
- **WHEN** parsed from an INI with only section headers
- **THEN** `Config` is valid with all defaults

### Requirement: warn_unknown_fields detection
Tests SHALL verify that `warn_unknown_fields` emits `ConfigWarning` for keys not in the known list.

#### Scenario: Unknown key triggers warning
- **WHEN** a section contains a key not in the known list
- **THEN** `ConfigWarning` is emitted mentioning the unknown field

### Requirement: TaskStatus enum values
Tests SHALL verify that `TaskStatus` enum members have correct integer values (`TO_DO=0`, `RUNNING=1`, `DONE=2`) and are `int` subclasses.

#### Scenario: Enum values match expected integers
- **WHEN** `TaskStatus.TO_DO`, `TaskStatus.RUNNING`, `TaskStatus.DONE` are compared to 0, 1, 2
- **THEN** each equality check succeeds and they are `int` instances

### Requirement: TaskModel construction and immutability
Tests SHALL verify that `TaskModel` converts `status` via `TaskStatus` converter, is frozen (raises on attribute assignment), and produces deterministic hashes.

#### Scenario: TaskModel is frozen
- **WHEN** attempting to set an attribute on an existing `TaskModel`
- **THEN** a frozen instance error is raised

#### Scenario: TaskModel hash is deterministic
- **WHEN** two `TaskModel` instances are constructed with identical fields
- **THEN** their hashes are equal

### Requirement: NodeModel defaults
Tests SHALL verify that `NodeModel` provides defaults for `enabled`, `cloud`, `username`, `port`, and is frozen.

#### Scenario: Minimal construction
- **WHEN** `NodeModel` is constructed with only required fields
- **THEN** optional fields have documented default values

### Requirement: DB node and task CRUD
Tests SHALL verify `DB` methods for node and task operations construct correct SQL and map results to `NodeModel`/`TaskModel`, using a mocked connection.

#### Scenario: Node methods map to correct SQL
- **WHEN** `add_node`, `get_node`, `enable_node`, `disable_node`, `remove_node` are called
- **THEN** correct SQL statements are executed and results map to `NodeModel`

#### Scenario: Task status transitions update SQL correctly
- **WHEN** `set_task_running`, `set_task_done`, `set_task_error` are called
- **THEN** SQL correctly updates status and related fields

#### Scenario: set_task_error embeds error in metadata
- **WHEN** `set_task_error` is called with an error message
- **THEN** metadata includes the error key

#### Scenario: set_task_error without error message passes metadata unchanged
- **WHEN** `set_task_error` is called without an error message
- **THEN** metadata is passed without adding an error key

### Requirement: FakeDB protocol-compatible class
A `FakeDB` class SHALL exist in `tests/fixtures/fake_db.py` implementing the same public methods as `DB` on in-memory dicts, returning real `TaskModel`/`NodeModel` objects with auto-incrementing `task_id`.

#### Scenario: FakeDB mirrors DB public methods
- **WHEN** `FakeDB` is used in place of `DB`
- **THEN** `add_task`, `get_task`, `add_node`, `get_all_nodes`, status transition methods all behave equivalently to `DB` for single-value lookups

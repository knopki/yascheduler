## Purpose

Requirements for unit tests covering config parsing, data models, database operations (mocked), remote machine management, and scheduler orchestration. Tests validate behavioral contracts without external dependencies (no real DB, SSH, or filesystem).

## Requirements

### Requirement: Config sub-module parsing
Tests SHALL verify that each config sub-module (`ConfigDb`, `ConfigLocal`, `ConfigRemote`, cloud configs, `Engine`, `EngineRepository`) correctly parses from INI sections, applies documented defaults when keys are absent, and applies explicit overrides.

#### Scenario: Defaults and overrides
- **WHEN** a config sub-module is parsed from an empty section then from a section with explicit keys
- **THEN** defaults are applied first, then overridden by the explicit values

### Requirement: Config validation rules
Tests SHALL verify that config parsing enforces validation rules:
- `ConfigCloudAzure` rejects `username="root"` with `ValueError`
- `AzureImageReference.from_urn` rejects malformed URN (fewer than 4 colon-separated parts) with `ValueError`
- `Engine` rejects unrecognized spawn placeholders with `ValueError` mentioning the placeholder name
- `Engine` rejects construction with both `check_cmd` and `check_pname` as None (`ValueError`)
- `Engine` rejects construction with `input_files=()` (`ValueError`)

#### Scenario: Azure rejects root username
- **WHEN** `ConfigCloudAzure` is constructed with `username="root"`
- **THEN** `ValueError` is raised

### Requirement: EngineRepository filtering and immutability
Tests SHALL verify that `EngineRepository.filter` and `filter_platforms` return new repositories with correct subsets. Repository SHALL be immutable (`__setitem__`/`__delitem__` raise `NotImplementedError`).

#### Scenario: Filter and immutability
- **WHEN** repository is filtered by platform list and mutation is attempted
- **THEN** only matching engines remain in the filtered result, and mutation raises `NotImplementedError`

### Requirement: Config top-level assembly
Tests SHALL verify that `Config.from_config_parser` assembles all sub-configs from a complete INI file and remains valid with empty sections.

#### Scenario: Full assembly from complete INI
- **WHEN** parsed from a valid INI with all required sections
- **THEN** `Config` contains correct sub-configs for db, local, remote, clouds, and engines

### Requirement: warn_unknown_fields detection
Tests SHALL verify that `warn_unknown_fields` emits `ConfigWarning` for keys not in the known list.

#### Scenario: Unknown key triggers warning
- **WHEN** a section contains a key not in the known list
- **THEN** `ConfigWarning` is emitted mentioning the unknown field

### Requirement: TaskStatus and TaskModel
Tests SHALL verify that `TaskStatus` enum members have correct integer values (`TO_DO=0`, `RUNNING=1`, `DONE=2`) and are `int` subclasses. `TaskModel` SHALL convert `status` via `TaskStatus` converter, be frozen (raises on attribute assignment), and produce deterministic hashes.

#### Scenario: Enum values and model immutability
- **WHEN** `TaskStatus` values are compared to 0, 1, 2 and attribute assignment is attempted on `TaskModel`
- **THEN** equality holds, they are `int` instances, and `TaskModel` raises on mutation

### Requirement: NodeModel defaults
Tests SHALL verify that `NodeModel` provides defaults for `enabled`, `cloud`, `username`, `port`, and is frozen.

#### Scenario: Minimal construction
- **WHEN** `NodeModel` is constructed with only required fields
- **THEN** optional fields have documented default values

### Requirement: DB node and task CRUD (mocked)
Tests SHALL verify `DB` methods for node and task operations construct correct SQL and map results to `NodeModel`/`TaskModel`, using a mocked connection.

#### Scenario: set_task_error with and without message
- **WHEN** `set_task_error` is called with an error message
- **THEN** metadata includes the error key
- **WHEN** `set_task_error` is called without an error message
- **THEN** metadata is passed without adding an error key

### Requirement: FakeDB protocol-compatible class
A `FakeDB` class SHALL exist in `tests/fixtures/fake_db.py` implementing the same public methods as `DB` on in-memory dicts, returning real `TaskModel`/`NodeModel` objects with auto-incrementing `task_id`.

#### Scenario: FakeDB mirrors DB public methods
- **WHEN** `FakeDB` is used in place of `DB`
- **THEN** `add_task`, `get_task`, `add_node`, `get_all_nodes`, status transition methods all behave equivalently to `DB`

### Requirement: RemoteMachineMetadata state transitions
Tests SHALL verify that setting `busy=True` sets `free_since=None`, setting `busy=False` sets `free_since` to current time, and initial state has `busy=None` and `free_since` set.

#### Scenario: Busy toggles free_since
- **WHEN** `meta.busy = True` then `meta.busy = False`
- **THEN** after busy=True `free_since` is None; after busy=False `free_since` is a recent datetime

### Requirement: RemoteMachineMetadata.is_free_longer_than
Tests SHALL verify that `is_free_longer_than(delta)` returns True only when machine is not busy AND has been free longer than the given delta. Returns False when busy regardless of delta.

#### Scenario: Free vs busy evaluation
- **WHEN** machine is busy and `is_free_longer_than(timedelta(seconds=0))` is called
- **THEN** result is False even with zero delta

### Requirement: RemoteMachineRepository.filter
Tests SHALL verify filtering by `busy` (True/False), `platforms` (intersection match), `free_since_gt` (duration threshold), and `reverse_sort` (descending by `free_since`). Filter SHALL return a new `RemoteMachineRepository` without modifying the original.

#### Scenario: Filter returns new repository, original unchanged
- **WHEN** `filter(busy=False)` is called on a repository with 2 machines (1 busy, 1 free)
- **THEN** filtered result has 1 machine and original still has 2

### Requirement: OS check functions with mocked SSH
Tests SHALL verify `check_is_linux`, `check_is_debian`, `check_is_debian_like`, `check_is_windows` return correct booleans based on mocked SSH command output. Notably, `check_is_debian` returns False when OS ID is "ubuntu" (not "debian"), even though it's debian-like.

#### Scenario: check_is_debian distinguishes ubuntu from debian
- **WHEN** `_get_os_release(conn)` returns `("ubuntu", "debian", "22.04")`
- **THEN** `check_is_debian(conn)` returns False (ID is "ubuntu", not "debian")

### Requirement: RemoteMachineAdapter structure
Tests SHALL verify that adapter instances (`linux_adapter`, `debian_adapter`, etc.) have correct platform names and non-None callables for all required fields. `debian_adapter.checks` SHALL be a superset of `debian_like_adapter.checks`.

#### Scenario: Adapter chain inheritance
- **WHEN** `debian_adapter` is compared to `debian_like_adapter`
- **THEN** `debian_adapter.checks` is a superset of `debian_like_adapter.checks`

### Requirement: Scheduler constructor and queues
Tests SHALL verify that `Scheduler.__attrs_post_init__` creates 4 `UniqueQueue` instances with correct names and maxsizes derived from `Config.local`.

#### Scenario: Queue configuration
- **WHEN** `Scheduler` is constructed with a Config containing specific limit values
- **THEN** queue maxsizes match the corresponding config fields

### Requirement: create_new_task validation and creation
Tests SHALL verify that `create_new_task` raises `RuntimeError` for unknown engine names and missing input files. On success, it SHALL call `db.add_task` with status `TO_DO`, include engine name in metadata, call `db.update_task_meta` with `remote_folder`, commit, and return a `TaskModel`.

#### Scenario: Successful task creation
- **WHEN** `create_new_task` is called with valid label, metadata containing all input files, and a known engine
- **THEN** `db.add_task` is called with status `TO_DO`, metadata contains `"engine"` key, `db.update_task_meta` is called with `remote_folder`, and a `TaskModel` is returned

### Requirement: allocate_task
Tests SHALL verify that `allocate_task` picks the first free machine with matching platform, sets task RUNNING in DB. Edge cases:
- No free matching machine → `clouds.allocate` is called, returns False
- Unknown engine in task metadata → `db.set_task_error` called with error about unsupported engine

#### Scenario: No free machine triggers cloud allocation
- **WHEN** no free machine matches the engine's platform requirements
- **THEN** `clouds.allocate` is called with the task_id and engine platforms, and method returns False

### Requirement: clouds_get_capacity calculation
Tests SHALL verify that `clouds_get_capacity` returns `max_nodes - busy_nodes`, floored at 0 (never negative).

#### Scenario: Over capacity floors to zero
- **WHEN** total max_nodes=10, current busy=12
- **THEN** `clouds_get_capacity()` returns 0

### Requirement: WebhookPayload
`WebhookPayload` SHALL hold `task_id`, `status`, and `custom_params` fields.

#### Scenario: Construction
- **WHEN** `WebhookPayload(task_id=1, status=0, custom_params={"k": "v"})`
- **THEN** all fields are accessible and match

### Requirement: Scheduler mock fixtures
The project SHALL provide mock fixtures for `RemoteMachine` (configurable meta, platforms, hostname) and `CloudAPIManager` (stubbed allocate/deallocate/get_capacity/mark_task_done) in `tests/fixtures/`.

#### Scenario: Mock RemoteMachine and CloudAPIManager
- **WHEN** `make_mock_remote_machine` and `make_mock_clouds` are called
- **THEN** spec-compliant mocks with configurable behavior are returned

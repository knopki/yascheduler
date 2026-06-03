## ADDED Requirements

### Requirement: Scheduler constructor sets up queues
Tests SHALL verify that `Scheduler.__attrs_post_init__` creates 4 `UniqueQueue` instances with correct names and maxsizes derived from `Config.local`.

#### Scenario: Queue configuration
- **WHEN** `Scheduler` is constructed with a Config containing specific limit values
- **THEN** `conn_machine_q.maxsize`, `allocate_q.maxsize`, `consume_q.maxsize`, `deallocate_q.maxsize` match the corresponding config fields

### Requirement: create_new_task validates engine
Tests SHALL verify that `create_new_task` raises `RuntimeError` for unknown engine names and for missing input files.

#### Scenario: Unknown engine
- **WHEN** `create_new_task(label="t", metadata={}, engine_name="nonexistent")`
- **THEN** `RuntimeError` is raised mentioning the engine name

#### Scenario: Missing input file
- **WHEN** `create_new_task` is called with an engine requiring `"input.txt"` but metadata lacks it
- **THEN** `RuntimeError` is raised mentioning the missing file

### Requirement: create_new_task creates task with correct metadata
Tests SHALL verify that `create_new_task` calls `db.add_task` with the engine name in metadata, updates metadata with `remote_folder`, commits, and returns the task.

#### Scenario: Successful task creation
- **WHEN** `create_new_task` is called with valid label, metadata containing all input files, and a known engine
- **THEN** `db.add_task` is called with status `TO_DO`, metadata contains `"engine"` key, `db.update_task_meta` is called with `remote_folder`, `db.commit` is called, and a `TaskModel` is returned

### Requirement: allocate_task selects free compatible machine
Tests SHALL verify that `allocate_task` picks the first free machine with matching platform, starts the task, sets it RUNNING in DB, and triggers webhook.

#### Scenario: Free machine with matching platform
- **WHEN** a task with engine requiring `["linux"]` platform exists, a free linux machine is available, and no other RUNNING tasks
- **THEN** `db.set_task_running` is called with the task_id and machine IP, and `clouds.mark_task_done` is called

#### Scenario: No free machine triggers cloud allocation
- **WHEN** no free machine matches the engine's platform requirements
- **THEN** `clouds.allocate` is called with the task_id and engine platforms, and method returns False

### Requirement: allocate_task handles unsupported engine
Tests SHALL verify that `allocate_task` marks the task as error when engine is unknown.

#### Scenario: Engine not in config
- **WHEN** task metadata has `engine="nonexistent"`
- **THEN** `db.set_task_error` is called with error message about unsupported engine

### Requirement: clouds_get_capacity calculation
Tests SHALL verify that `clouds_get_capacity` returns the difference between max_nodes and current busy nodes, floored at 0.

#### Scenario: Capacity available
- **WHEN** total max_nodes=20, current busy=5
- **THEN** `clouds_get_capacity()` returns 15

#### Scenario: Over capacity
- **WHEN** total max_nodes=10, current busy=12
- **THEN** `clouds_get_capacity()` returns 0

### Requirement: WebhookPayload dataclass
Tests SHALL verify `WebhookPayload` holds task_id, status, and custom_params fields.

#### Scenario: Construction
- **WHEN** `WebhookPayload(task_id=1, status=0, custom_params={"k": "v"})`
- **THEN** all fields are accessible and match

### Requirement: Scheduler mock fixtures
The project SHALL provide mock fixtures for `RemoteMachine` (with configurable meta, platforms, hostname) and `CloudAPIManager` (with stubbed allocate/deallocate/get_capacity/mark_task_done) in `tests/fixtures/`.

#### Scenario: Mock RemoteMachine
- **WHEN** `make_mock_remote_machine(ip="10.0.0.1", platforms=["linux"], busy=False)` is called
- **THEN** a MagicMock(spec=RemoteMachine) is returned with `.meta.busy=False`, `.platforms=["linux"]`, `.hostname` set

#### Scenario: Mock CloudAPIManager
- **WHEN** `make_mock_clouds()` is called
- **THEN** an AsyncMock is returned with `allocate`, `deallocate`, `get_capacity`, `mark_task_done` stubs

## ADDED Requirements

### Requirement: DB delegates to repositories internally

The system SHALL refactor `DB` methods to call `PostgresTaskRepository`
and `PostgresNodeRepository` internally, while preserving the external
API unchanged.

#### Scenario: get_task returns TaskModel
- **WHEN** `db.get_task(42)` is called by existing code
- **THEN** returns a `TaskModel` (attrs) as before, but internally the
  repository returned a `Task` (dataclass) which was converted

#### Scenario: add_node persists via repository
- **WHEN** `db.add_node(...)` is called with NodeModel-compatible arguments
- **THEN** the node is saved via `PostgresNodeRepository.add()`

#### Scenario: set_task_running updates status
- **WHEN** `db.set_task_running(42, "10.0.0.1")` is called
- **THEN** the task status is RUNNING and IP is set; internally uses
  `TaskRepository.save()` after fetching the task

### Requirement: DB API surface unchanged

The system SHALL preserve all existing public methods of `DB` with the
same signatures: `get_task`, `get_tasks_by_status`, `get_tasks_by_jobs`,
`add_task`, `update_task_meta`, `set_task_running`, `set_task_done`,
`set_task_error`, `get_node`, `get_enabled_nodes`, `get_disabled_nodes`,
`get_all_nodes`, `add_node`, `add_tmp_node`, `enable_node`, `disable_node`,
`remove_node`, `count_nodes_clouds`, `count_nodes_by_status`,
`count_tasks_by_status`, `commit`, `migrate`.

#### Scenario: Existing scheduler code compiles unchanged
- **WHEN** `scheduler.py` calls `self.db.get_tasks_by_status((TaskStatus.RUNNING,))`
- **THEN** the call succeeds with the same return type

### Requirement: Old↔new model conversion at boundary

The system SHALL convert between old attrs models (`TaskModel`, `NodeModel`)
and new domain types (`Task`, `Node`) only within `db.py` conversion methods.

#### Scenario: TaskModel to Task conversion
- **WHEN** a `TaskModel(attrs)` with task_id=1, status=TO_DO, metadata={"engine":"fleur"} is converted
- **THEN** a `Task(dataclass)` is returned with `context.engine="fleur"` and matching fields

#### Scenario: Task to TaskModel conversion
- **WHEN** a `Task(dataclass)` with task_id=1, status=RUNNING, context.engine="fleur" is converted
- **THEN** a `TaskModel(attrs)` is returned with `metadata` dict containing `"engine": "fleur"`

#### Scenario: NodeModel to Node conversion
- **WHEN** a `NodeModel(ip="10.0.0.1", ncpus=4, enabled=True, cloud="azure")` is converted
- **THEN** a `Node(dataclass)` is returned with matching fields

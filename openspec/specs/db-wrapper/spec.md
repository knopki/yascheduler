# db-wrapper

## Purpose

DB class wraps persistence adapter repositories while preserving backward-compatible public API.

## Requirements

### Requirement: DB provides task and node CRUD

The system SHALL provide a `DB` class with async methods for task and node
persistence. All methods return attrs-based models (`TaskModel`, `NodeModel`)
and accept the same parameter types as the original API.

Task methods: `get_task`, `get_tasks_by_status`, `get_tasks_by_jobs`,
`add_task`, `update_task_meta`, `update_task_status`, `set_task_running`,
`set_task_done`, `set_task_error`, `count_tasks_by_status`,
`get_task_ids_by_ip_and_status`, `get_tasks_with_cloud_by_id_status`.

Node methods: `get_node`, `get_enabled_nodes`, `get_disabled_nodes`,
`get_all_nodes`, `has_node`, `add_node`, `add_tmp_node`, `enable_node`,
`disable_node`, `remove_node`, `count_nodes_clouds`, `count_nodes_by_status`.

Lifecycle methods: `commit`, `migrate`, `close`.

#### Scenario: Existing scheduler code compiles unchanged
- **WHEN** `scheduler.py` calls `self.db.get_tasks_by_status((TaskStatus.RUNNING,))`
- **THEN** the call succeeds with the same return type

#### Scenario: set_task_running updates status and IP
- **WHEN** `db.set_task_running(42, "10.0.0.1")` is called
- **THEN** the task status is RUNNING and IP is set

#### Scenario: set_task_error with and without message
- **WHEN** `set_task_error` is called with an error message
- **THEN** metadata includes the error key
- **WHEN** `set_task_error` is called without an error message
- **THEN** metadata is passed without adding an error key

#### Scenario: add_tmp_node generates provisional IP
- **WHEN** `db.add_tmp_node("az", "root")` is called
- **THEN** a disabled node is created with a generated IP

### Requirement: TaskModel and NodeModel are immutable attrs

`TaskModel` SHALL be frozen with fields: `task_id`, `label`, `ip`, `status`
(converted via `TaskStatus` converter), `metadata` (Mapping), `cloud`.
It SHALL produce deterministic hashes.

`NodeModel` SHALL be frozen with fields: `ip`, `ncpus`, `enabled`, `cloud`,
`username`, `port`, with documented defaults (`enabled=True`, `cloud=None`,
`username="root"`, `port=22`).

#### Scenario: TaskModel immutability and hashing
- **WHEN** attribute assignment is attempted on `TaskModel`
- **THEN** an exception is raised

#### Scenario: NodeModel defaults
- **WHEN** `NodeModel` is constructed with only required fields
- **THEN** optional fields have documented default values

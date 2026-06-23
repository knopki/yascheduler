## MODIFIED Requirements

### Requirement: DB provides task and node CRUD

The system SHALL provide a `DB` class with async methods for task and node
persistence. All methods return attrs-based models (`TaskModel`,
`NodeModel`) and accept the same parameter types as the original API.

Task methods: `get_task`, `get_tasks_by_status`, `get_tasks_by_jobs`,
`add_task`, `update_task_meta`, `update_task_status`, `set_task_running`,
`set_task_done`, `set_task_error`, `count_tasks_by_status`,
`get_task_ids_by_ip_and_status`, `get_tasks_with_cloud_by_id_status`.

Node methods: `get_node`, `get_enabled_nodes`, `get_disabled_nodes`,
`get_all_nodes`, `has_node`, `add_node`, `add_tmp_node`, `enable_node`,
`disable_node`, `remove_node`, `count_nodes_clouds`, `count_nodes_by_status`.

Lifecycle methods: `commit`, `migrate`, `close`.

The `DB` class SHALL remain present for backward compatibility with
existing test fixtures and any external consumers, but SHALL have zero
production callers after the `client-query-uow` change. Production code
paths SHALL route through `PostgresUnitOfWork` and the repository adapters
directly. The eventual full removal of `yascheduler/db.py` is tracked as
a separate follow-up proposal (test-fixture migration first).

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

#### Scenario: Production code does not instantiate DB
- **WHEN** the `yascheduler/` package (excluding `yascheduler/db.py` itself) is inspected after the change lands
- **THEN** no module calls `DB.create(...)` at runtime and no module imports `DB` or `TaskStatus` from `yascheduler.db`; only test modules under `tests/` retain such imports (pending the test-fixture migration follow-up)

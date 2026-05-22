## Purpose

Specification for unit tests covering the `DB` class from `yascheduler/db.py` with mocked `pg8000.Connection`, verifying SQL queries, parameter binding, and result mapping. Includes specification for the `FakeDB` protocol-compatible in-memory class.

## Requirements

### Requirement: DB node CRUD with mocked connection
Tests SHALL verify `DB` node methods (`add_node`, `get_node`, `get_all_nodes`, `enable_node`, `disable_node`, `remove_node`) construct correct SQL and map results to `NodeModel`, using a mocked `pg8000.Connection`.

#### Scenario: add_node returns NodeModel
- **WHEN** `db.add_node("10.0.0.1", "root")` is called with mock connection
- **THEN** `INSERT INTO yascheduler_nodes` SQL is executed and a `NodeModel` with matching fields is returned

#### Scenario: get_node returns NodeModel when found
- **WHEN** `db.get_node("10.0.0.1")` and mock returns a matching row
- **THEN** a `NodeModel` with the row data is returned

#### Scenario: get_node returns None when not found
- **WHEN** `db.get_node("10.0.0.1")` and mock returns None/empty
- **THEN** `None` is returned

#### Scenario: enable_node executes UPDATE
- **WHEN** `db.enable_node("10.0.0.1")` is called
- **THEN** `UPDATE yascheduler_nodes SET enabled=TRUE` SQL is executed with correct IP parameter

### Requirement: DB task CRUD with mocked connection
Tests SHALL verify `DB` task methods (`add_task`, `get_task`, `update_task_status`, `set_task_running`, `set_task_done`, `set_task_error`) construct correct SQL and map results to `TaskModel`.

#### Scenario: add_task inserts and returns TaskModel
- **WHEN** `db.add_task(label="calc", ip_addr="10.0.0.1")` is called with mock returning a row
- **THEN** `INSERT INTO yascheduler_tasks` SQL is executed and a `TaskModel` is returned

#### Scenario: set_task_running updates status and IP
- **WHEN** `db.set_task_running(42, "10.0.0.1")` is called
- **THEN** SQL sets `status=1` and `ip="10.0.0.1"` for task_id 42

#### Scenario: set_task_error embeds error in metadata
- **WHEN** `db.set_task_error(42, {"key": "val"}, "crash")` is called
- **THEN** SQL sets `status=2` and metadata includes both original keys and `"error": "crash"`

#### Scenario: set_task_error without error message
- **WHEN** `db.set_task_error(42, {"key": "val"})` is called
- **THEN** metadata is passed unchanged (no error key added)

### Requirement: FakeDB protocol-compatible class
A `FakeDB` class SHALL be created in `tests/fixtures/fake_db.py` that implements the same public methods as `DB` but operates on in-memory dicts. It SHALL return real `TaskModel`/`NodeModel` objects and auto-increment `task_id`.

#### Scenario: FakeDB add_task and get_task
- **WHEN** `fake_db.add_task(label="test")` then `fake_db.get_task(1)`
- **THEN** a `TaskModel` with `task_id=1, label="test"` is returned

#### Scenario: FakeDB add_node and get_all_nodes
- **WHEN** two nodes are added via `fake_db.add_node()`
- **THEN** `get_all_nodes()` returns both as `NodeModel` instances

#### Scenario: FakeDB status transitions
- **WHEN** `fake_db.add_task()`, `fake_db.set_task_running()`, `fake_db.set_task_done()`
- **THEN** `get_task()` reflects each status change correctly

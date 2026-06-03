## ADDED Requirements

### Requirement: pytest configuration in pyproject.toml
The project SHALL declare pytest configuration under `[tool.pytest.ini_options]` in `pyproject.toml` with `asyncio_mode = "auto"`, `testpaths = ["tests/unit"]`, and marker definitions for `unit`, `integration`, and `e2e`.

#### Scenario: Default pytest run executes only unit tests
- **WHEN** developer runs `pytest` without arguments
- **THEN** only tests under `tests/unit/` are discovered and executed

#### Scenario: Integration tests run explicitly
- **WHEN** developer runs `pytest tests/integration/`
- **THEN** tests under `tests/integration/` are discovered and executed

### Requirement: test dependency declarations
The project SHALL declare test dependencies in `[dependency-groups].dev` in `pyproject.toml`: `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock`, and `testcontainers[postgres]`.

#### Scenario: Developer installs test dependencies
- **WHEN** developer runs `uv sync --group dev`
- **THEN** all test dependencies are installed and `pytest` is available

### Requirement: test directory structure
The project SHALL contain a `tests/` directory with subdirectories `unit/`, `integration/`, and `e2e/`, each containing an `__init__.py` to mark them as packages.

#### Scenario: Test directories exist
- **WHEN** the project is checked out
- **THEN** `tests/unit/`, `tests/integration/`, and `tests/e2e/` directories exist

### Requirement: shared conftest with test data helpers
The project SHALL provide a `tests/conftest.py` with shared fixtures and a `tests/fixtures/` directory containing helper functions for creating test data models (`make_task`, `make_node`).

#### Scenario: Test creates a TaskModel with defaults
- **WHEN** a test calls `make_task()`
- **THEN** a valid `TaskModel` is returned with sensible default values

#### Scenario: Test creates a TaskModel with overrides
- **WHEN** a test calls `make_task(task_id=42, label="custom")`
- **THEN** a `TaskModel` is returned with `task_id=42` and `label="custom"`, other fields at defaults

#### Scenario: Test creates a NodeModel with overrides
- **WHEN** a test calls `make_node(ip="10.0.0.1", ncpus=8)`
- **THEN** a `NodeModel` is returned with the specified values

### Requirement: queue.py unit tests
The project SHALL include unit tests for `UniqueQueue` in `tests/unit/test_queue.py` covering: put/get, deduplication, item_done tracking, psize, and task_done NotImplementedError.

#### Scenario: Put and get a message
- **WHEN** a `UMessage` is put into a `UniqueQueue` and then gotten
- **THEN** the retrieved message equals the original

#### Scenario: Duplicate message is skipped
- **WHEN** the same `UMessage` is put twice into a `UniqueQueue`
- **THEN** only one message is in the queue

#### Scenario: item_done removes from pending
- **WHEN** a message is gotten and then `item_done` is called with it
- **THEN** `psize()` returns 0 and the same message can be put again

#### Scenario: task_done raises NotImplementedError
- **WHEN** `task_done()` is called on a `UniqueQueue`
- **THEN** `NotImplementedError` is raised

## Purpose

Defines the testing infrastructure: pytest configuration, directory structure, shared fixtures, CI workflow, and unit tests for internal utilities.

## Requirements

### Requirement: pytest configuration in pyproject.toml
The project SHALL declare pytest configuration under `[tool.pytest.ini_options]` in `pyproject.toml`, with `testpaths` pointing to `tests/unit/` so that a bare `pytest` run executes only unit tests.

#### Scenario: Default pytest run executes only unit tests
- **WHEN** developer runs `pytest` without arguments
- **THEN** only tests under `tests/unit/` are discovered and executed

#### Scenario: Integration tests run explicitly
- **WHEN** developer runs `pytest tests/integration/`
- **THEN** tests under `tests/integration/` are discovered and executed

### Requirement: test directory structure
The project SHALL contain a `tests/` directory with subdirectories `unit/`, `integration/`, and `e2e/`, each containing an `__init__.py`.

#### Scenario: Test directories exist
- **WHEN** the project is checked out
- **THEN** `tests/unit/`, `tests/integration/`, and `tests/e2e/` directories exist with `__init__.py`

### Requirement: shared conftest with test data helpers
The project SHALL provide a `tests/conftest.py` with shared fixtures and a `tests/fixtures/` directory containing helper functions for creating test data models (`make_task`, `make_node`).

#### Scenario: Test creates a TaskModel with defaults
- **WHEN** a test calls `make_task()`
- **THEN** a valid `TaskModel` is returned with sensible default values

### Requirement: UniqueQueue unit tests
The project SHALL include unit tests for `UniqueQueue` covering: put/get, deduplication, item_done tracking, and task_done NotImplementedError.

#### Scenario: Duplicate message is skipped
- **WHEN** the same `UMessage` is put twice into a `UniqueQueue`
- **THEN** only one message is in the queue

#### Scenario: item_done allows re-queueing
- **WHEN** a message is gotten and then `item_done` is called with it
- **THEN** `psize()` reflects the removal and the same message can be put again

### Requirement: CI unit test workflow
The project SHALL include a GitHub Actions workflow triggered on push and pull request events that runs unit tests via `pytest`. The CI workflow SHALL NOT execute integration or e2e tests.

#### Scenario: Push triggers CI
- **WHEN** a commit is pushed to any branch
- **THEN** the CI workflow runs unit tests

#### Scenario: Integration tests excluded from CI
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute

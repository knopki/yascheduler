## Purpose

Testing infrastructure: pytest configuration, directory structure, shared fixtures, CI workflow, and utility tests.

## Requirements

### Requirement: pytest configuration
The project SHALL declare pytest configuration under `[tool.pytest.ini_options]` in `pyproject.toml`, with `testpaths` pointing to `tests/unit/`. Integration and e2e tests run via explicit paths only.

#### Scenario: Default pytest run executes only unit tests
- **WHEN** developer runs `pytest` without arguments
- **THEN** only tests under `tests/unit/` are discovered and executed

### Requirement: Test directory structure
`tests/` SHALL contain `unit/`, `integration/`, and `e2e/` subdirectories, each with `__init__.py`.

#### Scenario: Test directories exist
- **WHEN** the project is checked out
- **THEN** `tests/unit/`, `tests/integration/`, and `tests/e2e/` directories exist with `__init__.py`

### Requirement: Shared test data helpers
`tests/conftest.py` SHALL provide shared fixtures. `tests/fixtures/` SHALL contain helper functions (`make_task`, `make_node`) for creating test data models with sensible defaults.

#### Scenario: Test creates a TaskModel with defaults
- **WHEN** a test calls `make_task()`
- **THEN** a valid `TaskModel` is returned with sensible default values

### Requirement: UniqueQueue unit tests
Tests for `UniqueQueue` SHALL cover: put/get, deduplication (same `UMessage` put twice → only one in queue), item_done tracking (allows re-queueing after done), and `task_done` raising `NotImplementedError`.

#### Scenario: Duplicate message is skipped
- **WHEN** the same `UMessage` is put twice into a `UniqueQueue`
- **THEN** only one message is in the queue

### Requirement: CI unit test workflow
A GitHub Actions workflow triggered on push and pull request SHALL run unit tests via `pytest`. CI SHALL NOT execute integration or e2e tests.

#### Scenario: CI excludes integration tests
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute

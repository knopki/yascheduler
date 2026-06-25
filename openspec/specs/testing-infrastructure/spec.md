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
Tests for `UniqueQueue` SHALL cover: put/get, deduplication, item_done
tracking (allows re-queueing after done), and `task_done` raising
`NotImplementedError`.

Deduplication in `UniqueQueue` SHALL be keyed on the message `id`. Two
`UMessage` instances with equal `id` SHALL be treated as duplicates regardless
of their `payload`. The `payload` field SHALL NOT participate in `__eq__` or
`__hash__`; therefore an unhashable `payload` (e.g. a `dict`) SHALL be
accepted at construction and during enqueue/get/item_done operations.

#### Scenario: Duplicate message is skipped
- **WHEN** two `UMessage` instances with the same `id` are put into a `UniqueQueue`
- **THEN** only one message is in the queue

#### Scenario: Different payloads with the same id are deduplicated
- **WHEN** `UMessage(id="a", payload="x")` and `UMessage(id="a", payload="y")` (same id, different payloads) are both put into a `UniqueQueue`
- **THEN** the queue size is 1, and the retained message is the first one inserted (payload `"x"`)

#### Scenario: Unhashable payload is accepted
- **WHEN** a `UMessage` is constructed with an unhashable payload (e.g. a `dict`) and put into a `UniqueQueue`, then consumed via `get`, then `item_done` is called
- **THEN** no exception is raised during construction, put, get, or item_done

### Requirement: CI unit test workflow
A GitHub Actions workflow triggered on push and pull request SHALL run unit tests via `pytest`. CI SHALL NOT execute integration or e2e tests.

#### Scenario: CI excludes integration tests
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute

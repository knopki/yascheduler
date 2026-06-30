## MODIFIED Requirements

### Requirement: Client queue-submit characterization

Tests SHALL verify that `Yascheduler.queue_submit_task_async` (implemented in
`yascheduler/entrypoints/client.py`; re-exported by the `yascheduler/client.py`
compat shim) submits a task through the composition root's `make_cli_deps()`
factory and does not instantiate the daemon graph. Specifically,
`queue_submit_task_async` MUST call
`make_cli_deps(config).submit(label, metadata, engine_name)` and return its result.

#### Scenario: Yascheduler.queue_submit_task_async uses make_cli_deps
- **WHEN** `Yascheduler().queue_submit_task_async(label="t", metadata={"k": "v"}, engine_name="fleur")` is called with `make_cli_deps` patched to return a mock `CLIDeps` whose `submit` is an `AsyncMock`
- **THEN** `make_cli_deps` is called once with the client's `config`, `deps.submit` is awaited once with `("t", {"k": "v"}, "fleur")`, and the awaited return value is returned to the caller

### Requirement: Client queue-query unit verification

Tests SHALL verify that `Yascheduler.queue_get_tasks_async` (implemented in
`yascheduler/entrypoints/client.py`; re-exported by the `yascheduler/client.py`
compat shim) routes queries through the `deps_factory`-injected `CLIDeps.uow_factory`
and the `query_tasks` use case, then maps results to the public six-key dict shape.
Tests SHALL construct the client with a `FakeCLIDeps`-returning `deps_factory` whose
`uow_factory()` returns a `FakeUnitOfWork` carrying a `FakeTaskRepository`.

#### Scenario: Status filter dispatches list_by_status
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(status=[0])` is called with `FakeTaskRepository.list_by_status` seeded to return a known Task
- **THEN** `list_by_status({domain.TaskStatus.TO_DO})` is awaited and the returned dict has exactly the keys `{task_id, label, ip, status, metadata, cloud}`

#### Scenario: Jobs filter dispatches list_by_jobs
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(jobs=[7])` is called
- **THEN** `list_by_jobs([7])` is awaited on the fake repository and results mapped to the six-key shape

#### Scenario: Both filters supplied raises ValueError
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(jobs=[1], status=[0])` is called
- **THEN** `ValueError` is raised

#### Scenario: Neither filter returns empty list
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async()` is called with no arguments
- **THEN** `[]` is returned without dispatching to the repository

#### Scenario: Returned dict shape and types are correct
- **WHEN** a Task with `allocated_ip=None` is seeded into the fake repository and queried
- **THEN** the returned dict has `ip == ""`, `status` is `isinstance(status, domain.TaskStatus)` (not a plain int), and `cloud is None`

## ADDED Requirements

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

### Requirement: CI unit test workflow

A GitHub Actions workflow triggered on push and pull request SHALL run unit tests via `pytest`. CI SHALL NOT execute integration or e2e tests.

#### Scenario: CI excludes integration tests
- **WHEN** the CI workflow runs
- **THEN** only tests under `tests/unit/` execute

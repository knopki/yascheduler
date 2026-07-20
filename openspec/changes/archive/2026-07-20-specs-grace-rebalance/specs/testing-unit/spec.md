## MODIFIED Requirements

### Requirement: Client queue-query unit verification

Tests SHALL verify that `Yascheduler.queue_get_tasks_async` routes queries
through the `deps_factory`-injected `CLIDeps.uow_factory` and the
`query_tasks` use case, then maps results to the public six-key dict shape
`{task_id, label, status, metadata, node}` with the nested `node` object
(carrying `hostname`, not `ip`).

#### Scenario: Status filter dispatches list_by_status
- **WHEN** `Yascheduler(deps_factory=...).queue_get_tasks_async(status=[0])` is called with `FakeTaskRepository.list_by_status` seeded to return a known Task
- **THEN** `list_by_status({domain.TaskStatus.TO_DO})` is awaited and the returned dict has exactly the keys `{task_id, label, status, metadata, node}` (the flat `ip` and `cloud` keys are ABSENT)

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
- **WHEN** a Task with `allocated_node_id=None` is seeded into the fake repository and queried
- **THEN** the returned dict has `node == None`, `status` is `isinstance(status, domain.TaskStatus)` (not a plain int), and the flat `ip` / `cloud` keys are ABSENT

## REMOVED Requirements

### Requirement: Logging discipline guard test duplication

REMOVED from `testing-unit` — the contract text (no injected logger, no
extra-key collision with native `LogRecord` attributes) is owned by the
`logging` capability. The `testing-unit` capability retains ONE reference
scenario (added below) naming the two guards; the duplicated contract text
and per-collaborator enumeration (`Orchestrator`, `SSHMachineRepository`,
`SSHMachineSession`, `TaskDeployer`, `OutputDownloader`, `OccupancyChecker`,
`CloudProvisionerImpl`) are removed.

The exhaustive collaborator list lives in each collaborator's
`CLASS_*` GRACE region; the spec keeps only the behavioral rule "no
collaborator accepts an injected logger; no `extra` key collides with a
native `LogRecord` attribute".

## ADDED Requirements

### Requirement: Logging discipline guard tests (reference)

The project SHALL provide two guard unit tests in `tests/unit/` that
statically enforce the logging contract owned by the `logging` capability:
(a) no collaborator class accepts a `log` parameter in its `__init__`, and
(b) no `extra={...}` literal callsite in `yascheduler/` uses a key that
collides with a native `LogRecord` attribute. The guard tests SHALL run
under the `unit` pytest marker without external resources.

The exhaustive collaborator list and the exhaustive `LogRecord` attribute
set live in code (`CLASS_*` regions and the formatter module's
`MODULE_CONTRACT` respectively) — the spec keeps only the behavioral rule.

#### Scenario: guard tests pass on the committed package

- **GIVEN** the committed `yascheduler/` package
- **WHEN** the guard tests are run via `uv run pytest -m unit`
- **THEN** both pass (no `log` parameters in collaborator `__init__` methods and no `extra`-key collisions with native `LogRecord` attributes exist in the committed package)

#### Scenario: guard tests run under the unit marker without external resources

- **WHEN** the guard tests are run via `uv run pytest -m unit`
- **THEN** both pass without a database, SSH container, or cloud credentials

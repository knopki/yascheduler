## MODIFIED Requirements

### Requirement: Shared test fixtures

The project SHALL provide spec-compliant mock factories in
`tests/fixtures/mock_remote_machine.py` and `tests/fixtures/mock_clouds.py`.
The `tests/fixtures/models.py` module (`make_task` / `make_node` returning
legacy `TaskModel` / `NodeModel`) is removed; tests SHALL construct domain
entities directly (`yascheduler.domain.Task`, `yascheduler.domain.Node`) or
via local helpers in each test file.

#### Scenario: Domain entities constructed directly in tests
- **WHEN** a unit test needs a `Task` or `Node` instance
- **THEN** it constructs `yascheduler.domain.Task(...)` / `yascheduler.domain.Node(...)` directly (or via a file-local helper), not via a deleted `make_task`/`make_node` fixture

## REMOVED Requirements

### Requirement: Legacy DB models (TaskModel, NodeModel, TaskStatus)
**Reason**: `TaskModel`, `NodeModel`, and the legacy `TaskStatus` shim in
`yascheduler.db` are deleted with the module. The canonical
`yascheduler.domain.TaskStatus` IntEnum (TO_DO=0, RUNNING=1, DONE=2) and
the frozen `Task`/`Node` dataclasses remain and are already covered by the
domain entities lifecycle requirement.
**Migration**: Tests SHALL use `yascheduler.domain.TaskStatus`,
`yascheduler.domain.Task`, and `yascheduler.domain.Node`. `Task` field names
differ from the legacy `TaskModel`: `allocated_ip` (not `ip`), `context`
(not `metadata`). Domain model behavior is verified by the existing domain
entities lifecycle requirement (`test_domain_model.py`).

### Requirement: DB facade with mocked connection
**Reason**: The `DB` class is removed. Unit-testing its methods with a mocked
pg8000 connection is no longer meaningful — the repository adapters
(`PostgresTaskRepository`, `PostgresNodeRepository`, `PostgresUnitOfWork`)
are the persistence subject and are covered by the persistence-adapter
requirement (mocked) and the integration suite (real Postgres).
**Migration**: No direct replacement. Repository/UoW behavior is verified by
the "Persistence adapter with mocked pg8000" requirement and the integration
spec `test-db-integration`.

### Requirement: FakeDB test double
**Reason**: `FakeDB` was an in-memory double mirroring the deleted `DB` public
interface. It had no consumer other than its own test (`test_fake_db.py`).
Both are deleted. Domain-shaped fakes (`FakeTaskRepository`,
`FakeUnitOfWork`) already exist inline in `test_query_tasks.py` and
`test_client_query.py` for the use cases that need them.
**Migration**: Tests needing in-memory repository doubles SHALL define
file-local `FakeTaskRepository` / `FakeUnitOfWork` stubs (as already done in
`test_query_tasks.py` / `test_client_query.py`). Extracting shared domain
fakes to `tests/fixtures/` is a separate follow-up, out of scope here.
## MODIFIED Requirements

### Requirement: Node CRUD integration

Tests SHALL verify node operations against real PostgreSQL via
`PostgresNodeRepository` (through `uow.nodes`) and direct construction. The
covered operations are: `insert` (taking a `NewNode`, returning a `Node`),
`get_by_id`, `get_by_ids`, `list_all`, `list_enabled`, `list_disabled`,
`enable`, `disable`, `remove`, `count_by_cloud`, `count_by_status`. Tests
SHALL construct domain `NewNode` entities (`yascheduler.domain.NewNode`) and
assert the round-tripped `Node` fields.

The exhaustive method list lives in the persistence module's
`MODULE_CONTRACT` SCOPE and the `CLASS_PostgresNodeRepository` GRACE region
— the spec keeps only the behavioral coverage rule.

#### Scenario: Insert, retrieve, enable/disable filtering
- **WHEN** two nodes are inserted (one enabled, one disabled) via `uow.nodes.insert(NewNode(hostname="[IP1]", enabled=True))` and `uow.nodes.insert(NewNode(hostname="[IP2]", enabled=False))`
- **THEN** `uow.nodes.get_by_id(node_id)` returns matching fields, `uow.nodes.list_enabled()` returns one, `uow.nodes.list_disabled()` returns one

### Requirement: Task CRUD integration

Tests SHALL verify task operations via `PostgresTaskRepository` (through
`uow.tasks`) using the domain `Task` / `NewTask` entities and
`yascheduler.domain.TaskStatus`: `insert`, `get`, `update_status`, `save`
(for lifecycle transitions), `list_by_status`, `list_by_jobs`. Lifecycle
transitions SHALL be expressed via the domain `Task` methods operating on
the typed fields directly, then persisted via `uow.tasks.save`.

Tests SHALL construct `Task` / `NewTask` with the typed fields directly (no
`TaskContext(...)` wrapper, no `context=` kwarg). The `extra` JSONB column
(input-file payloads and unknown keys) SHALL be asserted to round-trip
through `insert` + `get` / `list_by_status` / `list_by_jobs`. The seven
typed columns (`engine`, `remote_folder`, `local_folder`, `webhook_url`,
`error`, `webhook_custom_params`, `extra`) SHALL be asserted to round-trip.
`error` SHALL be asserted to persist the new format contract values (bare
strings set via `task.fail()` / `task.reject()`, `NULL` on success).

The exhaustive method list lives in the persistence module's
`MODULE_CONTRACT` SCOPE and the `CLASS_PostgresTaskRepository` GRACE region
— the spec keeps only the behavioral coverage rule.

#### Scenario: Full task lifecycle
- **WHEN** a task transitions through the lifecycle (insert → running → done) via domain `Task` methods and is persisted via `uow.tasks.save`
- **THEN** each step reflects the correct status and typed fields (`engine`, `remote_folder`, `local_folder`, `error`, `extra`, `allocated_node_id`) in `uow.tasks.get`

#### Scenario: Task error column embeds error string
- **WHEN** a task is saved with `task.error="crash"` (via `task.fail("crash")` or `task.reject("crash")`) and status DONE
- **THEN** `uow.tasks.get(id)` returns status DONE and the row's `error` column equals `"crash"` (the typed column carries the error string directly; no `metadata` JSONB serialization)

#### Scenario: extra JSONB round-trips
- **WHEN** a task is saved with `extra={"input.in": "ATOMS", "input.xyz": "..."}` and retrieved via `uow.tasks.get(id)`
- **THEN** the retrieved task's `extra` equals `{"input.in": "ATOMS", "input.xyz": "..."}` (the `extra` JSONB column round-trips; pg8000 adapts `dict` ↔ JSONB natively)

#### Scenario: typed columns round-trip
- **WHEN** a task is saved with `engine="cp2k"`, `remote_folder="/r"`, `local_folder="/l"`, `webhook_url="https://..."`, `webhook_custom_params={"k": "v"}`, `error=None`, `extra={}` and retrieved
- **THEN** the retrieved task has the same values for all seven typed columns; `error` is `None` (NULL in the DB)

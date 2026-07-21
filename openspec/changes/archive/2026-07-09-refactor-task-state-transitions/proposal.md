## Why

The `Task` domain entity exposes its lifecycle as a bag of independent mutating
methods (`allocate_to`, `mark_running`, `complete`, `fail`, `reject`,
`with_remote_folder`, `with_download_results`) plus two event primitives
(`record_event`, `with_event`). Callers assemble the entity through
semantically-empty intermediate states (`TO_DO + allocated`, `RUNNING +
folders`) and must manually keep event payloads in sync with the transition
they follow — producing duplicated reason strings and event types that don't
match the transition (`fail("node is gone")` followed by
`with_event(TaskAbandoned)`). The entity should move between valid states via
atomic transitions that emit their own events inline.

## What Changes

- **BREAKING** — Replace the `Task` lifecycle API with atomic transition
  methods that emit events inline:
  - `run(self, node_id: NodeId, remote_folder: str) -> Task` — `TO_DO→RUNNING`,
    sets `allocated_node_id` + `remote_folder`, emits
    `TaskAllocated(node_id=node_id, engine_name=self.engine)`, raises
    `TaskNotTodoError`.
  - `reject(self, reason: str) -> Task` — `TO_DO→DONE`, sets `error`, emits
    `TaskFailed(reason=reason)`, raises `TaskNotTodoError`.
  - `complete(self, *, local_folder: str, remote_folder: str) -> Task` —
    `RUNNING→DONE`, sets `local_folder` + `remote_folder`, emits
    `TaskCompleted(local_folder=local_folder)`, raises `TaskNotRunningError`.
  - `fail(self, reason: str, *, local_folder: str, remote_folder: str) -> Task`
    — `RUNNING→DONE`, sets `error` + `local_folder` + `remote_folder`, emits
    `TaskFailed(reason=reason)`, raises `TaskNotRunningError`. Folders are
    keyword-only because `fail` may carry partial download results.
  - `abandon(self, node_id: NodeId | None, error: str = "node is gone") -> Task`
    — `RUNNING→DONE`, sets `error`, emits `TaskAbandoned(node_id=node_id)` only
    when `node_id is not None` (the double-abandon edge: the node row was
    already deleted, FK ON DELETE SET NULL nulled `allocated_node_id`, there is
    no node to abandon so no event is emitted). Raises `TaskNotRunningError`.
    Folders untouched (node gone, no download).
- **BREAKING** — Remove `Task.allocate_to`, `Task.mark_running`,
  `Task.with_remote_folder`, `Task.with_download_results`, `Task.with_event`,
  `Task.record_event`, `Task.pull_events`.
- Add a free domain function `materialize_task(task: Task) -> Task` in
  `yascheduler/domain/model.py` that returns a `Task` with `TaskCreated`
  appended to `events`, reading `task_id`/`webhook_url`/
  `webhook_custom_params`/`engine` off the freshly-inserted `Task`.
  `PostgresTaskRepository.insert` calls it; `_row_to_task` remains the single
  row→Task mapping site and always sets `events=()`.
- **BREAKING** — Make `Task._events` a public field `events: tuple[DomainEvent,
  ...]` (no leading underscore; `repr=False` → `repr=True`).
- **BREAKING** — Remove `TaskCompleted.has_errors` (unused; `complete` always
  means success, errors go through `fail`).
- **BREAKING** — Remove `TaskAlreadyAllocatedError` and
  `TaskNotAllocatedError` (they guarded the `TO_DO + allocated` intermediate
  state that no longer exists).
- Simplify `PostgresUnitOfWork.collect_events` to read `task.events` directly
  and clear `_saved_tasks`; drop the clean-task re-append (dead code —
  `publish_events` cleared the list immediately after).
- Move `remote_folder` assignment from `submit_task` to
  `allocate_task._try_start_on_machine` (computed from `task.task_id`, same
  formula as today, passed to `run`). The DB column is NULL for `TO_DO` tasks.
- Rewrite all five call sites (`submit_task`, `allocate_task._validate_engine`,
  `allocate_task._try_start_on_machine`, `consume_task._decide_finalisation`,
  `orchestrator._task_consumer_consumer`) to use the new atomic transitions.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `domain-entities`: Replace the `Task` lifecycle method requirements
  (`allocate_to`/`mark_running`/`complete`/`fail`/`reject`/
  `with_remote_folder`/`with_download_results`/`with_event`/`record_event`/
  `pull_events`) with the five atomic transition methods; add the
  `materialize_task` free function; make `events` a public field; remove the
  `TO_DO+allocated` allocation scenario.
- `domain-events-and-dispatch`: Remove the `Task.with_event` event-factory
  requirement and the `record_event`/`pull_events` collection primitive
  requirements; remove `has_errors` from `TaskCompleted`; rewrite the
  use-case-to-event mapping table (transitions emit events, not use cases);
  update the UoW `collect_events` requirement to read `task.events` directly.
- `domain-exceptions`: Remove `TaskAlreadyAllocatedError` and
  `TaskNotAllocatedError` — their guards are no longer needed. The remaining
  `TaskNotTodoError` and `TaskNotRunningError` cover all five transition
  guards.
- `postgres-persistence`: Update the `insert` contract to call
  `materialize_task(self._row_to_task(rows[0]))`; update `collect_events` to
  read `task.events` and clear.
- `use-cases`: Update the lifecycle call sites in `submit_task`,
  `allocate_task`, `consume_task`, and `orchestrator._task_consumer_consumer`
  to use atomic transitions; move `remote_folder` construction from
  `submit_task` to `allocate_task._try_start_on_machine`.

## Impact

- **Code**: `yascheduler/domain/model.py` (Task rewrite + `materialize_task`),
  `yascheduler/domain/events.py` (`TaskCompleted.has_errors` removed),
  `yascheduler/domain/exceptions.py` (2 classes removed),
  `yascheduler/infra/persistence/postgres.py` (`insert` calls
  `materialize_task`), `yascheduler/infra/persistence/postgres_uow.py`
  (`collect_events` simplified), `yascheduler/application/submit_task.py`,
  `allocate_task.py`, `consume_task.py`, `orchestrator.py` (call-site
  rewrites).
- **Tests**: `tests/unit/test_domain_model.py` (lifecycle method tests
  rewritten), `tests/unit/test_domain_events.py` (`with_event`/`record_event`
  tests removed; `TaskCreated`-via-`materialize_task` added; `pull_events`
  tests removed), `tests/unit/test_message_bus.py` (`record_event` → direct
  `events` field), `tests/integration/test_db_integration.py`,
  `test_persistence_adapter.py`, `test_never_connected_node_abandon.py`
  (replace `allocate_to` chains with direct dataclass construction for the
  edge-case fixture; use `run`/`complete`/`fail`/`abandon` for the lifecycle
  test).
- **Public API**: `Task` lifecycle methods change — any external caller of
  `allocate_to`/`mark_running`/`complete`/`fail`/`reject`/`with_*`/`with_event`
  must migrate to the new transitions. The `Yascheduler` facade, CLI commands,
  INI config, DB schema, and AiiDA entrypoint are unaffected.
- **Dependencies**: None added.
- **DB schema**: No change (`remote_folder` NULL on TO_DO is already valid per
  the existing schema DEFAULT NULL).
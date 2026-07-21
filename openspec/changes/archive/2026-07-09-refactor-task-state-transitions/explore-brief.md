# Explore Brief: refactor-task-state-transitions

## Problem

The Task domain entity exposes lifecycle as a bag of independent mutating
methods (`allocate_to`, `mark_running`, `complete`, `fail`, `reject`,
`with_remote_folder`, `with_download_results`) plus two event primitives
(`record_event`, `with_event`). Callers assemble the entity through
intermediate states that don't carry semantic meaning (`TO_DO + allocated`,
`RUNNING + folders`) and must manually keep event payloads in sync with the
transition they follow. The result: duplicated reason strings, event types
that don't match the transition (`fail("node is gone")` followed by
`with_event(TaskAbandoned)`), and an object that can be observed mid-chain in
a state no transition intends to produce.

## Rejected alternatives

- **Keep current methods, move event emission inside each** — leaves the
  intermediate states (`TO_DO+allocated`, `RUNNING+folders`) intact; the
  primary smell persists.
- **Transition command-objects** (`RunTransition(...).apply(task)`) — 4
  transitions do not justify a command hierarchy; indirection without clarity.
- **`with_event` survives as a private `_emit`** — preserves a primitive
  escape hatch the entity no longer needs; transitions cover every emission
  site.
- **Repository constructs `TaskCreated` directly** — leaks domain event types
  into the infrastructure layer; the domain should own event construction.
- **`NewTask.materialize(task: Task)` taking a post-persistence Task** — a
  pre-persistence entity consuming a post-persistence one is an inversion;
  rejected in favor of a free domain function over a Task.

## Final approach

### Lifecycle transitions (atomic, events emitted inline)

| Method | Transition | Sets | Emits | Raises |
|---|---|---|---|---|
| `run(self, node_id: NodeId, remote_folder: str) -> Task` | TO_DO→RUNNING | `allocated_node_id`, `remote_folder` | `TaskAllocated(node_id, engine_name=self.engine)` | `TaskNotTodoError` |
| `reject(self, reason: str) -> Task` | TO_DO→DONE | `error=reason` | `TaskFailed(reason=reason)` | `TaskNotTodoError` |
| `complete(self, *, local_folder: str, remote_folder: str) -> Task` | RUNNING→DONE | `local_folder`, `remote_folder` | `TaskCompleted(local_folder)` | `TaskNotRunningError` |
| `fail(self, reason: str, *, local_folder: str, remote_folder: str) -> Task` | RUNNING→DONE | `error=reason`, `local_folder`, `remote_folder` | `TaskFailed(reason=reason)` | `TaskNotRunningError` |
| `abandon(self, node_id: NodeId | None, error: str = "node is gone") -> Task` | RUNNING→DONE | `error=error` (folders untouched) | `TaskAbandoned(node_id=node_id)` only when `node_id is not None` | `TaskNotRunningError` |

Notes:
- `complete`/`fail` carry the download folders as keyword-only params so the
  `with_download_results` copy-with is absorbed into the transition. `fail`
  may carry partial download results (some files downloaded, others failed).
- `abandon` does not set folders (node gone, no download happened); it takes
  `node_id: NodeId | None` so the orchestrator's double-abandon edge (FK
  cascade nulled `allocated_node_id`) is handled by a single call without
  branching — `abandon(None)` transitions to DONE + error but emits no
  `TaskAbandoned` event (preserves the current silent behavior at
  `orchestrator.py:462`).
- `reject` sets no folders (the task never ran).

### Creation: `materialize_task` free function

A free domain function in `yascheduler/domain/model.py`:

```
materialize_task(task: Task) -> Task
    # Returns a Task with TaskCreated appended to events.
    # Reads task_id, webhook_url, webhook_custom_params, engine off the
    # freshly-inserted Task and constructs TaskCreated(engine_name=task.engine).
```

`PostgresTaskRepository.insert` becomes:
```
return materialize_task(self._row_to_task(rows[0]))
```

`_row_to_task` stays the single row→Task mapping site (insert + all reads);
it always sets `events=()`. `materialize_task` is a one-line domain layer
that attaches exactly one event. Infrastructure does not import `TaskCreated`.

### `events` field made public

`_events: tuple[DomainEvent, ...]` (repr=False) → `events: tuple[DomainEvent, ...]`
(public, repr shown). Rationale: the UoW reads it directly; no `pull_events`
helper is needed.

### `pull_events` removed; UoW `collect_events` simplified

Current `collect_events` pulls events via `pull_events`, re-appends clean
tasks to `_saved_tasks`, then `publish_events` immediately clears the list —
the clean tasks are never read. Simplified:

```
async def collect_events(self) -> list[DomainEvent]:
    events: list[DomainEvent] = []
    for task in self._saved_tasks:
        events.extend(task.events)
    self._saved_tasks.clear()
    return events
```

No `replace(task, events=())`, no clean-task tracking.

### Removed methods and fields

- `Task.allocate_to`, `Task.mark_running`, `Task.with_remote_folder`,
  `Task.with_download_results`, `Task.with_event`, `Task.record_event`,
  `Task.pull_events`
- `TaskAlreadyAllocatedError`, `TaskNotAllocatedError` (guarded the
  `TO_DO+allocated` intermediate state that no longer exists)
- `TaskCompleted.has_errors` field (unused; complete always means success,
  errors go through `fail`)

### `remote_folder` timing

`remote_folder` is no longer set at `submit_task` time. It is computed in
`allocate_task._try_start_on_machine` (from `task.task_id`, same formula as
today) and passed to `run(node_id, remote_folder)`. The DB column is NULL for
TO_DO tasks — acceptable: the remote folder does not exist until the task
runs.

## Call-site rewrites (cross-module data flows)

| Use case / file | Before | After |
|---|---|---|
| `submit_task.py:104` | `task.with_remote_folder(rf).with_event(TaskCreated, engine_name=task.engine)` | `task = await uow.tasks.insert(new_task)` (materialize_task attaches TaskCreated inside insert) |
| `allocate_task.py:92` (`_validate_engine`) | `task.reject("unsupported engine").with_event(TaskFailed, reason="unsupported engine")` | `task = task.reject("unsupported engine")` |
| `allocate_task.py:129,146` (`_try_start_on_machine`) | `task.allocate_to(node).mark_running()` then later `task.with_event(TaskAllocated, node_id=node.node_id, engine_name=task.engine)` | `task = task.run(node.node_id, remote_folder)` |
| `consume_task.py:127-138` (`_decide_finalisation`) | `task.with_download_results(local_folder=lf, remote_folder=rf)` then `task.fail(err).with_event(TaskFailed, reason=err)` OR `task.complete().with_event(TaskCompleted, local_folder=str(store_folder), has_errors=False)` | `task = task.fail(err, local_folder=lf, remote_folder=rf)` OR `task = task.complete(local_folder=str(store_folder), remote_folder=rf)` |
| `orchestrator.py:455,463` (`_task_consumer_consumer`) | `task = task.fail("node is gone")` then `if node_id is not None: task = task.with_event(TaskAbandoned, node_id=node_id)` | `task = task.abandon(node_id)` (single call; `abandon` emits `TaskAbandoned` only when `node_id is not None`) |
| `postgres.py:183-195` (`insert`) | `return self._row_to_task(rows[0])` | `return materialize_task(self._row_to_task(rows[0]))` |
| `postgres_uow.py:184-192` (`collect_events`) | `pull_events()` + re-append clean tasks | `events.extend(task.events)` + clear |

## Open questions

None remaining. All design points resolved during exploration:
- TaskCreated emission → `materialize_task` free function (domain owns it).
- `TO_DO + allocated` test fixture → test-only, will use direct dataclass
  construction (the pre-bind integration test sets up an edge case, not
  production behavior).
- `has_errors` → removed.
- `fail()` folders → required keyword-only params (partial download results
  are a real case).
- `with_event` / `record_event` → fully removed.
- `pull_events` → removed; UoW reads `task.events` directly.
- clean-task re-append in UoW → dead code, removed.
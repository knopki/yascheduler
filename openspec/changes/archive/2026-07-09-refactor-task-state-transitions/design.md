## Context

The `Task` domain entity (`yascheduler/domain/model.py`) is a frozen
dataclass that today exposes its lifecycle as a bag of independent mutating
methods returning new instances via `dataclasses.replace`. Five use cases
assemble the entity through chains: `submit_task` does
`with_remote_folder(...).with_event(TaskCreated, ...)`, `allocate_task` does
`allocate_to(node).mark_running()` then separately
`with_event(TaskAllocated, ...)`, `consume_task` does
`with_download_results(...)` then `fail(...).with_event(TaskFailed, ...)` or
`complete().with_event(TaskCompleted, ...)`, and `orchestrator` does
`fail("node is gone")` then `with_event(TaskAbandoned, node_id=...)`.

Two smells follow from this shape:

1. **Intermediate states.** `allocate_to` + `mark_running` produces a
   `TO_DO + allocated` task that exists only as a stepping stone. Similarly
   `with_download_results` produces `RUNNING + folders`. These states are
   valid by the dataclass but carry no semantic meaning — an observer
   catching the object mid-chain sees a state no transition intends to
   produce.
2. **Events decoupled from transitions.** Callers must (a) know which event
   matches which transition, (b) manually keep payload in sync with the
   transition args (`reject("unsupported engine").with_event(TaskFailed,
   reason="unsupported engine")` duplicates the reason), and (c) in the
   abandon case, choose an event type that doesn't match the `fail()` it
   follows. The entity has no opinion about its own events.

Constraints:

- `Task` stays a `@dataclass(frozen=True)` — immutability preserved; every
  transition still returns a new `Task` via `replace`.
- `_row_to_task` stays the single row→Task mapping site (insert + all reads);
  it always sets `events=()`.
- The `Yascheduler` public facade, CLI commands, INI config, DB schema, and
  AiiDA entrypoint are unaffected.
- The UoW dispatch-after-commit contract (`commit()` → SQL COMMIT →
  `publish_events()`) is preserved; events are recorded in `events` during
  the transaction but only dispatched after commit, so a discarded
  speculative transition (e.g. SSH spawn failure) never dispatches.

## Goals / Non-Goals

**Goals:**

- Every `Task` state change happens through one atomic transition method that
  sets all related fields and emits the matching event inline.
- No `Task` instance is ever observed in a semantically-empty intermediate
  state produced by a public method (the pre-bind test fixture constructs the
  edge case directly via the dataclass, not via a public method).
- Events are constructed inside the entity; callers never construct
  `DomainEvent` subclasses or pass event payloads.
- The UoW event-collection mechanism is simplified to read the public
  `events` field directly; `pull_events` and the dead clean-task re-append
  are removed.
- `TaskCreated` emission lives in the domain layer (a free function), not in
  the infrastructure layer.

**Non-Goals:**

- Changing the `TaskStatus` enum values or adding new statuses.
- Changing the `DomainEvent` base class or the `MessageBus`/`webhook_handler`
  contracts (only `TaskCompleted.has_errors` is removed; the webhook wire
  format is unaffected because `webhook_handler` does not read `has_errors`).
- Changing the DB schema — `remote_folder` NULL on TO_DO is already valid per
  the existing schema DEFAULT NULL.
- Changing the `NewTask` pre-persistence record (it stays a pure data
  carrier with no lifecycle methods).
- Introducing a state-machine library or command-object hierarchy — five
  plain methods suffice.
- Revisiting the `ConnectedMachine`/`Node`/`NewNode` entities.

## Decisions

### D1: Five atomic transition methods, events emitted inline

Each transition is a single method that (a) validates the source state, (b)
sets all fields that change, (c) constructs and appends the matching event to
`events`, and (d) returns the new `Task` via `replace`. No transition leaves
the entity in a partial state.

Alternatives considered:

- **Keep current methods, move event emission inside each** — leaves the
  intermediate states intact; the primary smell persists. Rejected.
- **Transition command-objects (`RunTransition(...).apply(task)`)** — four
  transitions do not justify a command hierarchy; indirection without
  clarity. Rejected.
- **Keep `with_event` as a private `_emit`** — preserves an escape hatch the
  entity no longer needs; every emission site is a transition. Rejected.

### D2: `complete` and `fail` take the download folders as keyword-only params

`with_download_results` is absorbed into the terminal transitions. `fail`
may carry partial download results (some files downloaded, others failed),
so its folder params are keyword-only with no default — the caller is forced
to be explicit. `complete` takes them keyword-only as well for symmetry.
`abandon` does not take folders (the node is gone, no download happened).
`reject` does not take folders (the task never ran).

Alternative considered: default `local_folder=""`/`remote_folder=""` on
`fail` — rejected because it lets the caller silently drop download context
that the transition is supposed to persist.

### D3: `materialize_task` free function, not a method on `NewTask` or `Task`

A free function in `yascheduler/domain/model.py`:

```
materialize_task(task: Task) -> Task
    # Returns a Task with TaskCreated appended to events.
```

It reads `task_id`, `webhook_url`, `webhook_custom_params`, `engine` off the
freshly-inserted `Task` (produced by `_row_to_task`) and constructs
`TaskCreated(task_id=task.task_id, webhook_url=task.webhook_url,
webhook_custom_params=task.webhook_custom_params, engine_name=task.engine)`,
then returns `replace(task, events=(event,))`.

`PostgresTaskRepository.insert` becomes
`return materialize_task(self._row_to_task(rows[0]))`.

Why a free function over alternatives:

- **`NewTask.materialize(task: Task)`** — rejected. A pre-persistence entity
  consuming a post-persistence one is an inversion; `NewTask` is a pure data
  carrier and should not gain methods that take a `Task`.
- **Repository constructs `TaskCreated` directly** — rejected. Leaks domain
  event types into the infrastructure layer; the domain should own event
  construction.
- **Class method `Task.created(...)`** — rejected. Bypasses the
  repository-as-conversion-site rule (`TaskRepository.insert` is the only
  `NewTask→Task` conversion site) and would re-parse DB fields the
  repository already parsed.
- **Keep `with_event` for `TaskCreated` only** — rejected. Preserves the
  event primitive the entity no longer needs; `materialize_task` is a
  single-purpose named function with a clearer contract than a lone
  `with_event(TaskCreated, ...)` call.

`_row_to_task` stays the single row→Task mapping site (insert + all reads);
it always sets `events=()`. `materialize_task` is a thin domain layer over
its output.

### D4: `events` public field, `pull_events` removed

`_events: tuple[DomainEvent, ...] = field(default=(), repr=False)` becomes
`events: tuple[DomainEvent, ...] = field(default=(), repr=True)`. The UoW
reads it directly. `pull_events` (which returned a clean Task + events tuple)
is removed because its only caller, `collect_events`, re-appended the clean
task to `_saved_tasks` and `publish_events` immediately cleared the list —
the clean task was never read.

Simplified `collect_events`:

```
async def collect_events(self) -> list[DomainEvent]:
    events: list[DomainEvent] = []
    for task in self._saved_tasks:
        events.extend(task.events)
    self._saved_tasks.clear()
    return events
```

No `replace(task, events=())` inside the UoW; the task instances are
discarded with the UoW context.

### D5: Remove `TaskCompleted.has_errors`

The field is unused — every `complete` path passes `has_errors=False`, and
errors go through `fail`. The webhook wire format is unaffected because
`webhook_handler` builds `WebhookPayload(task_id, status, custom_params)` and
does not read `has_errors`.

### D6: Remove `TaskAlreadyAllocatedError` and `TaskNotAllocatedError`

These guarded the `TO_DO + allocated` intermediate state: `allocate_to`
raised `TaskAlreadyAllocatedError` if `allocated_node_id is not None`, and
`mark_running` raised `TaskNotAllocatedError` if it was `None`. With
`run()` collapsing `allocate_to + mark_running` into a single `TO_DO→RUNNING`
transition, allocation is atomic with running and neither guard arises. The
remaining `TaskNotTodoError` (guards `run`, `reject`) and `TaskNotRunningError`
(guards `complete`, `fail`, `abandon`) cover all five transition guards.

### D7: `remote_folder` set at `run` time, not `submit` time

Today `submit_task` computes `remote_folder` from the generated `task_id`
and persists it via `with_remote_folder` so the DB column is populated while
the task is still `TO_DO`. Under the new design, `remote_folder` is computed
in `allocate_task._try_start_on_machine` (same formula,
`str(remote_tasks_dir / f"{dt_str}_{task.task_id}")`) and passed to
`run(node_id, remote_folder)`. The DB column is NULL for `TO_DO` tasks.

Rationale: `remote_folder` is the remote path where the task will execute —
it does not exist until the task runs. Persisting it at submit time was a
side effect of the old chain shape, not a requirement. NULL on TO_DO is
already valid per the schema DEFAULT NULL.

The `yastatus`/`Yascheduler` facade reads task rows via the repositories; if
any caller rendered `remote_folder` for a TO_DO task and cannot tolerate
NULL, it must be updated. A scan of the CLI and facade will be done during
implementation; the proposal's Impact section flags this.

### D8: Pre-bind test fixture uses direct dataclass construction

`tests/integration/test_never_connected_node_abandon.py:169` constructs a
`TO_DO + allocated` task via `inserted_task.allocate_to(persisted_node)` to
set up the never-connected-node edge case. With `allocate_to` removed, the
test constructs the edge case directly via the frozen dataclass:

```
stuck_task = replace(inserted_task, allocated_node_id=persisted_node.node_id)
```

This is acceptable because the test is setting up an edge case, not
exercising the public API. The `TO_DO + allocated` state is not produced by
any production transition under the new design — `run()` is the only path
that sets `allocated_node_id`, and it moves to `RUNNING` atomically.

`replace` is legitimate inside tests for fixture construction; the
"no `replace` outside the entity" rule applies to production code (entity
methods + `materialize_task`).

## Risks / Trade-offs

- **[Risk] `remote_folder` NULL on TO_DO breaks a CLI/facade renderer** →
  Mitigation: scan `cli/` and `package-facades` for `remote_folder` reads
  during implementation; update any renderer that assumes non-NULL on TO_DO.
  The DB schema already permits NULL.
- **[Risk] An external caller of the removed `Task` methods breaks** →
  Mitigation: the methods are domain-layer API, not the public `Yascheduler`
  facade. The facade's public methods (`queue_submit_task`, `check_task`,
  `list_nodes`, etc.) do not expose `Task` lifecycle methods. The AiiDA
  scheduler plugin uses the facade, not the domain entity. The change is
  breaking for direct domain-entity consumers only, which are internal to
  this repo.
- **[Risk] `abandon` takes `node_id: NodeId | None` but the double-abandon
  edge nulled `task.allocated_node_id`** → Mitigation: `abandon(None)`
  transitions the task to DONE with `error` but emits no `TaskAbandoned`
  event (preserves the current silent behavior at `orchestrator.py:462`,
  which skips `with_event(TaskAbandoned)` when `node_id is None`). The
  orchestrator's branching collapses to a single `task.abandon(node_id)`
  call; the entity owns the "emit only when there is a node" rule.
- **[Trade-off] `fail` requires explicit folder params** → callers can no
  longer forget to persist download paths on the failure path. Slightly more
  verbose at the call site, but removes a class of bugs where `fail` dropped
  the partial download location.
- **[Trade-off] `materialize_task` is a new public domain function** → one
  more symbol to learn, but it has a single purpose and a one-line body. The
  alternative (repository constructs the event) was rejected for layering
  reasons.

## Migration Plan

Single-repo, single-PR change. No runtime migration, no DB migration, no
config migration. Deployment is a code update.

Steps:

1. Update `domain/events.py` — remove `TaskCompleted.has_errors`.
2. Update `domain/exceptions.py` — remove `TaskAlreadyAllocatedError`,
   `TaskNotAllocatedError`.
3. Update `domain/model.py` — rewrite `Task` lifecycle methods, add
   `materialize_task`, rename `_events` → `events` (repr=True).
4. Update `infra/persistence/postgres.py` — `insert` calls
   `materialize_task(self._row_to_task(rows[0]))`.
5. Update `infra/persistence/postgres_uow.py` — simplify `collect_events`.
6. Update `application/submit_task.py`, `allocate_task.py`,
   `consume_task.py`, `orchestrator.py` — call-site rewrites.
7. Update tests (unit + integration) per the Impact section.
8. Scan CLI + facade for `remote_folder` reads on TO_DO; update if needed.

Rollback: revert the PR. No persistent state to roll back.

## Open Questions

None. All design points were resolved during exploration and captured in
`explore-brief.md`.
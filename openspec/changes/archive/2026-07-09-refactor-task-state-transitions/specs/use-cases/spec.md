## MODIFIED Requirements

### Requirement: SubmitTask use case

The system SHALL provide a `submit_task` async function that creates a new
task in the database after validating the engine and inputs. The function SHALL
return `TaskId` (was `int`).

The function SHALL construct a `NewTask(label=label, engine=engine_name,
local_folder=metadata.get("local_folder"), webhook_url=metadata.get("webhook_url"),
webhook_custom_params=metadata.get("webhook_custom_params", {}),
extra=extra_dict)` (the pre-persistence shape — no `task_id`; `status` defaults
to `TaskStatus.TO_DO`, `allocated_node_id` defaults to `None`; `remote_folder`
and `error` are NOT on `NewTask`), persist it via
`uow.tasks.insert(new_task) -> Task` (the sole `NewTask → Task` conversion;
`insert` calls `materialize_task` internally to attach `TaskCreated` to the
returned `Task`'s `events`), then `save`, `commit`, and return `task.task_id`
(a `TaskId`).

The prior `task.with_remote_folder(remote_folder)` and
`task.with_event(TaskCreated, engine_name=task.engine)` calls are REMOVED.
`remote_folder` is no longer set at submit time — it is set by `run` when the
task transitions to RUNNING in `allocate_task._try_start_on_machine` (see the
AllocateTask requirement). `TaskCreated` is attached by `materialize_task`
inside `insert`, not by the use case. The function SHALL NOT construct any
`DomainEvent` subclass.

The typed fields are extracted from the caller-supplied `metadata` dict
(produced by `cli/submit.py::_build_metadata`); `engine` is set from the
`engine_name` argument. The `extra` dict carries the input-file payloads (file
contents as values, file names as keys) — every key in the caller `metadata`
that is not one of the six known typed fields (`engine`, `remote_folder`,
`local_folder`, `webhook_url`, `webhook_custom_params`, `error`) goes into
`extra`. `remote_folder` and `error` are never set on `NewTask`: `remote_folder`
is assigned at `run` time; `error` is only ever set by `reject`/`fail`/`abandon`
on a post-persistence `Task`.

#### Scenario: Successful task submission
- **WHEN** `submit_task(...)` is called with valid inputs
- **THEN** a `NewTask` is constructed, persisted via `uow.tasks.insert` → `Task` (with `TaskCreated` in `events` via `materialize_task`), saved, committed, and the `TaskId` is returned; `remote_folder` is `None` on the persisted TO_DO task

#### Scenario: Unsupported engine
- **WHEN** `submit_task(...)` is called with an engine_name not in the EngineRepository
- **THEN** `UnsupportedEngineError` is raised

#### Scenario: submit_task constructs NewTask not Task
- **WHEN** `submit_task(...)` builds the pre-persistence record
- **THEN** it constructs `NewTask(...)` (no `task_id=0` sentinel, no `remote_folder`, no `error`)

#### Scenario: submit_task does not construct events
- **WHEN** `submit_task(...)` is inspected for `TaskCreated` construction or `with_event`/`record_event` calls
- **THEN** none are present; `TaskCreated` is attached by `materialize_task` inside `insert`

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function SHALL
accept `task_id: TaskId`, `uow_factory`, `repository: MachineRepository`
(Protocol type), `occupancy_checker: OccupancyChecker` (concrete
collaborator type, for `start_occupancy_check`), `clouds:`
`CloudProvisioner` (Protocol type), `tracker: AllocationTracker`, and
`allocation_lock: asyncio.Lock`. It SHALL NOT import from `yascheduler.infra` at
runtime. It SHALL NOT accept `adapters` or `configs` parameters — provider
selection is delegated to the `clouds.select_provider` port method.

The orchestrator reads task ids from `list_by_status -> [Task]` (each carrying
`TaskId`) and feeds `allocate_task(task_id=task.task_id, ...)`, so `TaskId`
flows end-to-end internally with no conversion. Logging `"task_id=%s"` renders
the bare integer via `TaskId.__str__`. `tracker.add`/`discard(task_id)` keys
are `TaskId` (the tracker's internal `set` becomes `set[TaskId]`).

For the cloud-fallback path, the use case SHALL own the full flow:
tracker dedup, capacity check, provider selection (via
`clouds.select_provider` port method returning `str | None`), tmp-node
insertion via `uow.nodes.insert` (NOT `add_tmp`), cloud allocation (via
`clouds.allocate(selection, node)` returning a `Node` reusing the tmp node's
`node_id`), final node persistence via `uow.nodes.update(node)` (a
single UPDATE flipping `enabled=TRUE` and setting `ip`/`ncpus`), and
tmp-node cleanup on failure (`uow.nodes.remove(tmp_node_id)`). The
`allocation_lock` SHALL serialize the capacity-read + select + tmp-insert
sequence so two concurrent `allocate_task` calls for the same engine cannot
both provision a cloud node when only one slot is free.

The function SHALL read `task.engine` (was `task.context.engine`) when
matching the task against engines. The `_validate_engine` helper SHALL reject
an unsupported engine via `task.reject("unsupported engine")` (a single atomic
transition that emits `TaskFailed` inline — no separate `with_event` call, no
duplicated reason string). The `_try_start_on_machine` helper SHALL compute
`remote_folder = str(remote_tasks_dir / f"{dt_str}_{task.task_id}")` (the same
formula the prior `submit_task` used) and transition the task via
`task.run(node.node_id, remote_folder)` (a single atomic transition that sets
`allocated_node_id` + `remote_folder`, moves to RUNNING, and emits
`TaskAllocated` inline — no separate `allocate_to`/`mark_running`/`with_event`
calls). No `TaskContext` indirection.

The prior `task.allocate_to(node).mark_running()` two-step and the separate
`task.with_event(TaskAllocated, node_id=node.node_id, engine_name=task.engine)`
call are REMOVED. The `remote_folder` construction moves from `submit_task` to
`_try_start_on_machine`.

#### Scenario: Successful allocation to a free machine
- **WHEN** `allocate_task(...)` is called and a free compatible machine exists
- **THEN** `_try_start_on_machine` computes `remote_folder` from `task.task_id`, calls `task.run(node.node_id, remote_folder)` (transitioning TO_DO→RUNNING and emitting `TaskAllocated` inline), starts the occupancy check, saves, commits, and the function returns True

#### Scenario: No free machine matches, cloud-fallback attempted
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the cloud-fallback path is attempted (tracker dedup, capacity check, provider selection, tmp-node insert, cloud allocation, final persist); returns False if no provider available

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a `task_id` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** `_validate_engine` calls `task.reject("unsupported engine")` (emitting `TaskFailed` inline), saves, commits, and the function returns False

#### Scenario: Occupancy check started via occupancy_checker

- **WHEN** `allocate_task(...)` successfully starts a task on a machine
- **THEN** `occupancy_checker.start_occupancy_check(session, engine)` is called (was `operations.start_occupancy_check`)

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function SHALL
accept `task_id: TaskId`, `session: MachineSession` (resolved by the
orchestrator via `repository.get_session(task.allocated_node_id)`),
`output_downloader: OutputDownloader` (concrete collaborator type, for
`download_outputs`), `engines: EngineRepository`, `uow_factory: Callable[[], AbstractUnitOfWork]`,
`local_tasks_dir: Path`, and `tracker: AllocationTracker`. It SHALL NOT import
`SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime.

The function SHALL return `bool`: `True` when the task is finalised (DONE
status applied, remote directory cleaned by the operations, in-flight
allocation slot released via `tracker.discard(task_id)`); `False` when the
task is deferred for retry (status unchanged, remote directory preserved by
the operations, in-flight allocation slot NOT released).

The function SHALL receive the `session` directly (resolved by the
orchestrator from `task.allocated_node_id` via
`repository.get_session(node_id)`) and delegate SFTP download with retry and
error classification to `output_downloader.download_outputs(session, ...)`.
`download_outputs` receives `task_id=task.task_id` (a `TaskId`); it uses the
value for logging and remote folder naming, where `TaskId.__str__` renders
the bare integer. The function SHALL receive `(local_folder, remote_folder,
transient_errors, permanent_errors)` from `download_outputs` (a 4-tuple of
typed values — the legacy `meta_add: list[tuple[str, Any]]` first element
is REMOVED; the two paths flow directly to `_decide_finalisation` as named
arguments, no `meta_dict` reconstruction) and branch on them:

- When `permanent_errors` is non-empty OR `transient_errors` is empty (full
  success, permanent-only errors, or both transient and permanent errors),
  the function SHALL finalise: on permanent errors it SHALL continue
  downloading the remaining available files first, then apply the terminal
  transition — `task.fail(error_details, local_folder=local_folder or
  task.local_folder, remote_folder=remote_folder or task.remote_folder)` (or
  `task.complete(local_folder=str(store_folder), remote_folder=remote_folder
  or task.remote_folder)` on full success with no permanent errors). Both
  transitions set the folders AND emit the matching event (`TaskFailed` or
  `TaskCompleted`) inline. The prior `task.with_download_results(...)` call
  followed by `.complete()`/`.fail()` and a separate `with_event(...)` is
  REMOVED — the terminal transition absorbs the folder-setting and event
  emission. Save via `uow.tasks.save()`, commit, call `tracker.discard(task_id)`,
  and return `True`. When both `permanent_errors` and `transient_errors` are
  non-empty, permanent takes priority and the function finalises with
  `task.fail()`.
- When `transient_errors` is non-empty AND `permanent_errors` is empty, the
  function SHALL defer: leave the task in `RUNNING` (no status change, no
  save, no event, no `tracker.discard`), and return `False` so the
  orchestrator re-consumes the task on the next producer cycle.

The `error_details` for the `TaskFailed` path SHALL be formatted via the
error column format contract (see the `domain-entities` delta): a
`_format_download_error(combined_errors)` helper produces
`"Download error: <path>: <msg>, <path>: <msg>"` (combined `permanent_errors
+ transient_errors`, preserving the legacy mixed-case behavior); entries with
`path=None` render as bare `"<msg>"`.

The `_decide_finalisation` helper SHALL call `task.fail(error_msg,
local_folder=local_folder or task.local_folder, remote_folder=remote_folder
or task.remote_folder)` or `task.complete(local_folder=str(store_folder),
remote_folder=remote_folder or task.remote_folder)` directly — no prior
`with_download_results(...)` step. The legacy `extra_updates` merge block
(building `extra_updates = {k: v for k, v in meta_dict.items() if k not in
("remote_folder", "local_folder", "error")}` and merging into
`task.context.extra`) is REMOVED: the terminal transitions do NOT touch
`extra`. The whole `updated_context = task.context.replace(...)` construction
and the `task.with_context(...)` calls are deleted. The `meta_add`/`meta_dict`
indirection itself is also REMOVED as a metadata-blob relic:
`download_outputs` returns the two paths as the leading elements of its
4-tuple, and `_decide_finalisation` / `_finalize_task` receive them as named
`local_folder: str, remote_folder: str` parameters — no intermediate dict is
constructed.

`_prepare_store_folder` SHALL read `task.remote_folder` (was
`task.context.remote_folder`), `task.engine` (was `task.context.engine`), and
`task.local_folder` (was `task.context.local_folder`) directly from the
typed fields. The assertion `assert task.remote_folder is not None` SHALL
guard the `task.remote_folder` read (the task is RUNNING — `run` assigned
`remote_folder` at allocate time). No `TaskContext` indirection.

#### Scenario: Successful consumption
- **WHEN** `consume_task(...)` is called and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** `task.complete(local_folder=str(store_folder), remote_folder=...)` is called (emitting `TaskCompleted` inline), the task is saved, committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with DONE+error
- **WHEN** `download_outputs` returns non-empty `permanent_errors`
- **THEN** `task.fail(error_msg, local_folder=..., remote_folder=...)` is called (emitting `TaskFailed` inline, setting folders from partial download), the task is saved, committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Transient-only download error defers for retry
- **WHEN** `download_outputs` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING`, no `tracker.discard` is called, and the function returns `False`

#### Scenario: consume_task reads typed fields not task.context
- **WHEN** `consume_task.py` is inspected for `task.context` references
- **THEN** none are present; reads use `task.remote_folder`, `task.engine`, `task.local_folder` directly

#### Scenario: consume_task does not call with_download_results or with_event
- **WHEN** `consume_task.py` is inspected for `with_download_results` or `with_event` calls
- **THEN** none are present; the terminal transitions `complete`/`fail` set the folders and emit the events inline
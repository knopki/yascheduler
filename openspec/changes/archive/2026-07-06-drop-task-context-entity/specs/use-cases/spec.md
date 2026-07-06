# Spec Delta: use-cases

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
`uow.tasks.insert(new_task) -> Task` (the sole `NewTask → Task` conversion),
then `task.with_remote_folder(remote_folder)` (the remote path is constructed
from the generated `task.task_id` as `str(remote_tasks_dir /
f"{dt_str}_{task.task_id}")`) and `task.with_event(TaskCreated,
engine_name=task.engine)`, `save`, `commit`, and return `task.task_id` (a
`TaskId`).

The typed fields are extracted from the caller-supplied `metadata` dict
(produced by `cli/submit.py::_build_metadata`); `engine` is set from the
`engine_name` argument. The `extra` dict carries the input-file payloads (file
contents as values, file names as keys) — every key in the caller `metadata`
that is not one of the six known typed fields (`engine`, `remote_folder`,
`local_folder`, `webhook_url`, `webhook_custom_params`, `error`) goes into
`extra`. `remote_folder` and `error` are never set on `NewTask`: `remote_folder`
is assigned post-insert via `with_remote_folder`; `error` is only ever set by
`fail`/`reject` on a post-persistence `Task`.

#### Scenario: Successful task submission
- **WHEN** `submit_task("my-job", metadata, "fleur", engines, uow_factory, remote_tasks_dir)` is called with valid inputs (metadata contains `local_folder`, input-file payloads, and optionally `webhook_url`/`webhook_custom_params`)
- **THEN** a `NewTask(label="my-job", engine="fleur", local_folder=metadata["local_folder"], webhook_url=..., webhook_custom_params=..., extra={input-file payloads})` is constructed, persisted via `uow.tasks.insert` → `Task`, `task.with_remote_folder(<constructed path>)` is applied, `task.with_event(TaskCreated, engine_name="fleur")` is applied, the resulting task is saved and committed, and the `TaskId` is returned

#### Scenario: Unsupported engine
- **WHEN** `submit_task(...)` is called with an engine_name not in the EngineRepository
- **THEN** `UnsupportedEngineError` is raised

#### Scenario: Missing input file
- **WHEN** `submit_task(...)` is called with metadata missing a required input file (per `engine.input_files`)
- **THEN** `MissingInputFileError` is raised

#### Scenario: submit_task constructs NewTask not Task
- **WHEN** `submit_task(...)` builds the pre-persistence record
- **THEN** it constructs `NewTask(label=label, engine=engine_name, local_folder=..., webhook_url=..., webhook_custom_params=..., extra=...)` (no `task_id=0` sentinel, no `remote_folder`, no `error`); the `task_id=0` fiction is gone

#### Scenario: submit_task extracts typed fields from metadata dict
- **WHEN** `submit_task("job", {"local_folder": "/l", "input.in": "ATOMS", "webhook_url": "https://..."}, "cp2k", engines, uow_factory, remote_tasks_dir)` is called
- **THEN** the `NewTask` has `engine="cp2k"`, `local_folder="/l"`, `webhook_url="https://..."`, `webhook_custom_params={}` (default), `extra={"input.in": "ATOMS"}` (input-file payload routed to extra); no `TaskContext.from_metadata` is called

#### Scenario: submit_task assigns remote_folder post-insert
- **WHEN** `submit_task(...)` has persisted the `NewTask` via `uow.tasks.insert` and received the resulting `Task` with a generated `task_id`
- **THEN** it calls `task.with_remote_folder(str(remote_tasks_dir / f"{dt_str}_{task.task_id}"))` (constructed from the generated id and a timestamp), then `with_event(TaskCreated, engine_name=task.engine)`, then `save` + `commit`

#### Scenario: No TaskContext or with_context in submit_task
- **WHEN** `submit_task.py` is inspected for `TaskContext`, `with_context`, or `context.replace` references
- **THEN** none are present (the function extracts typed fields directly from the caller metadata dict and uses `with_remote_folder`)

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function SHALL
accept `task_id: TaskId`, `uow_factory`, `repository: MachineRepository`
(Protocol type), `operations: MachineOperations` (Protocol type), `clouds:
CloudProvisioner` (Protocol type), `tracker: AllocationTracker`, and
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
matching the task against engines and when recording the `TaskAllocated` /
`TaskFailed` events. No `TaskContext` indirection.

#### Scenario: Successful allocation to a free machine
- **WHEN** `allocate_task(task_id, engines, uow_factory, repository, operations, clouds, start_task_on_machine, tracker, allocation_lock)` is called (with `task_id: TaskId`) and a free compatible machine exists
- **THEN** the task is allocated to the machine via `task.allocate_to(node)`, `task.mark_running()` is applied, the `TaskAllocated` event (carrying `task_id: TaskId`, `node_id: NodeId`, `engine_name=task.engine`) is recorded, and the function returns True

#### Scenario: No free machine matches
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the cloud-fallback path is attempted (or the function returns False if no cloud provider is available)

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a `task_id: TaskId` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without creating a second VM

#### Scenario: Throttle returns None — no tmp-node inserted
- **WHEN** `clouds.select_provider(platforms, counts)` returns `None` because the selected provider's op semaphore is locked
- **THEN** the use case calls `tracker.discard(task_id)` and returns False (no tmp-node inserted, no exception raised)

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine (read from `task.engine`, was `task.context.engine`) is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject("unsupported engine")`, saved, committed, and `TaskFailed` event is recorded (carrying `task_id: TaskId`); `task.error == "unsupported engine"` (bare human string per the error column format contract)

#### Scenario: _find_free_machines returns session-node pairs matched by node_id
- **WHEN** `_find_free_machines(engine, uow_factory, repository)` is called and free compatible machines exist
- **THEN** it returns `list[tuple[MachineSession, Node]]` where each `Node` carries `node_id`, paired by `s.machine.node_id == node.node_id`; the `Node` is sourced from `uow.nodes.list_enabled()` and carried forward so the bind site has `node.node_id`

#### Scenario: _find_free_machines disambiguates dup-IP nodes by node_id
- **WHEN** two enabled nodes share the same IP but have different node_ids (a transient state during cloud provisioning)
- **THEN** `_find_free_machines` matches sessions to nodes by `node_id` (not by IP), so the correct `Node` is bound to the task

#### Scenario: _try_start_on_machine failure does not leak tracker slot
- **WHEN** `uow.nodes.update(node)` or its commit raises after `clouds.allocate` succeeded
- **THEN** the use case best-effort calls `clouds.deallocate(node)` (logged not raised), best-effort calls `_cleanup_tmp_node_best_effort(uow_factory, tmp_node_id, ...)` (logged not raised), and re-raises the original persist exception

#### Scenario: allocate_task reads task.engine not task.context.engine
- **WHEN** `allocate_task.py` is inspected for engine reads
- **THEN** it reads `task.engine` (was `task.context.engine`) for engine matching and `with_event(TaskAllocated, node_id=..., engine_name=task.engine)` / `with_event(TaskFailed, reason=...)` event construction; no `task.context` references

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function SHALL
accept `task_id: TaskId`, `session: MachineSession` (resolved by the
orchestrator via `repository.get_session(task.allocated_node_id)`),
`operations: MachineOperations` (Protocol type, for `download_outputs`),
`engines: EngineRepository`, `uow_factory: Callable[[], AbstractUnitOfWork]`,
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
error classification to `operations.download_outputs(session, ...)`.
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
  downloading the remaining available files first, then apply
  `task.with_download_results(local_folder=local_folder or task.local_folder,
  remote_folder=remote_folder or task.remote_folder)` (falling back to the
  existing field values) followed by `task.fail(error_details)` (or
  `task.complete()` on full success with no permanent errors), save via
  `uow.tasks.save()`, commit, record the corresponding event (`TaskFailed`
  or `TaskCompleted`, both carrying `task_id: TaskId`), call
  `tracker.discard(task_id)`, and return `True`. When both `permanent_errors`
  and `transient_errors` are non-empty, permanent takes priority and the
  function finalises with `task.fail()`.
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

The `_decide_finalisation` helper SHALL apply
`task.with_download_results(local_folder=local_folder or task.local_folder,
remote_folder=remote_folder or task.remote_folder)` (falling back to the
existing field values) BEFORE `.complete()` or `.fail()`. The legacy
`extra_updates` merge block (building `extra_updates = {k: v for k, v in
meta_dict.items() if k not in ("remote_folder", "local_folder", "error")}`
and merging into `task.context.extra`) is REMOVED: `with_download_results`
does NOT touch `extra`. The whole `updated_context =
task.context.replace(...)` construction and the `task.with_context(...)`
calls are deleted. The `meta_add`/`meta_dict` indirection itself is also
REMOVED as a metadata-blob relic: `download_outputs` returns the two paths
as the leading elements of its 4-tuple, and `_decide_finalisation` /
`_finalize_task` receive them as named `local_folder: str, remote_folder:
str` parameters — no intermediate dict is constructed.

`_prepare_store_folder` SHALL read `task.remote_folder` (was
`task.context.remote_folder`), `task.engine` (was `task.context.engine`), and
`task.local_folder` (was `task.context.local_folder`) directly from the
typed fields. The assertion `assert task.remote_folder is not None` SHALL
guard the `task.remote_folder` read (the task is RUNNING — `submit_task`
assigned `remote_folder` post-insert via `with_remote_folder`). No
`TaskContext` indirection.

#### Scenario: Successful consumption
- **WHEN** `consume_task(task_id, session, operations, engines, uow_factory, local_tasks_dir, tracker)` is called (with `task_id: TaskId`) on a completed task and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is loaded via UoW (`uow.tasks.get(task_id)`), output files are downloaded via `operations.download_outputs(session, ..., task_id=task.task_id)`, the task is updated via `task.with_download_results(local_folder=str(store_folder), remote_folder=remote_folder)` then transitioned via `task.complete()` (error stays None), saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with DONE+error
- **WHEN** `operations.download_outputs(session, ...)` returns empty `transient_errors` and non-empty `permanent_errors=[("/remote/1.out", OSError("No such file"))]`
- **THEN** the task is updated via `task.with_download_results(...)` then transitioned via `task.fail("Download error: /remote/1.out: No such file")` (the new format contract), saved, committed, a `TaskFailed` event (carrying `task_id: TaskId`, `reason="Download error: /remote/1.out: No such file"`) is recorded, `tracker.discard(task_id)` is called, and the function returns `True`; `task.error == "Download error: /remote/1.out: No such file"`

#### Scenario: Transient-only download error defers for retry
- **WHEN** `operations.download_outputs(session, ...)` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING` (no status change, no save, no event, no `with_download_results` call), `tracker.discard(task_id)` is NOT called, and the function returns `False` so the orchestrator re-consumes the task on the next producer cycle; `task.error` stays None (nothing was written)

#### Scenario: Mixed transient and permanent errors finalise with DONE+error
- **WHEN** `operations.download_outputs(session, ...)` returns both non-empty `transient_errors=[("/remote/1.out", SFTPRetryExc("timeout"))]` and non-empty `permanent_errors=[("/remote/2.out", OSError("No such file"))]`
- **THEN** permanent takes priority: the task is updated via `task.with_download_results(...)` then transitioned via `task.fail("Download error: /remote/2.out: No such file, /remote/1.out: timeout")` (both lists combined, permanent first — behavior preserved), saved, committed, a `TaskFailed` event (carrying `task_id: TaskId`) is recorded, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Retry-then-success leaves error None
- **WHEN** a task's first consume attempt defers (transient-only, no save, error stays None) and a later attempt downloads successfully and calls `task.complete()`
- **THEN** the persisted task has `error=None` (the deferral wrote nothing; the successful `complete()` does not touch `error`; `with_download_results` does not touch `error`)

#### Scenario: with_download_results does not update extra
- **WHEN** `consume_task._decide_finalisation` finalises a task with `task.extra={"input.in": "ATOMS"}`
- **THEN** the finalised task has `extra={"input.in": "ATOMS"}` unchanged — `with_download_results` does NOT merge, clear, or modify `extra`; the legacy `extra_updates` block is removed

#### Scenario: consume_task reads typed fields not task.context
- **WHEN** `consume_task.py` is inspected for `task.context` or `task.context.X` references
- **THEN** none are present; reads use `task.remote_folder`, `task.engine`, `task.local_folder` (was `task.context.X`); mutations use `task.with_download_results(...)` (was `task.with_context(updated_context)`)

#### Scenario: No adapter imports at runtime
- **WHEN** `consume_task.py` is imported
- **THEN** it does NOT import `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)
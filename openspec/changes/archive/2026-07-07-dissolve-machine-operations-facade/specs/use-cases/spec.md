## MODIFIED Requirements

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
matching the task against engines and when recording the `TaskAllocated` /
`TaskFailed` events. No `TaskContext` indirection.

#### Scenario: Successful allocation to a free machine

- **WHEN** `allocate_task(...)` is called and a free compatible machine exists
- **THEN** the task is allocated via `task.allocate_to(node)`, `task.mark_running()` is applied, `TaskAllocated` event recorded, and the function returns True

#### Scenario: No free machine matches, cloud-fallback attempted

- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the cloud-fallback path is attempted (tracker dedup, capacity check, provider selection, tmp-node insert, cloud allocation, final persist); returns False if no provider available

#### Scenario: Duplicate allocation rejected by tracker

- **WHEN** `allocate_task` is called for a `task_id` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately

#### Scenario: Unsupported engine

- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the task is marked DONE with error via `task.reject(...)`, saved, committed, and `TaskFailed` event recorded

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
status applied, remote directory cleaned by the output_downloader, in-flight
allocation slot released via `tracker.discard(task_id)`); `False` when the
task is deferred for retry (status unchanged, remote directory preserved by
the output_downloader, in-flight allocation slot NOT released).

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

- **WHEN** `consume_task(...)` is called and `output_downloader.download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is completed via `task.complete()`, saved, committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with DONE+error

- **WHEN** `output_downloader.download_outputs` returns non-empty `permanent_errors`
- **THEN** the task is failed via `task.fail(...)`, saved, committed, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Transient-only download error defers for retry

- **WHEN** `output_downloader.download_outputs` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING`, no `tracker.discard` is called, and the function returns `False`

#### Scenario: consume_task reads typed fields not task.context

- **WHEN** `consume_task.py` is inspected for `task.context` references
- **THEN** none are present; reads use `task.remote_folder`, `task.engine`, `task.local_folder` directly

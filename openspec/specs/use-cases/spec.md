# Use Cases

## Purpose

Application-layer use cases that orchestrate domain operations for task
submission, allocation, consumption, and node deallocation.

## Requirements

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

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`,
`config_clouds: Sequence[CloudConfig]`, and `idle_machines: dict[NodeId, float]`
(`NodeId` -> free_since monotonic timestamp). It SHALL NOT accept `repository`
or `operations` (the per-node SSH/cloud teardown lives in `deallocate_node`).

The per-node wrapper `deallocate_node(node, repository, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(node)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `ip`).
`clouds.deallocate(node)` SHALL take the whole `Node` and read `node.cloud`
(provider) and `node.ip` (cloud host) internally. `deallocate_node` SHALL
call `repository.contains(node.node_id)` and `repository.disconnect(node.node_id)`
BEFORE the `if node.cloud:` guard, so SSH teardown is owned by
`deallocate_node` and runs regardless of whether the node is a cloud node.

`deallocate_nodes` SHALL iterate the enabled nodes returned by
`uow.nodes.list_enabled()` and call `uow.nodes.disable(node.node_id)` for
each node whose `node_id` is in `idle_machines` and whose `node_id` is not
in `busy_node_ids` (the node_ids of RUNNING tasks' `allocated_node_id`).

`deallocate_nodes` SHALL return `list[Node]` (was `list[str]`). Phase 2
(collect free disabled cloud nodes) SHALL return the `Node` objects it
reads from `uow.nodes.list_disabled()`, each carrying `node_id`, instead
of discarding them to bare `ip` strings. This eliminates the
`uow.nodes.get(ip)` round-trip lookup previously performed by the
orchestrator's `_deallocator_consumer` to reconstruct the `Node` from `ip`.

`deallocate_nodes` phase 2 SHALL filter disabled nodes by
`node.node_id not in busy_node_ids and node.cloud`. The prior `"." in node.ip`
post-filter SHALL NOT be present — it was dead code from the fake-ip era.

Internal log lines in both `deallocate_nodes` and `deallocate_node` SHALL
include both `node_id` and `ip` for correlation.

#### Scenario: Idle cloud node disabled

- **WHEN** `deallocate_nodes(uow_factory, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` (carrying `node_id`) is included in the returned `list[Node]` for orchestrator-level SSH disconnect and cloud deallocation

#### Scenario: Non-cloud node skipped

- **WHEN** a non-cloud node (`node.cloud is None`) is idle
- **THEN** it is not disabled in phase 1 (filtered by `node.cloud == ccfg.prefix`) and not included in the returned `list[Node]` (phase 2 filters `and node.cloud`)

#### Scenario: Returns disabled Node objects carrying node_id

- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned (was `list[str]` of IPs); each `Node` carries its `node_id`, `ip`, `cloud`, and other fields, so the orchestrator's `_deallocator_consumer` can call `deallocate_node(node, ...)` directly without a `uow.nodes.get(ip)` round-trip lookup

#### Scenario: Phase 2 filters by node_id not in busy_node_ids

- **WHEN** `deallocate_nodes` phase 2 filters disabled nodes
- **THEN** the filter is `node.node_id not in busy_node_ids and node.cloud` — the `"." in node.ip` guard is NOT present (dead code from the fake-ip era; `list_disabled.sql` `WHERE ip <> ''` already excludes tmp-node rows at SQL level)

#### Scenario: Deallocate node brackets cloud delete with disable+remove

- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** the node's SSH session is disconnected via `repository.contains(node.node_id)` + `repository.disconnect(node.node_id)` (before the `if node.cloud:` guard), then the node is disabled via `uow.nodes.disable(node.node_id)` and committed, then `clouds.deallocate(node)` is called, then the node is removed via `uow.nodes.remove(node.node_id)` and committed

#### Scenario: Internal logs include node_id and ip

- **WHEN** `deallocate_node` or `deallocate_nodes` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function in
`yascheduler/application/abandon_node.py` that cleans up a cloud node that
never established its SSH connection, releasing the originating task to
re-allocate on the next cycle. The function SHALL accept `node: Node`,
`clouds: CloudProvisioner` (Protocol type), `uow_factory: Callable[[],
AbstractUnitOfWork]`, and `tracker: AllocationTracker`. It SHALL NOT import
from `yascheduler.infra` at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `repository.disconnect` — by construction the
node was never registered in the repository (that is why it is being
abandoned). The use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `node_id`, `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`, and
   in-memory filter for the task whose `allocated_node_id == node.node_id`.
   This read SHALL happen BEFORE the node-row removal in step 3 — the
   `allocated_node_id` FK is `ON DELETE SET NULL`, so removing the node row
   first would null `allocated_node_id` and the in-memory filter would no
   longer match. Hold the matching task(s) in memory.
3. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `ip`, and the exception and
   re-raised.
4. If exactly one matching task was found in step 2, call
   `tracker.discard(task.task_id)`. If zero or multiple matched, no `discard`
   is called.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `ip` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released

- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node (`node.cloud` non-None) with one TO_DO task whose `allocated_node_id == node.node_id`
- **THEN** `clouds.deallocate(node)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard(task.task_id)` is called for the matching task, and the function returns without raising

#### Scenario: Non-cloud node skips VM deletion

- **WHEN** `abandon_node(...)` is called with `node.cloud is None`
- **THEN** `clouds.deallocate` is NOT called, `uow.nodes.remove(node.node_id)` is still called and committed, and the stuck-task lookup still runs

#### Scenario: Cloud deletion failure does not block DB cleanup

- **WHEN** `clouds.deallocate(node)` raises an exception
- **THEN** the exception is logged at `error` level with `node_id`, `ip`, `cloud`, and the message, `uow.nodes.remove(node.node_id)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: DB remove failure is re-raised

- **WHEN** `uow.nodes.remove(node.node_id)` or its commit raises an exception
- **THEN** the exception is logged at `error` level with `node_id`, `ip`, and the message, and the exception is re-raised

#### Scenario: Internal logs include node_id and ip

- **WHEN** `abandon_node` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields

#### Scenario: No matching TO_DO task

- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_node_id == node.node_id`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple matching TO_DO tasks is logged not fatal

- **WHEN** the stuck-task lookup finds more than one TO_DO task with `allocated_node_id == node.node_id`
- **THEN** a warning is logged, `tracker.discard` is NOT called (ambiguous which task to release), the VM deletion + DB removal still ran, and the function returns without raising

#### Scenario: No adapter imports at runtime

- **WHEN** `abandon_node.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

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
### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`,
`config_clouds: Sequence[CloudConfig]`, and `idle_machines: dict[NodeId, float]`
(`NodeId` -> free_since monotonic timestamp). It SHALL NOT accept `repository`
or `operations` (the per-node SSH/cloud teardown lives in `deallocate_node`).

The per-node wrapper `deallocate_node(node, repository, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(cloud, ip)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `ip`).
`clouds.deallocate(node.cloud, node.ip)` SHALL continue to take `ip`
(ip is the cloud host address, not node identity). `deallocate_node` SHALL
call `repository.contains(node.node_id)` and `repository.disconnect(node.node_id)`
BEFORE the `if node.cloud:` guard, so SSH teardown is owned by
`deallocate_node` and runs regardless of whether the node is a cloud node.

`deallocate_nodes` SHALL iterate the enabled nodes returned by
`uow.nodes.list_enabled()` and call `uow.nodes.disable(node.node_id)` for
each node whose `node_id` is in `idle_machines` and whose `node_id` is not
in `busy_node_ids` (the node_ids of RUNNING tasks' `allocated_node_id`).

`deallocate_nodes` SHALL return `list[Node]` (was `list[str]`). Phase 2
(collect free disabled cloud nodes) SHALL return the `Node` objects it
reads from `uow.nodes.list_disabled()`, each carrying `node_id`, instead
of discarding them to bare `ip` strings. This eliminates the
`uow.nodes.get(ip)` round-trip lookup previously performed by the
orchestrator's `_deallocator_consumer` to reconstruct the `Node` from `ip`.

`deallocate_nodes` phase 2 SHALL filter disabled nodes by
`node.node_id not in busy_node_ids and node.cloud`. The prior `"." in node.ip`
post-filter SHALL NOT be present — it was dead code from the fake-ip era.

Internal log lines in both `deallocate_nodes` and `deallocate_node` SHALL
include both `node_id` and `ip` for correlation.

#### Scenario: Idle cloud node disabled

- **WHEN** `deallocate_nodes(uow_factory, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` (carrying `node_id`) is included in the returned `list[Node]` for orchestrator-level SSH disconnect and cloud deallocation

#### Scenario: Non-cloud node skipped

- **WHEN** a non-cloud node (`node.cloud is None`) is idle
- **THEN** it is not disabled in phase 1 (filtered by `node.cloud == ccfg.prefix`) and not included in the returned `list[Node]` (phase 2 filters `and node.cloud`)

#### Scenario: Returns disabled Node objects carrying node_id

- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned (was `list[str]` of IPs); each `Node` carries its `node_id`, `ip`, `cloud`, and other fields, so the orchestrator's `_deallocator_consumer` can call `deallocate_node(node, ...)` directly without a `uow.nodes.get(ip)` round-trip lookup

#### Scenario: Phase 2 filters by node_id not in busy_node_ids

- **WHEN** `deallocate_nodes` phase 2 filters disabled nodes
- **THEN** the filter is `node.node_id not in busy_node_ids and node.cloud` — the `"." in node.ip` guard is NOT present (dead code from the fake-ip era; `list_disabled.sql` `WHERE ip <> ''` already excludes tmp-node rows at SQL level)

#### Scenario: Deallocate node brackets cloud delete with disable+remove

- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** the node's SSH session is disconnected via `repository.contains(node.node_id)` + `repository.disconnect(node.node_id)` (before the `if node.cloud:` guard), then the node is disabled via `uow.nodes.disable(node.node_id)` and committed, then `clouds.deallocate(node.cloud, node.ip)` is called, then the node is removed via `uow.nodes.remove(node.node_id)` and committed

#### Scenario: Internal logs include node_id and ip

- **WHEN** `deallocate_node` or `deallocate_nodes` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields
### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function in
`yascheduler/application/abandon_node.py` that cleans up a cloud node that
never established its SSH connection, releasing the originating task to
re-allocate on the next cycle. The function SHALL accept `node: Node`,
`clouds: CloudProvisioner` (Protocol type), `uow_factory: Callable[[],
AbstractUnitOfWork]`, and `tracker: AllocationTracker`. It SHALL NOT import
from `yascheduler.infra` at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `repository.disconnect` — by construction the
node was never registered in the repository (that is why it is being
abandoned). The use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node.cloud, node.ip)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `node_id`, `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`, and
   in-memory filter for the task whose `allocated_node_id == node.node_id`.
   This read SHALL happen BEFORE the node-row removal in step 3 — the
   `allocated_node_id` FK is `ON DELETE SET NULL`, so removing the node row
   first would null `allocated_node_id` and the in-memory filter would no
   longer match. Hold the matching task(s) in memory.
3. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `ip`, and the exception and
   re-raised.
4. If exactly one matching task was found in step 2, call
   `tracker.discard(task.task_id)`. If zero or multiple matched, no `discard`
   is called.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `ip` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released

- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node (`node.cloud` non-None) with one TO_DO task whose `allocated_node_id == node.node_id`
- **THEN** `clouds.deallocate(node.cloud, node.ip)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard(task.task_id)` is called for the matching task, and the function returns without raising

#### Scenario: Non-cloud node skips VM deletion

- **WHEN** `abandon_node(...)` is called with `node.cloud is None`
- **THEN** `clouds.deallocate` is NOT called, `uow.nodes.remove(node.node_id)` is still called and committed, and the stuck-task lookup still runs

#### Scenario: Cloud deletion failure does not block DB cleanup

- **WHEN** `clouds.deallocate(node.cloud, node.ip)` raises an exception
- **THEN** the exception is logged at `error` level with `node_id`, `ip`, `cloud`, and the message, `uow.nodes.remove(node.node_id)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: DB remove failure is re-raised

- **WHEN** `uow.nodes.remove(node.node_id)` or its commit raises an exception
- **THEN** the exception is logged at `error` level with `node_id`, `ip`, and the message, and the exception is re-raised

#### Scenario: Internal logs include node_id and ip

- **WHEN** `abandon_node` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields

#### Scenario: No matching TO_DO task

- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_node_id == node.node_id`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple matching TO_DO tasks is logged not fatal

- **WHEN** the stuck-task lookup finds more than one TO_DO task with `allocated_node_id == node.node_id`
- **THEN** a warning is logged, `tracker.discard` is NOT called (ambiguous which task to release), the VM deletion + DB removal still ran, and the function returns without raising

#### Scenario: No adapter imports at runtime

- **WHEN** `abandon_node.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)
### Requirement: Use cases importable from application

The system SHALL expose all use cases from `yascheduler.application`. No use
case SHALL import adapter-specific types (`AllSSHRetryExc`, `SFTPRetryExc`,
`SFTPError`) from `yascheduler.infra` at runtime.

#### Scenario: Import use case
- **WHEN** `from yascheduler.application.submit_task import submit_task` is executed
- **THEN** the function is available

#### Scenario: No adapter runtime imports in use cases
- **WHEN** any use case module is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `SFTPError` from `yascheduler.infra` at runtime

### Requirement: QueryTasks use case

The system SHALL provide a `query_tasks` async function that returns
domain `Task` aggregates matching a jobs- or statuses-based read query,
alongside a `dict[NodeId, Node]` of the nodes allocated to those tasks (for
the caller to project a nested `node` field). The function SHALL accept
`jobs: Sequence[TaskId] | None` (was `Sequence[int] | None`), `statuses:
Sequence[TaskStatus] | None`, and `uow_factory: Callable[[], AbstractUnitOfWork]`.
It SHALL raise `ValueError` if both `jobs` and `statuses` are supplied. It
SHALL open a single Unit of Work, dispatch to `uow.tasks.list_by_status(set(statuses))`
when `statuses` is non-empty or `uow.tasks.list_by_jobs(list(jobs))` (a
`list[TaskId]`) when `jobs` is non-empty, and return `([], {})` when neither
is non-empty (truthiness semantics, matching `yascheduler.client.queue_get_tasks_async`'s
existing dispatch). It SHALL NOT call `uow.commit` (read-only). It SHALL NOT
import from `yascheduler.infra` at runtime.

Within the same single UoW, after fetching tasks, the use case SHALL
batch-load the nodes allocated to those tasks via
`uow.nodes.get_by_ids(list({t.allocated_node_id for t in tasks if
t.allocated_node_id is not None}))` (a single batch round-trip), building
`nodes_by_id: dict[NodeId, Node]`. When no task has an `allocated_node_id`
(all tasks are unallocated), the use case SHALL skip the `get_by_ids` call
and return `(tasks, {})`. The use case SHALL return the tuple
`(tasks, nodes_by_id)`.

The return type widens from `list[Task]` to `tuple[list[Task], dict[NodeId,
Node]]`. This is the only signature change. The use case does NOT project
the nested `node` field into task dicts; that is the facade's responsibility
(see the `package-facades` capability). It returns raw domain objects.

The public `Yascheduler.queue_get_tasks_async(jobs: list[int])` facade is the
sole `int`/`TaskId` boundary on this path: it wraps `[TaskId(i) for i in jobs]`
before calling `query_tasks(jobs=[TaskId(...)], ...)`.

#### Scenario: Query by statuses dispatches to list_by_status
- **WHEN** `query_tasks(jobs=None, statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_status({TaskStatus.TO_DO})` is awaited, `uow.nodes.get_by_ids(...)` is called with the `allocated_node_id`s of the returned tasks, the UoW closes without `commit`, and the returned `(list[Task], dict[NodeId, Node])` tuple is forwarded to the caller

#### Scenario: Query by jobs dispatches to list_by_jobs
- **WHEN** `query_tasks(jobs=[TaskId(1), TaskId(2), TaskId(3)], statuses=None, uow_factory=f)` is called
- **THEN** a UoW is opened via `f()`, `uow.tasks.list_by_jobs([TaskId(1), TaskId(2), TaskId(3)])` is awaited, `uow.nodes.get_by_ids(...)` is called with the `allocated_node_id`s of the returned tasks, the UoW closes without `commit`, and the returned `list[Task]` is forwarded to the caller

#### Scenario: Both jobs and statuses supplied raises ValueError
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=[TaskStatus.TO_DO], uow_factory=f)` is called
- **THEN** `ValueError` is raised and no UoW is opened

#### Scenario: Neither jobs nor statuses returns empty tuple
- **WHEN** `query_tasks(jobs=None, statuses=None, uow_factory=f)` is called
- **THEN** `([], {})` is returned without dispatching to either repository method and without opening a UoW

#### Scenario: Query returns nodes_by_id with resolved nodes
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` is called and task 1 has `allocated_node_id=NodeId("n1")`
- **THEN** `uow.nodes.get_by_ids([NodeId("n1")])` is called, the returned dict `{NodeId("n1"): node}` is included in the `(tasks, nodes_by_id)` tuple

#### Scenario: Query skips get_by_ids when all tasks unallocated
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` is called and task 1 has `allocated_node_id=None`
- **THEN** `uow.nodes.get_by_ids` is NOT called (no node IDs to resolve), and the return is `([task], {})`

#### Scenario: Use case is read-only
- **WHEN** `query_tasks(jobs=[TaskId(1)], statuses=None, uow_factory=f)` runs to completion successfully
- **THEN** `uow.commit()` is never called on the opened UoW

### Requirement: AllocationTracker tracks in-flight cloud allocations

The system SHALL provide an `AllocationTracker` class in
`yascheduler.application.allocation_tracker` that maintains an in-memory
`set[TaskId]` of task_ids with in-flight cloud allocations (was `set[int]`).
The class SHALL expose `add(task_id: TaskId) -> bool` (returns True if newly
added, False if already tracked), `discard(task_id: TaskId) -> None`, and
`__contains__(task_id: TaskId) -> bool`.

The tracker SHALL be constructed once by the orchestrator and injected into
the `allocate_task`, `consume_task`, and `abandon_node` use cases. It is
internal to the orchestrator and never crosses the public `Yascheduler`
facade boundary.

#### Scenario: Add new task to tracker
- **WHEN** `tracker.add(TaskId(42))` is called for an untracked task_id
- **THEN** returns True and `TaskId(42)` is in `tracker`

#### Scenario: Add duplicate task to tracker
- **WHEN** `tracker.add(TaskId(42))` is called while `TaskId(42)` is already tracked
- **THEN** returns False and the set is unchanged

#### Scenario: Discard tracked task
- **WHEN** `tracker.discard(TaskId(42))` is called after a successful allocation or completion
- **THEN** `TaskId(42)` is no longer in `tracker`

#### Scenario: Discard untracked task is a no-op
- **WHEN** `tracker.discard(TaskId(99))` is called for a task not in the tracker
- **THEN** no error is raised and the set is unchanged

#### Scenario: Containment check
- **WHEN** `TaskId(42) in tracker` is evaluated
- **THEN** returns True if `TaskId(42)` is tracked, False otherwise

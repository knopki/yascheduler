## MODIFIED Requirements

### Requirement: ConsumeTask use case

The system SHALL provide a `consume_task` async function that downloads
outputs from a remote machine and finalises or defers the task. The function
SHALL accept `task_id: int`, `ip: str`, `gateway: MachineGateway` (Protocol
type), `engines: EngineRepository`, `uow_factory: Callable[[],
AbstractUnitOfWork]`, `local_tasks_dir: Path`, and `tracker:
AllocationTracker`. It SHALL NOT import `SFTPRetryExc`, `SFTPError`, or
`backoff` from `yascheduler.infra` at runtime.

The function SHALL return `bool`: `True` when the task is finalised (DONE
status applied, remote directory cleaned by the gateway, in-flight allocation
slot released via `tracker.discard(task_id)`); `False` when the task is
deferred for retry (status unchanged, remote directory preserved by the
gateway, in-flight allocation slot NOT released).

The function SHALL delegate SFTP download with retry and error classification
to `gateway.download_outputs()` instead of managing SFTP sessions and backoff
internally. The function SHALL receive `(meta_add, transient_errors,
permanent_errors)` from `download_outputs` and branch on them:

- When `permanent_errors` is non-empty OR `transient_errors` is empty
  (full success, permanent-only errors, or both transient and permanent
  errors), the function SHALL finalise: on permanent errors it SHALL continue
  downloading the remaining available files first (the gateway loop already
  does not break on permanent), then apply `task.fail(error_details)` (or
  `task.complete()` on full success with no permanent errors), save via
  `uow.tasks.save()`, commit, record the corresponding event (`TaskFailed` or
  `TaskCompleted`), call `tracker.discard(task_id)`, and return `True`.
  When both `permanent_errors` and `transient_errors` are non-empty,
  permanent takes priority and the function finalises with `task.fail()`
  (the permanent errors mean the task cannot complete successfully; the
  transient errors are included in the error message but do not trigger a
  retry).
- When `transient_errors` is non-empty AND `permanent_errors` is empty, the
  function SHALL defer: leave the task in `RUNNING` (no status change, no
  save, no event, no `tracker.discard`), and return `False` so the orchestrator
  re-consumes the task on the next producer cycle.

#### Scenario: Successful consumption
- **WHEN** `consume_task(task_id, ip, gateway, engines, uow_factory, local_tasks_dir, tracker)` is called on a completed task and `download_outputs` returns empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is loaded via UoW, output files are downloaded via `gateway.download_outputs()`, the task is transitioned via `task.complete()`, saved via `uow.tasks.save()`, committed, and `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Permanent download error finalises with DONE+error
- **WHEN** `gateway.download_outputs()` returns empty `transient_errors` and non-empty `permanent_errors`
- **THEN** the task is transitioned via `task.fail(error_details)` (after the gateway loop downloaded the remaining available files), saved, committed, a `TaskFailed` event is recorded, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: Transient-only download error defers for retry
- **WHEN** `gateway.download_outputs()` returns non-empty `transient_errors` and empty `permanent_errors`
- **THEN** the task is left in `RUNNING` (no status change, no save, no event), `tracker.discard(task_id)` is NOT called, and the function returns `False` so the orchestrator re-consumes the task on the next producer cycle

#### Scenario: Mixed transient and permanent errors finalise with DONE+error
- **WHEN** `gateway.download_outputs()` returns both non-empty `transient_errors` and non-empty `permanent_errors`
- **THEN** permanent takes priority: the task is transitioned via `task.fail(error_details)` (the error message includes both permanent and transient error details), saved, committed, a `TaskFailed` event is recorded, `tracker.discard(task_id)` is called, and the function returns `True`

#### Scenario: No adapter imports at runtime
- **WHEN** `consume_task.py` is imported
- **THEN** it does NOT import `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)
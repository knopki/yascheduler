## 1. Gateway: classification + return shape + rmtree guard

- [x] 1.1 Modify `download_outputs` in `yascheduler/infra/ssh/gateway.py`: split `sftp_errors` into `transient_errors` and `permanent_errors`; classify each caught per-file exception by `isinstance(err, SFTPRetryExc)` → transient, else → permanent (covers `SFTPNoSuchFile`, `SFTPPermissionDenied`, bare local `OSError`)
- [x] 1.2 Update the return type annotation to `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]` and return `(meta_add, transient_errors, permanent_errors)`
- [x] 1.3 Gate `await sftp.rmtree(path_type(remote_dir))` inside `_session()` on `if not transient_errors:` so the remote dir is preserved when transient errors left files undownloaded
- [x] 1.4 Update the session-level `except Exception` catch-all to append the session error to `transient_errors` (session-level failures are transient — remote dir preserved for retry)
- [x] 1.5 Update the `MODULE_MAP`/`START_CONTRACT`/`START_BLOCK` GRACE-lite annotations in `gateway.py` to reflect the new return shape and rmtree-gating behaviour; bump `VERSION` and add a `START_CHANGE_SUMMARY` entry

## 2. Domain port: Protocol signature

- [x] 2.1 Update `MachineGateway.download_outputs` Protocol signature in `yascheduler/domain/ports.py` to the 3-tuple return type `(meta_add, transient_errors, permanent_errors)`
- [x] 2.2 Update the `START_CONTRACT`/`MODULE_MAP`/`START_CHANGE_SUMMARY` GRACE-lite annotations in `ports.py` if they reference the old return shape; bump `VERSION` and add a `START_CHANGE_SUMMARY` entry (public Protocol signature change)

## 3. Use case: branching + return bool

- [x] 3.1 Change `consume_task` signature in `yascheduler/application/consume_task.py` from `-> None` to `-> bool`
- [x] 3.2 Unpack `meta_add, transient_errors, permanent_errors = await gateway.download_outputs(...)` (3-tuple instead of 2)
- [x] 3.3 Rewrite `_record_finalization_event` (or rename to `_decide_finalisation`) branching: permanent non-empty OR transient empty → finalise (`task.fail` with combined error msg including both lists if both present, or `task.complete` on full success), return `True`; transient-only → no status change, no save, no event, no `tracker.discard`, return `False`
- [x] 3.4 Move `tracker.discard(task_id)` into the finalise branch only (NOT called on deferred retry)
- [x] 3.5 Update `_finalize_task` to propagate the `bool` return from `_record_finalization_event` to `consume_task`'s caller (rename `_record_finalization_event` to `_decide_finalisation` if the rename is applied per 3.3; keep the wrapper structure consistent with the renamed function)
- [x] 3.6 Update the `START_CONTRACT`/`MODULE_MAP`/`START_CHANGE_SUMMARY` GRACE-lite annotations in `consume_task.py`; bump `VERSION`

## 4. Orchestrator: conditional discard + in-flight guard

- [x] 4.1 Add `self._consuming: set[int] = set()` to `Orchestrator.__init__` in `yascheduler/application/orchestrator.py`
- [x] 4.2 In `_task_consumer_producer`, skip yielding `UMessage` for any `task.task_id in self._consuming`
- [x] 4.3 In `_task_consumer_consumer`, wrap the `consume_task` call: `self._consuming.add(task_id)` before `await`, `self._consuming.discard(task_id)` in a `finally` block
- [x] 4.4 Capture `finalised = await consume_task(...)`; replace the unconditional `self._occupancy_started.discard(ip)` with `if finalised: self._occupancy_started.discard(ip)`
- [x] 4.5 Update the `START_CONTRACT`/`START_BLOCK_CONSUME` GRACE-lite annotations to reflect the in-flight guard and conditional discard; bump `VERSION` and add a `START_CHANGE_SUMMARY` entry

## 5. Knowledge graph update

- [x] 5.1 Update `docs/knowledge-graph.xml`: if `M-SSH-GATEWAY` annotations reference `download_outputs`, update the PURPOSE to mention classification + conditional rmtree; add/update `M-APPLICATION-CONSUME` and `M-APPLICATION-ORCHESTRATOR` CrossLinks if the consume->orchestrator bool-signal dependency is new; bump module VERSION attributes if the contracts changed

## 6. Unit tests

- [x] 6.1 Add unit test for `consume_task` success branch: `download_outputs` returns empty `transient_errors` and empty `permanent_errors` → `task.complete()` called, `TaskCompleted` recorded, `tracker.discard` called, returns `True`
- [x] 6.2 Add unit test for `consume_task` permanent-only branch: `download_outputs` returns empty `transient_errors` and non-empty `permanent_errors` → `task.fail()` called with combined error msg, `TaskFailed` recorded, `tracker.discard` called, returns `True`
- [x] 6.3 Add unit test for `consume_task` transient-only branch: `download_outputs` returns non-empty `transient_errors` and empty `permanent_errors` → no status change, no save, no event, `tracker.discard` NOT called, returns `False`
- [x] 6.4 Add unit test for `consume_task` mixed branch: both `transient_errors` and `permanent_errors` non-empty → permanent takes priority, `task.fail()` called with combined msg, returns `True`
- [x] 6.5 Add unit test for orchestrator `_task_consumer_consumer`: `consume_task` returns `True` → `_occupancy_started.discard(ip)` called; returns `False` → NOT called
- [x] 6.6 Add unit test for in-flight guard: a task id in `_consuming` is skipped by the producer; the id is removed from `_consuming` after `consume_task` returns (both True and False paths)

## 7. Update existing tests for signature changes

- [x] 7.1 Find all existing tests that call `download_outputs` or `consume_task` directly or assert on their return values (search `tests/` for `download_outputs`, `consume_task`, `sftp_errors`, `_finalize_task`, `_record_finalization_event`); list the affected files
- [x] 7.2 Update existing tests that unpack `download_outputs` as a 2-tuple `(meta_add, sftp_errors)` to unpack the 3-tuple `(meta_add, transient_errors, permanent_errors)`; update assertions that check `sftp_errors` to check the appropriate split list (transient or permanent)
- [x] 7.3 Update existing tests that assert `consume_task` returns `None` (or ignore its return) to assert the new `bool` return (`True` for finalised, `False` for deferred retry)
- [x] 7.4 Update existing tests for `_record_finalization_event` / `_finalize_task` (and any mock/fake `MachineGateway` implementations of `download_outputs`) to match the new signature and return shape
- [x] 7.5 Run `uv run pytest -m unit` and confirm all existing + new unit tests pass before moving to e2e

## 8. E2E tests

- [x] 8.1 Add e2e test for retry-then-success: a RUNNING task whose first `download_outputs` returns transient errors (remote dir preserved) succeeds on the second consume cycle → task DONE, remote dir removed, `TaskCompleted` recorded
- [x] 8.2 Add e2e test for permanent→DONE+error: a RUNNING task whose `download_outputs` returns permanent errors (e.g. missing output file) → task DONE+error, remote dir removed (after downloading available files), `TaskFailed` recorded
- [x] 8.3 Add e2e test for data-loss regression: assert that when `download_outputs` returns transient errors, the remote directory still exists after `consume_task` returns `False` (the original bug would have rmtree'd it)

## 9. Validation

- [x] 9.1 Run `uv run pytest -m unit` for the new consume_task/orchestrator unit tests and updated existing unit tests
- [ ] 9.2 Run `uv run pytest -m e2e` for the new retry/permanent/regression e2e tests
- [x] 9.3 Run `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`
- [x] 9.4 Run `python3 scripts/grace_check.py` (GRACE-lite validation)
- [x] 9.5 Run `openspec validate --all --json` (spec validation after the change)
- [x] 9.6 Confirm `consume_task.py` does NOT import `SFTPRetryExc`, `SFTPError`, or `backoff` from `yascheduler.infra` at runtime (grep check)
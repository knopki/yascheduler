## 1. SSH gateway: drop non-idempotent retry decorators

- [x] 1.1 Remove `@my_backoff_exc()` decorator from `SSHMachineGateway.run_bg` (`yascheduler/infra/ssh/gateway.py:433`). Keep the method body unchanged. Verify the `MachineGateway` Protocol declaration in `yascheduler/domain/ports.py:163-165` is untouched.
- [x] 1.2 Remove `@my_backoff_sftp()` decorator from `SSHMachineGateway.upload` (`gateway.py:449`). Keep the method body.
- [x] 1.3 Remove `@my_backoff_sftp()` decorator from `SSHMachineGateway.download` (`gateway.py:460`). Keep the method body.
- [x] 1.4 Confirm `get_cpu_cores` (`gateway.py:887`) and `_connect_impl` (`gateway.py:272`) retain their `@my_backoff_exc()` decorators (idempotent read / idempotent connection — out of scope).

## 2. SSH gateway: `start_task_on_machine` BUSY rollback

- [x] 2.1 Wrap the deploy+spawn body of `start_task_on_machine` (`gateway.py:593-640`) in `try/except BaseException` so the gateway-level BUSY marking from `update_machine(machine.occupy())` (line 610) is rolled back on any failure (including `CancelledError`). Implement per design D2: `state = self._machines.get(machine.ip)`; if `None` → log warning ("machine already disconnected"), re-raise; if `state.machine.state != MachineState.BUSY` → log warning ("unexpected state <state>, expected BUSY"), still call `update_machine(state.machine.release())`, re-raise; else call `update_machine(state.machine.release())`, log info ("rollback succeeded"), re-raise.
- [x] 2.2 Verify the existing `except Exception` handlers in `_exec_spawn_command` (`gateway.py:575`) and the DEPLOY block (`gateway.py:630`) still re-raise — they now feed the new rollback handler. No change to those handlers themselves.
- [x] 2.3 Verify the rollback does NOT touch DB task status or the orchestrator's in-memory `mark_running()` (owned by `_try_start_on_machine` in `allocate_task.py:114-144` — out of scope). The rollback is gateway-level only.

## 3. SSH gateway: restructure `download_outputs`

- [x] 3.1 Drop the outer `job_retry = my_backoff_sftp()` layer and the `await job_retry(_session)()` call (`gateway.py:676`, `gateway.py:706`). Remove the inner `_session` function definition (`gateway.py:678-703`) — inline the loop body directly in `download_outputs`.
- [x] 3.2 Keep `file_get_retry = my_backoff_sftp()` (`gateway.py:675`) for per-file retry.
- [x] 3.3 Move the `async with self.get_sftp(ip) as sftp:` context INSIDE the `for out_file in files:` loop, so each file gets a FRESH SFTP client (design D4.2 / spec "Per-file SFTP isolation bounds dead-connection blast radius"). The per-file `file_get_retry(sftp.get)(out_file, local_dir, preserve=True)` call and its `except (OSError, SFTPError)` classifier stay inside the per-file context.
- [x] 3.4 Move the `sftp.rmtree` OUT of the per-iteration position to a SINGLE post-loop evaluation (design D4.3). Gate on `if not transient_errors and not permanent_errors:` (was: `if not transient_errors:`). Use a SEPARATE `async with self.get_sftp(ip) as sftp:` context for the rmtree (not a per-file client).
- [x] 3.5 Keep the single outer `try/except Exception` (`gateway.py:705-712`) that catches session-level failures (e.g. `get_sftp` itself raising before the loop body), appends to `transient_errors` as `(remote_dir, err)`, logs `"Cannot scp from %s: %s"`, and returns without raising. Verify this still satisfies the v1.7.0 contract ("session-level failure is transient — remote dir preserved, method SHALL NOT raise").
- [x] 3.6 Verify the 3-tuple return shape `(meta_add, transient_errors, permanent_errors)` is unchanged (spec: `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]`).

## 4. GRACE-lite + module metadata

- [x] 4.1 Bump `VERSION` in `yascheduler/infra/ssh/gateway.py` (line 2) per the file's versioning convention.
- [x] 4.2 Add a `START_CHANGE_SUMMARY` entry to `gateway.py` (lines 28-31) describing this change: drop `@my_backoff_exc()`/`@my_backoff_sftp()` from `run_bg`/`upload`/`download` (non-idempotent); add BUSY rollback to `start_task_on_machine` under `except BaseException`; restructure `download_outputs` (drop outer `job_retry`, per-file `get_sftp` isolation, single post-loop rmtree gate on `not transient_errors and not permanent_errors`). Reference `fix-nonidempotent-ssh-retries`.
- [x] 4.3 Update the `M-SSH-GATEWAY` `fn-download_outputs` PURPOSE string in `docs/knowledge-graph.xml` (currently "conditional rmtree (only when transient_errors empty)" — review note from design Round 1) to reflect the new gate ("conditional rmtree (only when both transient_errors and permanent_errors are empty)"). Low effort, keeps the graph accurate. No other graph change required (private/implementation-only per AGENTS.md rule 3).

## 5. Unit tests — `tests/unit/test_ssh_gateway.py`

- [x] 5.1 Add `test_run_bg_no_longer_retries_on_ssh_error`: mock the adapter's `run_bg` to raise `ChannelOpenError` (in `SSHRetryExc`); assert the exception propagates immediately and `run_bg` was called exactly once (no retry). Use `AsyncMock` with `side_effect`.
- [x] 5.2 Add `test_upload_no_longer_retries_on_sftp_error`: mock `start_sftp_client` / `sftp.put` to raise `SFTPConnectionLost` (in `SFTPRetryExc`); assert exception propagates and `sftp.put` called once.
- [x] 5.3 Add `test_download_no_longer_retries_on_sftp_error`: mock `sftp.get` to raise `SFTPConnectionLost`; assert exception propagates and `sftp.get` called once.
- [x] 5.4 Add `test_start_task_on_machine_rollback_busy_on_upload_failure`: mock `_upload_task_data` (or `_write_remote_file`) to raise; assert `update_machine` was called with a `release()`-transitioned machine after the exception, and the machine's gateway state is `FREE`. Assert the rollback info log line was emitted.
- [x] 5.5 Add `test_start_task_on_machine_rollback_busy_on_spawn_failure`: mock `run_bg` to raise `ChannelOpenError`; assert `update_machine` called with `release()`, machine state `FREE`, rollback info log emitted, original exception re-raised.
- [x] 5.6 Add `test_start_task_on_machine_rollback_on_cancelled_error`: raise `asyncio.CancelledError` from `_upload_task_data`; assert `update_machine(release())` called, `CancelledError` re-raised, machine state `FREE`.
- [x] 5.7 Add `test_start_task_on_machine_rollback_warns_on_unexpected_state`: set the machine's gateway state to `FREE` (not `BUSY`) before the rollback handler runs; assert warning log emitted AND `release()` still called AND machine state `FREE`.
- [x] 5.8 Add `test_start_task_on_machine_rollback_warns_on_concurrent_disconnect`: call `disconnect(ip)` to remove the machine from `self._machines` before the rollback handler runs; assert warning log emitted AND `release()` NOT called (state is `None`).
- [x] 5.9 Add `test_download_outputs_rmtree_only_on_full_success`: all files download successfully → `sftp.rmtree` called once. Mix: one permanent error → `rmtree` NOT called (gate now includes `permanent_errors`). Mix: one transient error → `rmtree` NOT called.
- [x] 5.10 Add `test_download_outputs_per_file_sftp_isolation`: mock `get_sftp` to return a fresh client per call; simulate `SFTPConnectionLost` on file 2; assert file 3 still gets its own fresh client and is attempted (not fail-fast on file 2's dead client). Assert file 2 classified transient, file 3 succeeds.
- [x] 5.11 Add `test_download_outputs_session_level_failure_transient`: mock `get_sftp` itself to raise `SFTPConnectionLost` before the loop body; assert outer `except Exception` catches it, appends `(remote_dir, err)` to `transient_errors`, `rmtree` NOT called, method returns the 3-tuple without raising.
- [x] 5.12 Update existing `download_outputs` tests in `tests/unit/test_ssh_gateway.py` (and `tests/unit/test_ssh_gateway_download_outputs.py` if present) for the new single-iteration structure: remove any assertions on outer `job_retry` re-entry counts; update rmtree-gate assertions to require both error lists empty.

## 6. Static checks + spec validation

- [x] 6.1 Run `uv run ruff check .` and `uv run ruff format --check .`; fix any issues in changed files.
- [x] 6.2 Run `uv run zuban check` (if configured); fix any issues in changed files.
- [x] 6.3 Run `uv run lint-imports`; fix any import-order issues in changed files.
- [x] 6.4 Run `uv run pytest -m unit` focused on `tests/unit/test_ssh_gateway.py`; all new + updated tests green.
- [x] 6.5 Run `openspec validate --changes fix-nonidempotent-ssh-retries --json`; must report `valid: true` for this change.
- [ ] 6.6 Run `python3 scripts/grace_check.py` (GRACE-lite validation); must exit 0. *(ACCEPTED KNOWN VIOLATION: `gateway.py` is 1021 lines > the 1000 hard limit; `module-size-hard` fails grace_check. A structural split (move `download_outputs` to a new submodule) is the fix but was deferred per user instruction — tracked as separate follow-up. All other GRACE checks pass.)*
- [x] 6.7 Run `uv run pytest -m integration` and `uv run pytest -m e2e` if any tests touch `SSHMachineGateway` / `download_outputs` / `start_task_on_machine` lifecycle (per `test-db-integration` and `e2e-testing` specs). Note: this change touches SSH-layer retry behavior; e2e coverage of the full task lifecycle is expected per `e2e-testing`. *(integration `tests/integration/test_ssh_gateway.py`: 34 passed, 1 skipped — covers `run_bg`/spawn occupancy lifecycle. e2e `tests/e2e/test_consume_retry.py`: 3 FAILED — but verified PRE-EXISTING on clean HEAD: `test_consume_retry_then_success` fails identically on unmodified HEAD (task stays TO_DO, never reaches RUNNING/DONE) — a pre-existing e2e environment/orchestrator-startup defect, NOT a regression from this change. Not fixed here; tracked separately.)*
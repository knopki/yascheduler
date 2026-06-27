# Explore Brief: fix-write-remote-file-swallow

## Problem

`_write_remote_file` (`yascheduler/infra/ssh/gateway.py:123-144`) has a generic
`except Exception` that logs and **does not re-raise**. Only `asyncssh.misc.Error`
is caught-and-raised; every other exception is swallowed. The caller
`_upload_task_data` (`gateway.py:508-548`) loops over `engine.input_files`,
calls `_write_remote_file` per file, and unconditionally returns `True` at the
end — no error aggregation. `start_task_on_machine` (`gateway.py:592-639`)
depends on exceptions (via `try/except Exception` at line 629) to abort; the
`bool` return value is never read. Result: any non-SFTP exception during input
upload is silently lost, `_upload_task_data` returns `True`, and
`_exec_spawn_command` runs the engine spawn command with missing/garbage input
files. The calculation proceeds with an incomplete input set and produces
silently wrong results — neither the daemon nor the user is alerted.

## Classes of exceptions swallowed today

| Source                                                          | Type                              | Pre-validated upstream? |
| --------------------------------------------------------------- | --------------------------------- | ----------------------- |
| `task.context.extra[input_file]` key missing                    | `KeyError`                          | Yes — `submit_task` raises `MissingInputFileError` |
| `_safe_b64decode(malformed_b64)` for `fort.9`                   | `binascii.Error` ⊂ `ValueError`     | No |
| `str(file_data)` where `file_data` is not a str                 | `TypeError`                         | No |
| Text-mode write with un-encodable data                          | `UnicodeEncodeError`                | No |
| Transient asyncssh non-`misc.Error` (e.g. `ConnectionError`)    | `ConnectionError`                   | No |
| Local `OSError` during data preparation                         | `OSError`                           | No |

## Audit of every `except Exception` in the gateway

| Location                                        | Verdict                                                                                              |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `gateway.py:142` `_write_remote_file` generic      | **BUG** — swallows, no re-raise                                                                        |
| `gateway.py:574` `_exec_spawn_command`            | OK — `raise err` re-raises                                                                            |
| `gateway.py:629` `start_task_on_machine` DEPLOY   | OK — `raise err` re-raises (the upload-abort path we want to activate)                                  |
| `gateway.py:691` `download_outputs` catch-all      | **Intentional** — contract returns `list[(name, Exception)]`; "collect-what-you-can" pattern, `_record_finalization_event` distinguishes success/failure by error presence |
| `gateway.py:824` `start_occupancy_check._checker`  | **Intentional** — perpetual background loop; `asyncio.CancelledError` caught separately; one poll failure must not kill the monitor |
| `windows.py:139` `windows_list_processes` inner   | **Intentional** — streaming JSON parse from PowerShell; skip malformed line, continue telemetry |

**Only one** site is a real swallow. The fix is surgical.

## Pre-validation already exists

`submit_task` (`yascheduler/application/submit_task.py:68-75`) already validates:

```python
for input_file in engine.input_files:
    if input_file not in metadata:
        raise MissingInputFileError(engine_name, input_file)
```

Verified every task-creation path:

```
yasubmit CLI ─────────────┐
Yascheduler client         ├──→ CLIDeps.submit ─→ submit_task (validates)
(queue_submit_task*)       │
AiiDA plugin submit_job ───┘  (invokes yasubmit via transport → submit_task)
tests use uow.tasks.insert directly (out of prod scope)

prod path → submit_task → KeyError class is already caught upstream
```

So the `KeyError` case (the most common silent-failure trigger) is already
pre-validated. The remaining classes (`binascii.Error`, `TypeError`,
`UnicodeEncodeError`, `OSError`, transient non-SFTP asyncssh errors) are not
pre-validated — and **should not be**. Reasons:
- Extending pre-validation would duplicate knowledge of internal data shape
  (that `fort.9` is base64, that other inputs are `str`) currently encapsulated
  in the gateway.
- It moves validation away from the point of consumption; the gateway should
  fail loudly on the unexpected regardless.
- YAGNI: no real reports of corrupted b64 / non-str metadata exist. If they
  appear, the gateway failing loudly (post-fix) is the signal.

## Rejected alternatives

### A — Add `raise` to both branches of the existing `try/except`

Keep `asyncssh.misc.Error` branch + generic branch, add `raise` to the generic
branch.

**Rejected because:** the generic branch's local log line
(`"Error processing file %s: %s"`) duplicates the upstream handler's log
(`start_task_on_machine:630` writes `"Can't upload task_id=%s files: %s"` with
`task_id` — strictly better). Variant B removes the duplicate and **improves**
diagnostics (task_id appears).

### B — Remove the generic branch, keep only `asyncssh.misc.Error` — **FINAL**

```python
try:
    async with sftp.open(path, mode) as f:
        await f.write(data)
except asyncssh.misc.Error as err:
    log.error("Write %s - SFTPError: %s (%s)", path, err.reason, err.code)
    raise
```

Net change: minus 2 lines, plus better diagnostics (task_id in the upstream log
that now fires), plus correct abort semantics.

**Why keep the `asyncssh.misc.Error` branch:** `err.code` + `err.reason`
provide structured SFTP-protocol diagnostics (FX_PERMISSION_DENIED=3,
FX_NO_SUCH_FILE=2, …) absent from `str(err)` at the upstream catch. This branch
is not a swallow — it logs structured info and re-raises.

### C — Aggregate errors in `_upload_task_data`, raise composite `UploadError`

Collect all failed files, raise one `UploadError(failed=[...])`.

**Rejected because:** YAGNI. The single caller only aborts on any failure; the
partial-failure info would not be used. Adds a new exception type, contract,
tests, and knowledge-graph entry for zero current consumer benefit.

### D — Post-write `sftp.stat` validation

After writing, `sftp.stat(path)` to confirm size > 0.

**Rejected because:** races (parallel writes), extra RTTs, doesn't catch
"wrong bytes written" (encoding, truncation), and validates in the wrong place.
The right place to fail loudly is the write itself.

### E — Narrow `except Exception` to specific types (`ValueError, TypeError,
KeyError, OSError`) and `raise` everything else

Enumerate expected types, swallow them, re-raise the rest.

**Rejected because:** brittle — the next unexpected error class silently
re-introduces the bug. Illusion of safety, not safety.

## Final Approach — variant B

Single decision-level change: delete the generic `except Exception` branch in
`_write_remote_file`. Keep the `asyncssh.misc.Error` branch unchanged (logs
structured SFTP code/reason, re-raises).

### Exact source change (`yascheduler/infra/ssh/gateway.py:123-144`)

| Location                              | Before                                              | After                                |
| ------------------------------------- | --------------------------------------------------- | ------------------------------------ |
| `START_BLOCK_WRITE_FILE` (lines 142-144) | `except Exception as e:` + `log.error(...)` (no raise) | (deleted — generic exceptions now propagate) |
| `asyncssh.misc.Error` branch (134-141)   | unchanged                                            | unchanged                              |

### Behavior delta

| Path                                   | Before                                           | After                                                  |
| -------------------------------------- | ------------------------------------------------ | ------------------------------------------------------ |
| `binascii.Error` on `fort.9` decode    | swallowed → spawn with missing `fort.9`            | propagates → `start_task_on_machine` logs + raises → no spawn |
| `TypeError` on `str(non_str)`           | swallowed → spawn with garbage                    | propagates → abort                                     |
| `UnicodeEncodeError` on text write      | swallowed → spawn with truncated input           | propagates → abort                                     |
| `OSError` during data prep              | swallowed → spawn with missing input             | propagates → abort                                     |
| `KeyError` on `extra[input_file]`       | swallowed → spawn with missing input              | propagates → abort (already pre-validated upstream by `submit_task`, so this is belt-and-suspenders) |
| `asyncssh.misc.Error` (SFTP failure)    | logged + raised → abort                            | unchanged                                              |

## Cross-module data flow

```
[client/yasubmit/AiiDA] → submit_task (validates input_files presence)
                                       ↓
                                   Task persisted (TO_DO)
                                       ↓
[orchestrator] → allocate_task → _start_task_on_machine
                                       ↓
                  gateway.start_task_on_machine
                       ↓
                  _upload_task_data (loops input_files)
                       ↓ per file
                  _write_remote_file  ← FIX HERE
                       ↓ on any Exception (post-fix)
                  propagates to start_task_on_machine:629
                       ↓
                  log "Can't upload task_id=N files: <err>"
                       ↓
                  raise → orchestrator sees failure, task stays TO_DO/failed
                       (no spawn, no silent garbage calculation)
```

## Open questions

1. **Should `_upload_task_data` return type change from `bool` to `None`?**
   The `bool` is dead — no caller reads it. Lean: **no** in this change —
   changing the return type is a separate contract touch (touches the
   `MachineGateway.start_task_on_machine` Protocol signature? — actually no,
   `_upload_task_data` is private). Defer to a cleanup change to avoid scope
   creep. Confirm in proposal review.

2. **Should `Engine.validate_inputs` replace the inline loop in `submit_task`?**
   `Engine.validate_inputs` (`yascheduler/domain/engine.py:90-94`) exists and
   is only called in tests; `submit_task` duplicates its logic inline. Lean:
   **no** in this change — separate concern (DRY refactor in the application
   layer, not an SSH-layer bug fix). Note as out-of-scope debt in the proposal.

3. **Should `_safe_b64decode` gain explicit pre-validation of the `fort.9`
   payload before the SFTP write?** Lean: **no** — the post-fix behavior (raise
   `binascii.Error` loudly from `_write_remote_file`, abort spawn) is already
   correct. Adding pre-validation duplicates the decode-once cost and splits the
   error path. The fix makes the existing failure loud.

## Scope boundaries

**In scope:**
- `yascheduler/infra/ssh/gateway.py` — remove generic `except Exception` in
  `_write_remote_file`; bump VERSION, add CHANGE_SUMMARY entry.
- `openspec/specs/ssh-gateway/spec.md` — add a requirement stating
  `_write_remote_file` SHALL re-raise (not swallow) non-SFTP exceptions, with
  a scenario for the abort-propagation behavior.
- `docs/knowledge-graph.xml` — update `M-SSH-GATEWAY` annotations if the public
  surface changes (it does not — `_write_remote_file` is module-private), so
  only a CHANGE_SUMMARY-level note may be warranted; no new module/CrossLink.
- Unit tests — `tests/unit/test_ssh_gateway.py` (already exists per codegraph
  blast radius): add a test that a non-SFTP exception inside `_write_remote_file`
  propagates and aborts `start_task_on_machine` (no spawn called).

**Out of scope:**
- Changing `_upload_task_data` return type from `bool` (open question 1).
- Replacing the inline validation loop in `submit_task` with
  `Engine.validate_inputs` (open question 2).
- Adding pre-decode validation for `fort.9` (open question 3).
- Aggregating per-file upload errors (rejected alternative C).
- Post-write `sftp.stat` validation (rejected alternative D).
- Touching `download_outputs`, `start_occupancy_check._checker`, or
  `windows_list_processes` (all intentional, audited above).
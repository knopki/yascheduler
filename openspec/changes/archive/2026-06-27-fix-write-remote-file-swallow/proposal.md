## Why

`_write_remote_file` (`yascheduler/infra/ssh/gateway.py:123-144`) catches every
`Exception` that is not an `asyncssh.misc.Error`, logs it, and **does not
re-raise**. The caller `_upload_task_data` loops over `engine.input_files`,
returns `True` unconditionally, and `start_task_on_machine` depends on
exceptions (via its own `try/except Exception` at line 629) to abort — the
`bool` return is never read. Net effect: a non-SFTP failure while writing any
input file is silently lost, `_upload_task_data` reports success, and
`_exec_spawn_command` runs the engine spawn command with missing or garbage
inputs. The calculation then runs with an incomplete input set and produces
silently wrong results — neither the daemon nor the user is alerted, and the
machine slot is occupied for the duration of a garbage run.

This is a bug fix. The SSH-lifecycle behavior is governed by the `ssh-gateway`
spec, so the spec is updated in the same change (per `AGENTS.md`).

## What Changes

- Remove the generic `except Exception as e:` branch in `_write_remote_file`
  (`gateway.py:142-144`). Non-SFTP exceptions during a remote file write now
  propagate. The `asyncssh.misc.Error` branch (lines 134-141) is unchanged — it
  logs the structured SFTP `code`/`reason` and re-raises, which is correct and
  not a swallow.
- The propagation activates the existing abort path: `start_task_on_machine`
  (line 629) catches the propagated exception, logs
  `"Can't upload task_id=N files: <err>"` (with `task_id` — better diagnostics
  than the swallowed line, which lacked it), and re-raises. The orchestrator
  sees the failure; spawn does not run; the task is not silently launched with
  bad inputs.
- No new exception type, no aggregator, no return-type change, no pre-validation
  extension. The fix is a deletion of a swallowing handler.
- Diagnostics improve, not regress: the lost local line
  (`"Error processing file %s: %s"`) is subsumed by the upstream
  `"Can't upload task_id=%s files: %s"` which carries the `task_id`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `ssh-gateway`: add a requirement stating `_write_remote_file` SHALL re-raise
  (not swallow) any exception that is not an `asyncssh.misc.Error`, so that a
  failed input upload aborts `start_task_on_machine` instead of letting the
  spawn run with missing/garbage inputs. Adds a scenario for the abort
  propagation and a scenario confirming the `asyncssh.misc.Error` structured
  log-and-reraise behavior is preserved.

## Impact

- **Code**: `yascheduler/infra/ssh/gateway.py` — delete the generic
  `except Exception` branch in `_write_remote_file`; bump `VERSION`; add a
  `START_CHANGE_SUMMARY` entry. No other source file changes.
- **Public surface**: none. `_write_remote_file` is module-private; the
  `MachineGateway` Protocol, CLI commands, INI format, DB schema, and AiiDA
  plugin entrypoint are unchanged. The behavior change (abort instead of
  silent spawn) is the correct contract — the silent-spawn behavior was the
  bug.
- **Pre-validation**: unchanged. `submit_task` already validates
  `engine.input_files ⊆ metadata` and raises `MissingInputFileError` before
  persistence, so the common `KeyError` path is already blocked upstream for
  every prod task-creation path (yasubmit CLI, `Yascheduler` client, AiiDA
  plugin — all route through `submit_task`). The fix is belt-and-suspenders
  for that path and the **only** defense for the remaining classes
  (`binascii.Error`, `TypeError`, `UnicodeEncodeError`, `OSError`, transient
  non-SFTP asyncssh errors) which are not pre-validated and should not be.
- **Dependencies / schema**: none. No migration, no new dependency.
- **Callers**: `start_task_on_machine` is the sole caller of
  `_upload_task_data` which is the sole caller of `_write_remote_file`. Its
  existing `except Exception` (line 629) already handles the now-propagated
  exceptions identically to how it handles the already-propagated
  `asyncssh.misc.Error`. No caller-side change needed.
- **Tests**: `tests/unit/test_ssh_gateway.py` (covers `SSHMachineGateway` per
  codegraph blast radius) — add a unit test that a non-SFTP exception raised
  inside `_write_remote_file` propagates through `_upload_task_data` and
  `start_task_on_machine` (spawn is NOT called), and a test that an
  `asyncssh.misc.Error` is still logged with `code`/`reason` and re-raised.
- **GRACE-lite**: `M-SSH-GATEWAY` `CHANGE_SUMMARY` entry in
  `gateway.py` only. No knowledge-graph change: `_write_remote_file` is
  module-private, so no `<annotations>` / `<depends>` / `CrossLink` change is
  required (private-only change per `AGENTS.md` rule 3).
- **Out of scope (noted as debt, not fixed here)**:
  - `_upload_task_data`'s `bool` return is dead (no caller reads it); cleanup
    deferred to avoid scope creep.
  - `Engine.validate_inputs` (`domain/engine.py:90-94`) is only exercised in
    tests; `submit_task` duplicates its loop inline. Consolidation is a
    separate application-layer DRY refactor, not an SSH-layer bug fix.
  - Pre-decoding `fort.9` base64 before the SFTP write — rejected; post-fix
    the loud `binascii.Error` is the correct signal.
  - Per-file upload error aggregation (composite `UploadError`) — rejected as
    YAGNI; the single caller only aborts.
  - Post-write `sftp.stat` validation — rejected; races, extra RTTs, wrong
    validation layer.
- **Relationship to active changes**: `fix-download-rmtree-data-loss` and
  `fix-orchestrator-producer-silent-death` touch disjoint files
  (`download_outputs` / orchestrator producer loop). `schema-migrations`
  touches DB schema. None modify `_write_remote_file` or `_upload_task_data`,
  so this change does not conflict.
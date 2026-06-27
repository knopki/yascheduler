## Context

`yascheduler/infra/ssh/gateway.py` defines `_write_remote_file(sftp, path,
data, log, mode)` — a module-private async helper that writes a single input
file to a remote machine via SFTP. It is called only from
`SSHMachineGateway._upload_task_data`, which loops over `engine.input_files`
and calls it once per file, returning `True` unconditionally at the end.
`_upload_task_data` is called only from `SSHMachineGateway.start_task_on_machine`,
which wraps the upload in `try/except Exception` (line 629) and re-raises on
failure — the `bool` return of both `_upload_task_data` and
`start_task_on_machine` is never read by any caller (verified via codegraph:
the orchestrator calls `start_task_on_machine` and discards its `bool`).

Current exception handling in `_write_remote_file` (lines 130-144):

```python
# START_BLOCK_WRITE_FILE
try:
    async with sftp.open(path, mode) as f:
        await f.write(data)
except asyncssh.misc.Error as err:
    log.error("Write %s - SFTPError: %s (%s)", path, err.reason, err.code)
    raise err
except Exception as e:
    log.error("Error processing file %s: %s", path, e)   # ← swallows, no raise
# END_BLOCK_WRITE_FILE
```

The generic branch is a swallow: `KeyError` (missing `task.context.extra` key —
already pre-validated upstream by `submit_task`, but belt-and-suspenders here),
`binascii.Error` from `_safe_b64decode` on a malformed `fort.9`, `TypeError`
from `str(non_str)`, `UnicodeEncodeError` on text-mode writes, transient
non-SFTP asyncssh errors, and `OSError` all disappear. The swallow means
`_upload_task_data` returns `True`, `start_task_on_machine` proceeds to
`_exec_spawn_command`, and the engine spawn runs with missing or garbage
inputs — a silently wrong calculation.

The audit of every `except Exception` in the gateway (6 sites) confirmed only
this one is a real swallow. The other five are intentional: `_exec_spawn_command`
and `start_task_on_machine`'s DEPLOY block both re-raise; `download_outputs`
aggregates errors into its return tuple by contract; the occupancy-check
checker loop must survive a single poll failure; the Windows process-list
streaming parser skips malformed JSON lines.

Constraint: the application layer (`submit_task`) already pre-validates
`engine.input_files ⊆ metadata` and raises `MissingInputFileError`, so the
`KeyError` class is blocked upstream for every prod task-creation path
(yasubmit CLI, `Yascheduler` client, AiiDA plugin — all route through
`submit_task`, verified via codegraph). The remaining swallowed classes are
not pre-validated and should not be — pre-validation would duplicate
knowledge of the gateway's internal data shape (`fort.9` is base64; other
inputs are `str`) currently encapsulated there.

## Goals / Non-Goals

**Goals:**
- Stop swallowing non-SFTP exceptions in `_write_remote_file` so a failed
  input upload aborts `start_task_on_machine` instead of letting spawn run
  with missing/garbage inputs.
- Preserve the existing `asyncssh.misc.Error` branch unchanged — its
  structured `code`/`reason` log + re-raise is correct and not a swallow.
- Improve, not regress, diagnostics: the propagated exception reaches
  `start_task_on_machine`'s handler which logs with `task_id` (the swallowed
  line did not).
- Keep the fix surgical: a deletion, not a refactor. No new exception type,
  no aggregator, no return-type change, no pre-validation extension.

**Non-Goals:**
- Changing `_upload_task_data`'s `bool` return type to `None` (dead return,
  but a separate contract touch — deferred to avoid scope creep).
- Replacing the inline validation loop in `submit_task` with
  `Engine.validate_inputs` (a `domain/engine.py` method exercised only in
  tests today — a separate application-layer DRY refactor, not an SSH-layer
  bug fix).
- Pre-decoding `fort.9` base64 before the SFTP write (post-fix the loud
  `binascii.Error` is the correct signal).
- Aggregating per-file upload errors into a composite `UploadError` (YAGNI;
  the single caller only aborts).
- Post-write `sftp.stat` validation (races, extra RTTs, wrong layer).
- Touching `download_outputs`, `start_occupancy_check._checker`, or
  `windows_list_processes` — all intentional, audited.

## Decisions

### D1: Delete the generic `except Exception` branch (variant B)

Remove lines 142-144 of `gateway.py`:

```python
# removed:
except Exception as e:
    log.error("Error processing file %s: %s", path, e)
```

The `asyncssh.misc.Error` branch (lines 134-141) is unchanged. After the
deletion, any non-SFTP exception propagates up through `_upload_task_data`
(unchanged — it has no try/except around the per-file loop) into
`start_task_on_machine`'s `try/except Exception` (line 629), which already
logs `"Can't upload task_id=%s files: %s"` with the `task_id` and re-raises.
The orchestrator sees the failure; spawn is not called; the task is not
silently launched with bad inputs.

**Alternatives considered (rejected during explore):**

- **A — add `raise` to the generic branch, keep both.** Rejected: the generic
  branch's local log (`"Error processing file %s: %s"`, no `task_id`) is
  strictly worse than the upstream handler's log
  (`"Can't upload task_id=%s files: %s"`, with `task_id`). Keeping both
  produces duplicate noise without value. B removes the duplicate and
  improves diagnostics.
- **C — aggregate per-file errors in `_upload_task_data`, raise a composite
  `UploadError(failed=[...])`.** Rejected: YAGNI. The single caller only
  aborts on any failure; the partial-failure info would not be consumed.
  Adds a new exception type, contract, tests, and knowledge-graph entry for
  zero current benefit.
- **D — post-write `sftp.stat(path)` validation.** Rejected: races with
  parallel writes, extra RTTs, and doesn't catch "wrong bytes written"
  (encoding/truncation). Validates in the wrong place; the write itself
  should fail loudly.
- **E — narrow `except Exception` to `ValueError, TypeError, KeyError, OSError`
  and re-raise the rest.** Rejected: brittle — the next unexpected exception
  class silently re-introduces the bug. Illusion of safety, not safety. B
  removes the footgun permanently.

### D2: Keep the `asyncssh.misc.Error` branch unchanged

`err.code` and `err.reason` carry structured SFTP-protocol diagnostics
(e.g. `FX_NO_SUCH_FILE=2`, `FX_PERMISSION_DENIED=3`) that are absent from
`str(err)` at the upstream catch. The branch logs these structured fields
then re-raises — it is not a swallow. Deleting it would lose diagnostics
without any benefit. Decision: leave it byte-for-byte unchanged.

### D3: No knowledge-graph update

`_write_remote_file` is module-private. Per `AGENTS.md` GRACE-lite rule 3,
private-only changes require no graph update — no `<annotations>`,
`<depends>`, or `CrossLink` change. Only a `START_CHANGE_SUMMARY` entry in
`gateway.py` (per rule 2: update CHANGE_SUMMARY after editing).

### D4: Spec delta is an ADDED requirement, not MODIFIED

The existing `ssh-gateway` spec (line 33) lists `_write_remote_file` as a
private helper the gateway MAY use, but no Requirement specifies its
exception contract. Therefore the delta adds a new Requirement
("`_write_remote_file` re-raises non-SFTP exceptions") rather than modifying
an existing one. The new Requirement's scenarios cover: (a) a non-SFTP
exception propagates and aborts `start_task_on_machine`; (b) an
`asyncssh.misc.Error` is logged with `code`/`reason` and re-raised.

### D5: Pre-validation is intentionally not extended

`submit_task` already validates input-file presence. Extending
pre-validation to cover `binascii.Error` / `TypeError` / `UnicodeEncodeError`
would (1) duplicate knowledge of the gateway's internal data shape
(`fort.9` is base64; other inputs are `str`) currently encapsulated there,
(2) move validation away from the point of consumption, and (3) address a
non-problem (no real reports of corrupted b64 / non-str metadata exist). The
fix makes the gateway fail loudly on the unexpected — which is the correct
signal. If a real class of pre-validatable failures emerges, a separate
proposal can add pre-validation then.

## Risks / Trade-offs

- **[A previously-swallowed exception class now causes upload abort where
  before it caused a garbage run]** → This is the intended behavior change,
  not a regression. The garbage run was the bug; an aborted upload with a
  logged `task_id` is strictly better (operator can act on it). The task
  stays in its pre-spawn state (TO_DO or whatever the orchestrator leaves it
  in) rather than producing wrong output.
- **[Operator sees new "Can't upload task_id=N files: ..." logs that were
  previously absent]** → This is correct — those failures were happening
  silently before. The new logs are the signal that was missing.
- **[Loss of the local "Error processing file %s: %s" line]** → Subsumed by
  the upstream `"Can't upload task_id=%s files: %s"` which is strictly more
  informative (carries `task_id`). No diagnostic regression.
- **[`asyncssh.misc.Error` branch remains, so SFTP failures still log
  twice?]** → No. The `asyncssh.misc.Error` branch logs the structured
  `code`/`reason` (absent upstream) AND re-raises; the upstream handler then
  logs with `task_id`. These are two different pieces of information
  (structured SFTP code vs. task correlation), not duplication. Acceptable
  and unchanged from today's behavior for SFTP errors.
- **[A test that asserted the swallow behavior exists?]** → Verified via
  codegraph blast radius: `tests/unit/test_ssh_gateway.py`,
  `tests/integration/test_ssh_gateway.py`, and
  `tests/unit/test_ssh_gateway_bg_tasks.py` cover `SSHMachineGateway`. None
  reference `_write_remote_file` directly (it is module-private). The new
  unit test added by this change asserts the propagation; no existing test
  asserts the swallow.

## Migration Plan

No data migration. Source-only deletion.
- Deploy: ship the deletion + spec delta + new unit test together. The
  behavior change (abort instead of silent spawn) is the correct contract;
  there is no rollback to the buggy behavior.
- Rollback: revert the commit. No persisted state, schema, wire format, or
  public API affected.

## Open Questions

None. The three explore-phase open questions are resolved (all "defer / out
of scope"):
1. `_upload_task_data` return type `bool` → `None` → deferred (separate
   cleanup).
2. `Engine.validate_inputs` consolidation in `submit_task` → deferred
   (separate application-layer refactor).
3. Pre-decode `fort.9` validation → rejected (loud `binascii.Error` is the
   correct signal post-fix).
## Why

Three SSH retry defects in `yascheduler/infra/ssh/gateway.py` corrupt
correctness or waste resources on non-idempotent operations:

1. **`run_bg` double-spawns engine processes (HIGH).** `run_bg`
   (`gateway.py:433`) is `@my_backoff_exc()`-decorated and delegates to
   `asyncssh.SSHClientConnection.create_process` — a channel-open + exec
   request. If the remote honours the request and starts the process, but
   the connection drops before the client receives the open-confirmation,
   the client raises `ConnectionLost`/`ChannelOpenError` (both in
   `SSHRetryExc`). Backoff re-enters `run_bg`, re-sends `create_process`,
   and a SECOND engine process starts for the same task on the same
   machine. `occupancy_check` only reports busy/free, not process-count,
   so the orchestrator cannot detect the duplicate. On top of this,
   `start_task_on_machine` (`gateway.py:610`) marks the machine BUSY at
   the gateway BEFORE spawn via `self.update_machine(machine.occupy())`
   and never rolls that back on spawn/upload failure — so a failed
   `run_bg` after 60s of double-spawning leaves the machine stuck BUSY
   with no DB owner and no occupancy monitor (which only installs after
   success).
2. **`download_outputs` redundant nested backoff + sticky rmtree gate
   (MED).** `download_outputs` (`gateway.py:655`) wraps the whole session
   in `job_retry` (outer, 60s) AND each `sftp.get` in `file_get_retry`
   (inner, 60s). On a session-level failure the outer retries re-run the
   entire session (re-opens SFTP, re-iterates all files, re-overwrites
   local copies); pathological worst case is 60s × 60s/file. Separately,
   `transient_errors` is declared OUTSIDE `_session` and never reset, so
   once any file produces a transient error in iteration N, the
   `if not transient_errors` rmtree-gate is False for EVERY subsequent
   iteration — even if a later iteration re-downloads that file
   successfully. After transient-blip-then-success the remote dir is NOT
   cleaned, contradicting the v1.7.0 contract documented at
   `gateway.py:29`.
3. **`upload`/`download` half-written files (LOW).** Both are
   `@my_backoff_sftp()`-decorated; `sftp.put`/`sftp.get` are not
   idempotent. `rg` confirms zero external callers outside `gateway.py`
   (the real upload path is `_upload_task_data` → `_write_remote_file`,
   neither decorated) — so latent, not currently exercised — but the
   decorator on the public methods is inconsistent with the
   non-idempotency principle and the `run_bg` fix.

The existing `ssh-gateway` spec (lines 112-133) *mandates* the backoff
decorators on `run_bg`, `upload`, `download`. This change amends those
requirements because the mandated behavior is the bug.

## What Changes

- **Remove `@my_backoff_exc()` from `run_bg`** (`gateway.py:433`). Spawn
  becomes a single attempt; failure propagates to `_exec_spawn_command`
  → `start_task_on_machine` → caller. The orchestrator already must
  handle spawn-failure-after-60s (the old backoff would have eventually
  raised after 60s too); removing the backoff makes the failure
  immediate instead of risking a double-spawn. **BREAKING** only against
  the buggy retry contract — no public API, CLI, INI, DB, or AiiDA
  surface change.
- **Roll back gateway-level BUSY on `start_task_on_machine` failure**
  (`gateway.py:593-640`). Wrap the deploy+spawn body in
  `try/except BaseException` that releases the machine
  (`update_machine(state.machine.release())`) on any failure (including
  `CancelledError` for daemon shutdown mid-deploy), then re-raises. Log
  a warning if the state was not BUSY at rollback time (logic-error
  guard) and log info on successful rollback. This closes the
  machine-stuck-BUSY leak exposed by removing the `run_bg` backoff.
- **Remove `@my_backoff_sftp()` from `upload` and `download`**
  (`gateway.py:449`, `gateway.py:460`). Both become single-attempt. The
  `MachineGateway` Protocol declaration is preserved (locked by
  `AGENTS.md`); only the decorator is removed.
- **Restructure `download_outputs`** (`gateway.py:655-713`):
  - Drop the outer `job_retry` layer. Keep the per-file
    `file_get_retry`.
  - Open a FRESH `get_sftp(ip)` context per file (not one shared client
    for the loop), so a dropped SFTP connection only invalidates that
    file's retries instead of failing fast on all remaining files.
  - Move the `sftp.rmtree` out of the per-iteration position to a single
    post-loop gate evaluated once on the final state.
  - Gate rmtree on `not transient_errors AND not permanent_errors`
    (was: `not transient_errors` only). A permanent error (e.g.
    `SFTPPermissionDenied`) no longer causes remote-dir deletion that
    would destroy the undownloadable file.
  - Session-level failures (lost connection before/at the loop) still
    escape to the single outer `try/except Exception`, recorded in
    `transient_errors` with the remote dir preserved — matching the
    v1.7.0 contract intent.
- **No new exception types, no return-type change.**
  `download_outputs` keeps its 3-tuple shape. The classification
  (`SFTPRetryExc` → transient, else → permanent) is unchanged.
- **Diagnostics improve, not regress:** new rollback log lines make the
  machine-stuck-BUSY path traceable; per-file SFTP isolation makes
  per-file failures attributable to the file, not the shared session.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `ssh-gateway`: amend the "Backoff on gateway methods" requirement —
  `run_bg`, `upload`, `download` SHALL NOT be backoff-wrapped
  (non-idempotent operations); `get_cpu_cores` retains its backoff
  (idempotent read). Amend the `download_outputs` requirements to
  require per-file SFTP client isolation, a single post-loop rmtree
  gate on `not transient_errors AND not permanent_errors`, and removal
  of the redundant outer session-retry layer. Add a new requirement that
  `start_task_on_machine` SHALL roll back the gateway-level BUSY
  marking on any deploy/spawn failure (including `CancelledError`) so
  the machine is not left stuck BUSY with no DB owner.

## Impact

- **Code**: `yascheduler/infra/ssh/gateway.py` — remove three decorators,
  restructure `download_outputs` (~40 lines), add rollback try/except in
  `start_task_on_machine` (~10 lines); bump `VERSION`; add
  `START_CHANGE_SUMMARY` entry. No other source file changes.
- **Public surface**: none. `MachineGateway` Protocol, CLI commands, INI
  format, DB schema, and AiiDA plugin entrypoint are unchanged. The
  `MachineGateway` Protocol still declares `run_bg`/`upload`/`download`;
  only the SSH implementation drops internal retry. The behavior change
  (single-attempt spawn/upload/download) is the correct contract — the
  retry was the bug.
- **Caller — `start_task_on_machine`**: sole internal caller of
  `run_bg`/`_upload_task_data`/`_exec_spawn_command`. The new rollback
  closes the machine-stuck-BUSY leak; the existing `except Exception`
  handlers in `_exec_spawn_command` (`gateway.py:575`) and
  `start_task_on_machine`'s DEPLOY block (`gateway.py:630`) still
  re-raise, now feeding the new rollback.
- **Caller — orchestrator `_start_task_on_machine` /
  `_try_start_on_machine`** (`allocate_task.py:114-144`): unchanged.
  `_try_start_on_machine` already handles `start_task_on_machine` raising
  (exception propagates, in-memory `mark_running()` discarded, task stays
  TO_DO in DB, next allocator tick retries — possibly on a different
  machine). Removing `run_bg`'s backoff makes this failure path MORE
  LIKELY (a single SSH blip now fails immediately instead of self-healing
  for 60s); this is the intended fail-fast trade-off. Documented as an
  explicit behavioral change, not a regression.
- **Caller — `download_outputs` consumer** (orchestrator consume flow):
  unchanged. The single outer `try/except Exception` in
  `download_outputs` preserves the "session-level failure is transient,
  remote dir preserved, method does not raise" contract. The caller's
  existing transient-error handling (deferred consumption, next-cycle
  retry) continues to work.
- **Dependencies / schema**: none. No migration, no new dependency.
- **Tests**: `tests/unit/test_ssh_gateway.py` — add: `run_bg` no longer
  retries (raises immediately on `ChannelOpenError`);
  `start_task_on_machine` rolls back BUSY on upload failure AND on spawn
  failure (machine released, warning logged if state was not BUSY);
  `upload`/`download` no longer retry; `download_outputs` rmtree gated
  on `not transient_errors AND not permanent_errors`;
  `download_outputs` per-file SFTP isolation (one dropped connection
  does not fail-fast the remaining files);
  `download_outputs` session-level failure still transient and preserves
  remote dir. Update existing `download_outputs` tests for the new
  single-iteration structure (no outer `job_retry`).
- **GRACE-lite**: `M-SSH-GATEWAY` `CHANGE_SUMMARY` entry in
  `gateway.py`. No knowledge-graph change: all touched methods are
  either module-private (`_upload_task_data`, `_exec_spawn_command`) or
  have unchanged public signatures (`run_bg`/`upload`/`download` lose a
  decorator but keep signatures; `download_outputs` return shape
  unchanged). No `<annotations>` / `<depends>` / `CrossLink` change
  required (private/implementation-only change per `AGENTS.md` rule 3).
- **Out of scope (noted as debt, not fixed here)**:
  - Removing the dead `upload`/`download` public methods entirely —
    rejected; `AGENTS.md` locks the `MachineGateway` Protocol surface.
  - Engine-contract idempotent-spawn guard (e.g. `pgrep -f <task_dir> ||
    <spawn>` in `engine.spawn`) — deferred; would require an `engine`
    spec change and per-platform guards. Pair with this change if
    empirical double-spawn rate is non-trivial post-fix.
  - `_upload_task_data` `bool` return is dead — cleanup deferred (also
    noted in `fix-write-remote-file-swallow`).
  - Classifying network `OSError` subclasses
    (`ConnectionResetError`, `BrokenPipeError`) as transient in
    `download_outputs` — pre-existing classification gap, deferred.
  - Adding a caller-level retry of whole `download_outputs` in the
    orchestrator consume flow to compensate for removing the inner
    session-retry — deferred; the existing transient-error deferral
    path is sufficient.
- **Relationship to other changes**: `fix-write-remote-file-swallow`
  touches `_write_remote_file` (disjoint from this change's
  `run_bg`/`upload`/`download`/`download_outputs`/`start_task_on_machine`
  rollback). `fix-download-rmtree-data-loss` (already merged in HEAD)
  established the v1.7.0 `download_outputs` 3-tuple contract this change
  builds on (its `CHANGE_SUMMARY` entry at `gateway.py:29` is the
  contract referenced in the Why section). `fix-orchestrator-producer-silent-death`
  touches disjoint orchestrator files. `schema-migrations` touches DB
  schema. None modify the methods this change touches, so no conflict.
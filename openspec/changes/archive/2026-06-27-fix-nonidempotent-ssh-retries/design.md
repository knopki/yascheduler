## Context

`yascheduler/infra/ssh/gateway.py` (v1.7.0) wraps three non-idempotent
SSH operations in `backoff.on_exception` decorators that retry for up to
60 seconds on transient exception classes. The retry was added for
resilience but is incorrect for non-idempotent operations: a successful
remote side-effect followed by a lost client confirmation produces a
duplicate side-effect on retry. A separate defect in
`download_outputs`'s nested backoff structure wastes resources and
breaks the v1.7.0 rmtree contract. A latent leak in
`start_task_on_machine` leaves machines stuck BUSY at the gateway
whenever spawn fails — masked until now by the `run_bg` backoff's 60s
self-heal window, but exposed once that backoff is removed.

The relevant code (verified via codegraph + Read):

- `my_backoff_exc` (`gateway.py:85-90`): `partial(backoff.on_exception,
  wait_gen=backoff.fibo, max_time=60, exception=SSHRetryExc)`.
- `my_backoff_sftp` (`gateway.py:92-97`): same shape, `SFTPRetryExc`.
- `SSHRetryExc` (`platform/protocol.py:85-96`): includes
  `ConnectionLost`, `ChannelOpenError`, `OSError`, `asyncio.TimeoutError`.
- `SFTPRetryExc` (`platform/protocol.py:71-84`): includes
  `SFTPConnectionLost`, `SFTPFailure`, `asyncio.TimeoutError`.
- `run_bg` (`gateway.py:433-443`): `@my_backoff_exc()`; delegates to
  `asyncssh.SSHClientConnection.create_process` via the adapter.
- `upload` (`gateway.py:449-454`): `@my_backoff_sftp()`; `sftp.put`.
- `download` (`gateway.py:460-467`): `@my_backoff_sftp()`; `sftp.get`.
- `download_outputs` (`gateway.py:655-713`): outer `job_retry` wraps the
  whole `_session`; inner `file_get_retry` wraps each `sftp.get`;
  `transient_errors`/`permanent_errors` declared outside `_session`;
  rmtree gate `if not transient_errors` inside the per-iteration
  position.
- `start_task_on_machine` (`gateway.py:593-640`): calls
  `self.update_machine(machine.occupy())` at line 610 (marks BUSY at the
  gateway), then DEPLOY block (upload) + `_exec_spawn_command` (spawn).
  No try/finally around the occupy — on any exception the machine stays
  BUSY.
- `_try_start_on_machine` (`allocate_task.py:114-144`): calls
  `task.allocate_to(ip).mark_running()` in-memory, then
  `start_task_on_machine`; persists only after success. On exception
  the in-memory state is discarded; the task stays TO_DO in DB.
- `rg` confirms zero external callers of `.upload()`/`.download()`/
  `.run_bg()` outside `gateway.py` — the public methods are Protocol
  surface only. The real upload path is `_upload_task_data` →
  `_write_remote_file` (neither decorated).

The existing `ssh-gateway` spec (lines 112-133) mandates the backoff
decorators on `run_bg`, `upload`, `download`, `get_cpu_cores`. That
mandate is the bug for the three non-idempotent operations;
`get_cpu_cores` is an idempotent read and keeps its decorator.

Constraint: `AGENTS.md` locks the `MachineGateway` Protocol, CLI, INI,
DB schema, AiiDA entrypoint. This change touches none of those — only
the SSH implementation's internal retry + rollback behavior, plus a
spec delta on `ssh-gateway`.

A prior `k-reviewer-fast` review of the planned code (logged in
explore) made four adjustments folded into this design:

- **A1 (🔴)**: `download_outputs` SHALL open a fresh `get_sftp(ip)`
  context per file, not one shared client for the loop. A dropped SFTP
  connection on a shared client makes every subsequent per-file retry
  fail fast — wasting up to 60s and mis-classifying remaining files as
  transient without actually retrying them.
- **A2 (🟡)**: The rmtree gate SHALL be `not transient_errors AND not
  permanent_errors` (was: `not transient_errors` only). Permanent
  errors (e.g. `SFTPPermissionDenied`) shall no longer cause
  remote-dir deletion that destroys the undownloadable file.
- **A3 (🟡)**: `download` SHALL also lose `@my_backoff_sftp()`, for
  symmetry with `upload` (same non-idempotency argument; same
  zero-caller status).
- **A4 (🟡)**: The `start_task_on_machine` rollback SHALL always call
  `release()` (not silently skip when state was not BUSY) and SHALL
  log a warning if the state was unexpected — making the state
  invariant explicit in logs rather than hiding logic errors.

## Goals / Non-Goals

**Goals:**
- Eliminate `run_bg`'s double-spawn window by making spawn a single
  attempt. Failure propagates immediately to the caller.
- Close the machine-stuck-BUSY leak in `start_task_on_machine` by
  rolling back the gateway-level `occupy()` on any deploy/spawn
  failure (including `CancelledError`).
- Fix `download_outputs`'s redundant nested backoff (drop outer
  `job_retry`), sticky rmtree gate (move gate to single post-loop
  evaluation), and shared-dead-SFTP-client failure mode (per-file
  `get_sftp` context).
- Make the rmtree gate conservative: preserve the remote dir whenever
  any error (transient or permanent) leaves files undownloaded.
- Remove `@my_backoff_sftp()` from `upload` and `download` for
  consistency with the non-idempotency principle (latent fix — zero
  external callers today).
- Preserve the `MachineGateway` Protocol, CLI, INI, DB, AiiDA
  surfaces unchanged.
- Preserve `download_outputs`'s 3-tuple return shape and
  non-raising contract.

**Non-Goals:**
- Removing the dead `upload`/`download` public methods — `AGENTS.md`
  locks the Protocol surface.
- Engine-contract idempotent-spawn guard (`pgrep -f <task_dir> ||
  <spawn>` in `engine.spawn`) — would require an `engine` spec change
  and per-platform guards. Pair with this change if empirical
  double-spawn rate is non-trivial post-fix; out of scope here.
- `_upload_task_data` `bool` return cleanup — deferred (also noted in
  `fix-write-remote-file-swallow`).
- Classifying network `OSError` subclasses
  (`ConnectionResetError`, `BrokenPipeError`) as transient in
  `download_outputs` — pre-existing classification gap, deferred.
- Adding a caller-level retry of whole `download_outputs` in the
  orchestrator consume flow — deferred; the existing
  transient-error deferral path is sufficient.
- Touching `get_cpu_cores`'s backoff — it is an idempotent read and
  retains its decorator.
- Touching `_connect_impl`'s backoff — connection establishment is
  idempotent and retains its decorator.

## Decisions

### D1: Drop `@my_backoff_exc()` from `run_bg` (single-attempt spawn)

Spawn is a single decision, not a retry-until-it-works operation.
`asyncssh.create_process` is non-idempotent: the remote may have
started the process when the client sees a confirmation loss. Retrying
risks a duplicate engine process on the same task — undetectable by
`occupancy_check` (busy/free, not process-count). Remove the decorator;
let the failure propagate.

**Alternatives considered (rejected during explore):**

- **B — idempotent spawn template** (`pgrep -f <task_dir> || <spawn>`
  in `engine.spawn`). Engine-defined, engine-owned; works regardless of
  SSH-layer behavior. Rejected here: forces every engine's `spawn` to
  embed a guard, breaks the public engine-contract stability rule
  (`AGENTS.md`), needs per-platform guards (Windows PowerShell), and is
  racy if `pgrep` matches unrelated processes. Pair with D1 as a
  follow-up if empirical double-spawn rate is non-trivial.
- **C — gateway-level guard** (call `occupancy_check(ip, engine)`
  before each `run_bg` attempt; skip spawn if busy). Rejected: race
  between check and spawn; couples `run_bg` to engine semantics;
  doesn't help if the first attempt's process is alive-but-not-yet-
  detected by pgrep. Fragile.
- **D — wrap upload+spawn in one guarded retry at
  `start_task_on_machine` level**. Rejected: more moving parts,
  couples layers, still racy if the orphan hasn't appeared in pgrep
  yet. Over-engineered for the actual failure rate.

D1 alone eliminates the double-spawn window. The orchestrator already
handles spawn-failure (task stays TO_DO, next tick retries) — the old
backoff would have raised after 60s anyway, so D1 makes the failure
immediate instead of risking a duplicate.

### D2: Roll back gateway-level BUSY on `start_task_on_machine` failure

Wrap the deploy+spawn body (lines 610-637) in
`try/except BaseException` that releases the machine and re-raises.
`BaseException` (not `Exception`) so `CancelledError` during daemon
shutdown mid-deploy also rolls back — otherwise a shutdown between
upload and spawn leaves the machine BUSY forever.

The rollback:

1. `state = self._machines.get(machine.ip)` — guard against concurrent
   `disconnect(ip)` having already removed the state.
2. If `state is None`: log a warning (machine already disconnected),
   re-raise without rollback.
3. If `state.machine.state != MachineState.BUSY`: log a warning
   (unexpected state — logic error somewhere), still call
   `update_machine(state.machine.release())` to enforce the invariant,
   re-raise.
4. Else: call `update_machine(state.machine.release())`, log info
   (rollback succeeded), re-raise.

**Why always release (not skip on non-BUSY):** per A4, silently
skipping when state is not BUSY hides logic errors. Always releasing
makes the invariant explicit and recoverable; the warning makes the
unexpected-state case traceable in logs without leaving the machine
stuck.

**Why not just `Exception`:** `CancelledError` is a real scenario
during daemon shutdown. Without `BaseException`, a shutdown between
`occupy()` and `_exec_spawn_command` leaves the machine BUSY at the
gateway with no owner in the DB and no occupancy monitor installed
(that happens only after success). The rollback is idempotent
(`release()` on an already-FREE machine is a no-op dataclass
transition), so the cost of catching `BaseException` is zero risk.

**`KeyboardInterrupt`/`SystemExit` interaction:** `BaseException`
catches these too. In a long-running daemon, a `KeyboardInterrupt` at
the moment of deployment rollback causes a machine release — harmless
(machine becomes FREE, picked up on restart). `SystemExit` similarly
harmless. Acceptable.

### D3: Drop `@my_backoff_sftp()` from `upload` and `download`

Both wrap non-idempotent `sftp.put`/`sftp.get` in retry. Zero external
callers (verified via `rg`), so latent — but the decorator is
inconsistent with D1's principle and the public surface contract. Per
A3, drop both decorators. The methods stay (Protocol locked); only the
retry goes.

### D4: Restructure `download_outputs` — drop outer `job_retry`, per-file SFTP isolation, single post-loop rmtree gate

**D4.1: Drop outer `job_retry`.** The per-file `file_get_retry` already
handles transient per-file errors. The outer layer re-ran the entire
session on session-level failure — re-opening SFTP, re-iterating all
files, re-overwriting local copies, with a pathological 60s × 60s/file
worst case. Session-level failures now escape to a single outer
`try/except Exception` that records them in `transient_errors` with
the remote dir preserved — matching the v1.7.0 contract intent
("session-level failure is transient — the remote directory is
preserved for retry").

**D4.2: Per-file `get_sftp(ip)` context (per A1).** Open a fresh SFTP
client per file inside the `for out_file in files:` loop, wrapping
each `file_get_retry(sftp.get)(...)` call. A dropped SFTP connection
on file N invalidates only file N's retries; files N+1..M get their own
fresh clients and retry normally. The rmtree path (after the loop) gets
its own separate `get_sftp(ip)` context. This bounds the
dead-connection blast radius to one file instead of the whole loop.

**D4.3: Single post-loop rmtree gate, `not transient_errors AND not
permanent_errors` (per A2).** Move the `sftp.rmtree` out of the
per-iteration position (which only made sense under the old outer
`job_retry` re-entry model) to a single evaluation after the loop,
on the final aggregated state. Gate on both error lists: any error
(transient or permanent) preserves the remote dir. Conservative — a
permanent error (e.g. `SFTPPermissionDenied`) no longer causes
remote-dir deletion that destroys the undownloadable file. Trade-off:
stale remote dirs accumulate on permanent-error paths; a separate
TTL-based cleanup mechanism would be needed for permanent-machine
scenarios (deferred — out of scope).

**D4.4: `transient_errors`/`permanent_errors` stay outside `_session`
equivalent — but there is no `_session` inner function anymore.** With
the outer `job_retry` gone, the loop body is inline in
`download_outputs`. The state lists are local to `download_outputs` and
populated once per file. The sticky-gate bug (state declared outside a
re-entered `_session` and never reset between re-entries) is
structurally impossible — there is no re-entry.

**Structure sketch (not line-by-line impl):**

```
async def download_outputs(self, ip, remote_dir, local_dir, files, task_id=None):
    meta_add = [...]
    transient_errors = []
    permanent_errors = []
    path_type = self.get_path(ip)
    file_get_retry = my_backoff_sftp()   # keep per-file retry

    try:
        for out_file in files:
            try:
                async with self.get_sftp(ip) as sftp:           # fresh per file
                    await file_get_retry(sftp.get)(out_file, local_dir, preserve=True)
            except (OSError, SFTPError) as err:
                # classify into transient/permanent (unchanged logic)
                ...
        # single post-loop rmtree gate, conservative
        if not transient_errors and not permanent_errors:
            async with self.get_sftp(ip) as sftp:
                await sftp.rmtree(path_type(remote_dir))
    except Exception as err:
        # session-level failure (e.g. get_sftp itself raises before loop body)
        self._log.warning("Cannot scp from %s: %s", remote_dir, err)
        transient_errors.append((remote_dir, err))

    return meta_add, transient_errors, permanent_errors
```

**Alternatives considered (rejected during explore / review):**

- **E — keep outer `job_retry`, drop inner `file_get_retry`.** Single
  layer. Rejected: a single transient per-file error re-runs the
  entire session (re-downloads everything); loses per-file
  transient/permanent classification granularity.
- **F — keep both backoffs, reset state inside `_session`.** Fixes the
  sticky-gate bug but not the redundant-nesting latency/cost problem.
- **G — keep one shared SFTP client for the loop.** Rejected per A1:
  dead-connection blast radius is the whole loop, not one file.
- **H — add fast-fail on connection-level errors mid-loop.** Latency
  improvement, not a correctness fix; D4.2 (per-file client) solves it
  more cleanly by construction.

### D5: Spec delta amends existing requirements (MODIFIED, not ADDED)

The existing `ssh-gateway` spec has:

- "Backoff on gateway methods" (lines 112-133) — mandates decorators
  on `run_bg`, `upload`, `download`, `get_cpu_cores`. This change
  amends it: `run_bg`/`upload`/`download` SHALL NOT be backoff-wrapped;
  `get_cpu_cores` retains its decorator. **MODIFIED** (full updated
  requirement block).
- `download_outputs` requirements (lines 18-35, 73-94) — govern
  session management, per-file retry, classification, rmtree gate,
  session-level failure handling. This change amends them: per-file
  SFTP client isolation, single post-loop rmtree gate on both error
  lists, removal of the outer session-retry layer. **MODIFIED**.
- `start_task_on_machine` requirement (lines 41-47) — governs the
  method's shape but not its failure rollback. This change adds a new
  requirement for the rollback contract. **ADDED** (new requirement,
  not a modification — the existing one doesn't cover rollback).

### D6: No knowledge-graph update

All touched methods are either module-private (`_upload_task_data`,
`_exec_spawn_command`) or have unchanged public signatures
(`run_bg`/`upload`/`download` lose a decorator but keep signatures;
`download_outputs` return shape unchanged;
`start_task_on_machine` signature unchanged). Per `AGENTS.md` GRACE-lite
rule 3, private/implementation-only changes require no graph update —
no `<annotations>` / `<depends>` / `CrossLink` change. Only a
`START_CHANGE_SUMMARY` entry in `gateway.py` (rule 2).

## Risks / Trade-offs

- **[A single SSH blip during spawn now fails the task start
  immediately instead of self-healing for 60s]** → Intended fail-fast
  trade-off. The orchestrator already handles spawn-failure (task
  stays TO_DO, next allocator tick retries — possibly on a different
  machine). The 60s self-heal was buying reliability at the cost of
  correctness (double-spawn risk). Documented as an explicit
  behavioral change in `proposal.md`. Mitigation: monitor spawn-failure
  rate post-deploy; if elevated, pair with the engine-contract
  idempotent-spawn guard (D1 alternative B).
- **[Machine-stuck-BUSY leak now visible]** → The leak was always
  present (masked by the `run_bg` backoff's self-heal window). D2
  closes it. The new rollback log lines make it traceable. No
  regression — the old code also stuck the machine BUSY if the 60s
  backoff ultimately raised.
- **[`download_outputs` permanent errors now preserve the remote dir,
  leading to stale-dir accumulation]** → Conservative trade-off per
  A2. A separate TTL-based cleanup mechanism for permanent-machine
  scenarios is deferred (out of scope). Mitigation: the
  `permanent_errors` list is returned to the caller, which can log/
  alert on it; an operator can clean stale dirs manually until the TTL
  mechanism lands.
- **[Per-file `get_sftp(ip)` opens N SFTP channels instead of 1]** →
  Cost: N channel opens per download cycle. asyncssh multiplexes
  channels over one TCP connection; the per-channel open cost is small
  vs. the file transfer cost. Benefit: a dropped channel invalidates
  only one file's retries. Acceptable trade-off. Mitigation: if the
  channel-open cost becomes measurable, batch files under a shared
  client with a dead-channel detection + fresh-client fallback (D4.2
  alternative H refined — deferred).
- **[`BaseException` in `start_task_on_machine` catches
  `KeyboardInterrupt`/`SystemExit`]** → Harmless in a daemon context
  (machine release on shutdown is correct). Documented in D2.
- **[A test that asserted the old backoff behavior exists?]** → To
  verify during apply: `tests/unit/test_ssh_gateway.py`,
  `tests/integration/test_ssh_gateway.py`,
  `tests/unit/test_ssh_gateway_bg_tasks.py` cover `SSHMachineGateway`.
  The apply phase will check for assertions on `run_bg`/`upload`/
  `download`/`download_outputs` retry counts and update them to assert
  single-attempt behavior. The new unit tests added by this change
  assert the new behavior.

## Migration Plan

No data migration. Source-only changes.
- Deploy: ship the decorator removals + `download_outputs`
  restructure + `start_task_on_machine` rollback + spec delta + new
  unit tests together. The behavior changes (single-attempt
  spawn/upload/download; conservative rmtree; BUSY rollback) are the
  correct contract — there is no rollback to the buggy behavior.
- Rollback: revert the commit. No persisted state, schema, wire
  format, or public API affected.
- Observability post-deploy: watch for (a) new
  `"SSH spawn cmd error: ..."` logs (spawn failures now immediate),
  (b) new rollback log lines (machine released on deploy/spawn
  failure), (c) `download_outputs` permanent-error paths leaving
  remote dirs in place (expected, conservative). If (a) spikes, pair
  with the engine-contract idempotent-spawn guard (D1 alternative B).

## Open Questions

None. The explore-phase open questions are resolved (all "defer / out
of scope"):
1. Engine-contract idempotent-spawn guard → deferred (D1 alternative
   B); pair with this change if empirical double-spawn rate is
   non-trivial post-deploy.
2. `_upload_task_data` `bool` return cleanup → deferred (also noted in
   `fix-write-remote-file-swallow`).
3. Network `OSError` subclass transient classification in
   `download_outputs` → pre-existing gap, deferred.
4. Caller-level retry of whole `download_outputs` → deferred; existing
   transient-error deferral path is sufficient.
5. TTL-based cleanup for stale remote dirs on permanent-error paths →
   deferred (D4.3 trade-off).
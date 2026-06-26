## Context

`SSHMachineGateway.download_outputs` (`yascheduler/infra/ssh/gateway.py:651`) currently runs `await sftp.rmtree(path_type(remote_dir))` unconditionally after a per-file download loop that collects per-file `(OSError, SFTPError)` failures into `sftp_errors`. When some files fail transiently (network blip, connection lost), the remote directory is destroyed along with the undownloaded files. `consume_task` then calls `task.fail()` (RUNNING → terminal DONE), and the orchestrator's `_task_consumer_producer` only re-yields `RUNNING` tasks — so the task is never retried and the lost outputs are irrecoverable. Data loss.

The classification of which failures are retryable is already encoded in the codebase: `SFTPRetryExc` (`infra/ssh/platform/protocol.py:71`) is the tuple of transient SFTP exception types that `my_backoff_sftp` retries on. The complement (within `SFTPError`) is permanent — notably `SFTPNoSuchFile` (the engine did not produce the output) and `SFTPPermissionDenied`. The `use-cases` spec (`openspec/specs/use-cases/spec.md:76-77,132-133,141`) forbids `consume_task` from importing `SFTPRetryExc`, `SFTPError`, or `backoff` at runtime, so classification MUST live in the gateway and be communicated to the use case as structured data, not raw exception types.

## Goals / Non-Goals

**Goals:**
- Eliminate the data-loss path: `rmtree` runs only when the task is being finalised (full success, or permanent error after downloading whatever is available).
- Enable retry of transient-only download failures by leaving the task in `RUNNING` so the existing consume producer-consumer loop re-yields it on the next cycle.
- Keep the classification logic in the gateway (the only layer that may import SFTP types); the use case branches on structured booleans/lists.
- No DB schema change, no new `TaskStatus`, no per-attempt DB writes.

**Non-Goals:**
- No new task status (`DOWNLOAD_FAILED` or similar). Retry stays in `RUNNING`.
- No DB migration.
- No per-attempt counter persisted in `context.extra` (an optional in-memory counter is the only cap mechanism considered, and it is deferred/optional).
- No blocking of cloud-node deallocation during retry. If a cloud node is reaped while a task is in retry, the retry hits the existing `machine is None` path and the task is abandoned — same as today.
- No explicit backoff between retries — the producer-consumer loop cadence is the natural delay.
- No new dependencies.

## Decisions

### Decision 1: Classify errors in the gateway, return structured split

`download_outputs` returns `(meta_add, transient_errors, permanent_errors)` where `transient_errors` and `permanent_errors` are `list[tuple[str | None, Exception]]` (same shape as today's `sftp_errors`, but split).

Classification rule per caught exception in the per-file loop:
- If `isinstance(err, SFTPRetryExc)` → append to `transient_errors`.
- Else → append to `permanent_errors`.

**Why not keep a flat list and let the use case classify:** the `use-cases` spec forbids `consume_task` from importing `SFTPRetryExc`/`SFTPError`. Pushing classification to the gateway keeps the use case free of adapter types and preserves the layering contract.

**Alternative considered:** returning a single list of `(file, err, is_transient)` tuples. Rejected — the use case's branching reads more clearly against two lists (`if permanent_errors` / `if transient_errors`) and avoids per-entry boolean plumbing.

### Decision 2: `OSError` local-vs-remote disambiguation

`OSError` is ambiguous: it appears as a remote transport error (in `SSHRetryExc`, transient) and as a local write error from `sftp.get(..., local_dir)` writing to the local filesystem (disk full, local permissions — permanent).

Mechanism: catch local-write `OSError` separately. `asyncssh`'s `sftp.get` downloads to `local_dir`; a local `OSError` raised by the local file write is distinguishable from an SFTP-transport `OSError` by inspecting whether it wraps an SFTP cause. Practically, the gateway wraps the `sftp.get` call and classifies `OSError` as permanent (local disk failures are the common case for `OSError` at the `local_dir` write site); remote transport `OSError` surfaces as `SFTPConnectionLost`/`SFTPFailure` (which are already in `SFTPRetryExc`) rather than bare `OSError` from the SFTP layer. The classifier therefore treats bare `OSError` (not in `SFTPRetryExc`) as permanent. This matches existing per-file `except (OSError, SFTPError)` semantics where `OSError` was already not retried by `file_get_retry` (which only retries `SFTPRetryExc`).

**Why not a more sophisticated cause-walk:** adds complexity for a rare case. The existing retry decorator already treats bare `OSError` as non-retryable in the SFTP context (`my_backoff_sftp` retries only `SFTPRetryExc`); preserving that behaviour is consistent and minimal.

### Decision 3: rmtree gating

`rmtree` runs inside `_session()` only when there are no transient errors — i.e. when the session is going to finalise (success or permanent-only). Concretely: after the per-file loop, `if not transient_errors: await sftp.rmtree(path_type(remote_dir))`.

The whole-session catch-all (today's `except Exception` around `job_retry(_session)()`) stays: if the session itself blows up (connection lost before the guard), `rmtree` did not run, the remote dir is preserved, and the error is recorded as transient (session-level failure). The task stays `RUNNING` for retry.

**Why not gate `rmtree` outside `_session` (in the use case):** the use case must not import SFTP types or call `sftp.rmtree` (layering). The gateway owns the SFTP session; the gate belongs inside it.

### Decision 4: `consume_task` returns `bool`

Signature: `async def consume_task(...) -> bool`. `True` = finalised (task is now DONE, rmtree ran, tracker slot discarded). `False` = stay `RUNNING` for retry (no rmtree, tracker slot NOT discarded — the slot stays so the allocator does not re-select the same task id via cloud-fallback; see Decision 6).

Branching in `_finalize_task` (renamed conceptually to "decide finalisation"):
- `permanent_errors` non-empty OR `transient_errors` empty → finalise. On permanent: continue downloading remaining files first (the loop already does this — it does not break on permanent), then `task.fail(error_msg)`, record `TaskFailed`, return `True`. On no errors: `task.complete()`, record `TaskCompleted`, return `True`.
- `transient_errors` non-empty AND `permanent_errors` empty → not finalised. No status change, no save, no event, return `False`. (The task remains `RUNNING` in DB from the prior cycle; nothing to persist.)

**Why `bool` and not an enum (`RETRY`/`DONE`):** two states only; an enum is over-engineering for a single caller that already has the `if`/`else` shape.

### Decision 5: Orchestrator conditional `_occupancy_started` discard

`_task_consumer_consumer` currently does `await consume_task(...)` then unconditionally `self._occupancy_started.discard(ip)`. Change to:

```
finalised = await consume_task(...)
if finalised:
    self._occupancy_started.discard(ip)
```

If not finalised, the next producer cycle re-yields the `RUNNING` task, the consumer re-enters the consume block (because `ip in self._occupancy_started` still holds), and `consume_task` retries.

### Decision 6: In-flight consume guard

Problem: between worker A dequeuing task 42 and starting `consume_task`, the next producer cycle can re-yield task 42 (still `RUNNING`) to worker B → two concurrent downloads from the same remote dir.

Mechanism: an in-process `set[int]` (`self._consuming: set[int]`) on the orchestrator. The producer skips yielding a task whose id is in `self._consuming`. The consumer adds `task_id` to the set before awaiting `consume_task` and removes it after (in a `finally`). Since both run in the same event loop, the set check/add/remove are atomic (no `await` between check and add).

```
# producer
for task in tasks:
    if task.task_id in self._consuming:
        continue
    yield UMessage(task.task_id, task)

# consumer
self._consuming.add(task_id)
try:
    finalised = await consume_task(...)
    if finalised:
        self._occupancy_started.discard(ip)
finally:
    self._consuming.discard(task_id)
```

**Alternative considered — `UniqueQueue` hold-until-`item_done`:** would require changing the queue semantics and the producer-consumer wrapper. The `set[int]` is localised, minimal, and sufficient given the single-event-loop model.

**Caveat:** the guard is best-effort against same-loop double-consume. It does not survive cross-process deployments (not applicable here — single daemon). It does not protect against a task being re-yielded after a daemon restart (acceptable — restart resets in-flight state, and a transient error will simply retry).

### Decision 7: No retry cap (deferred / optional)

No cap is implemented in this change. Transient errors are expected to self-resolve (network blips, connection drops that `my_backoff_sftp` already retries within the session). Permanent errors stop immediately. If a transient error never resolves (e.g. a persistent `SFTPFailure` due to remote file permissions), the task loops in `RUNNING` indefinitely — visible in `yastatus` and daemon logs as repeated consume attempts.

**Why no cap now:** the user explicitly deferred it. An in-memory counter (not persisted, resets on daemon restart) can be added later if ops observe runaway loops. Adding it now without evidence of the problem is YAGNI.

## Risks / Trade-offs

- **[Transient never resolves → infinite RUNNING loop]** → Mitigation: visible in `yastatus` (task stays RUNNING) and daemon logs (repeated consume warnings). Ops can manually fail the task or fix the remote. An in-memory cap can be added later without schema change. Accepted.

- **[Cloud node reaped during retry → outputs lost with the VM]** → Mitigation: none — same as today's behaviour for any RUNNING task on a reaped node. The retry path does not make this worse. The task hits the existing `machine is None` → `TaskAbandoned` path after `broken_tasks_passes=20` cycles. Accepted.

- **[Node stays occupied during retry → reduced allocator capacity]** → Mitigation: `_find_free_machines` already excludes `RUNNING`-task IPs; this is correct behaviour (the node holds undownloaded outputs). Retry cadence is bounded by the consume loop interval. Accepted.

- **[BREAKING: `download_outputs` return shape change]** → Mitigation: `MachineGateway` is a runtime-checkable Protocol; in-tree only `SSHMachineGateway` implements it. External implementers (if any) must update. The change is detectable by static type checkers.

- **[BREAKING: `consume_task` signature None→bool]** → Mitigation: `consume_task` is an internal use case, not part of the public `Yascheduler` API. Only `orchestrator._task_consumer_consumer` calls it. Single call site to update.

- **[Concurrent consume race after daemon restart]** → Mitigation: in-flight guard is in-memory and resets on restart. A task that was mid-consume when the daemon died will simply be re-consumed on the next cycle — idempotent (re-downloading overwrites locally, remote is untouched since rmtree did not run). Accepted.

## Migration Plan

No DB migration. No config change. Deployment is a code update:

1. Update `gateway.download_outputs` return shape + classification + rmtree guard.
2. Update `domain/ports.py` `MachineGateway.download_outputs` Protocol signature.
3. Update `consume_task` branching + `-> bool`.
4. Update `orchestrator._task_consumer_consumer` conditional discard + in-flight guard.
5. Update unit and e2e tests.

Rollback: revert the code; no data to migrate back. Tasks that were left `RUNNING` for retry under the new code will be consumed once (finalised or failed) under the old code on the next cycle — no orphaned state.

## Open Questions

- In-memory retry cap value (only if/when implemented — not in this change).
- Whether `OSError` classification by bare-type (permanent) is sufficient in the field, or whether a cause-walk is needed after observing real failures. Deferred to post-deployment ops feedback.
# Explore Brief: fix-download-rmtree-data-loss

## Problem

`SSHMachineGateway.download_outputs` (gateway.py:684) calls `await sftp.rmtree(path_type(remote_dir))` unconditionally after the per-file download loop, even when `sftp_errors` is non-empty (partial download failure). Combined with `task.fail()` transitioning to terminal `DONE` and the orchestrator's `_task_consumer_producer` selecting only `RUNNING` tasks, partially-downloaded remote outputs are destroyed irrecoverably and the task cannot be retried. Data loss.

## Alternatives Rejected

- **E — No rmtree at all, cleanup by node lifecycle.** Rejected: persistent (static) nodes in `yascheduler_nodes` accumulate orphaned remote dirs; no cleanup owner exists.
- **D — New `DOWNLOAD_FAILED` TaskStatus + DB migration.** Rejected: over-engineering. Retry can stay in `RUNNING` (which the producer already selects) without schema changes.
- **In-`context.extra` retry counter.** Rejected by user: no DB writes per attempt. If a cap is wanted, an in-memory counter suffices (does not survive daemon restart; acceptable since transient errors are self-resolving and permanent errors stop immediately).

## Final Approach

Classify per-file SFTP errors at the gateway (the only layer that may import `SFTPRetryExc`/`SFTPError` — `use-cases` spec forbids these imports in `consume_task`). `download_outputs` returns a structured split: `(meta_add, transient_errors, permanent_errors)`.

`consume_task` branches:
- **no errors** → `task.complete()`, rmtree ran, return `True` (finalised).
- **any permanent** → loop continues downloading remaining available files, then `task.fail(error_msg)`, rmtree ran, return `True`.
- **transient-only** → stay `RUNNING`, no rmtree, return `False` (retry next cycle).

Orchestrator discards `ip` from `_occupancy_started` only when `consume_task` returns `True`. On `False`, the next producer cycle re-yields the `RUNNING` task for retry. Cadence of the producer-consumer loop is the natural retry delay (no explicit backoff).

Cloud node deallocation is NOT blocked by an in-flight retry (acceptable: if the VM is reaped, the retry hits the `machine is None` path and the task is abandoned, same as today).

## Error Classification Mapping

| Class | Members | Source |
|-------|---------|--------|
| TRANSIENT (retry) | `asyncio.TimeoutError`, `SFTPEOFError`, `SFTPFailure`, `SFTPBadMessage`, `SFTPNoConnection`, `SFTPConnectionLost`, `SFTPInvalidHandle`, `SFTPLockConflict`, `SFTPByteRangeLockConflict`, `SFTPByteRangeLockRefused`, `SFTPDeletePending`, `SFTPNoMatchingByteRangeLock` | `SFTPRetryExc` tuple (`infra/ssh/platform/protocol.py:71`) |
| PERMANENT (DONE+error+rmtree) | `SFTPNoSuchFile` (missing output — engine failed, not transport), `SFTPPermissionDenied`, any `SFTPError` not in `SFTPRetryExc`, local `OSError` (disk full, local perms) | complement |

Nuance to resolve in design: `OSError` appears in BOTH `SFTPRetryExc`-adjacent (`SSHRetryExc` includes `OSError` for remote transport) and as a local-disk error. Local `OSError` from `sftp.get(..., local_dir)` writing to disk is permanent; remote `OSError` is transient. Classification must distinguish by error context, not bare type — design.md to specify the mechanism (likely: catch local-write `OSError` separately from SFTP-transport `OSError`).

## Cross-Module Data Flow

```
gateway.download_outputs(ip, remote_dir, local_dir, files, task_id)
    -> (meta_add, transient_errors, permanent_errors)
        │
        ▼
consume_task(task_id, ip, gateway, engines, uow_factory, local_tasks_dir, tracker)
    branch on (transient, permanent):
        empty           -> task.complete() + with_event(TaskCompleted); rmtree ran; tracker.discard; return True
        any permanent   -> task.fail(error_msg) + with_event(TaskFailed); rmtree ran; tracker.discard; return True
        transient-only  -> no status change, no rmtree, no tracker.discard; return False
        │
        ▼ returns bool finalised
orchestrator._task_consumer_consumer
    await consume_task(...)
    if finalised: self._occupancy_started.discard(ip)
    # next producer cycle re-yields RUNNING tasks (natural retry)
```

In-flight consume guard (Q10) — mechanism to prevent two workers consuming the same task in overlapping producer cycles. Candidate: `set[int]` in orchestrator checked in producer; or `UniqueQueue` hold-until-`item_done`. Detail → design.md.

## Locked Decisions

- rmtree only on finalisation (success | permanent).
- Transient-only → stay RUNNING, no rmtree, retry next cycle.
- Any permanent → loop continues downloading remaining available files, then DONE+error+rmtree.
- Classification lives in gateway (owns SFTP types; consume_task forbidden to import them).
- `download_outputs` returns structured `(meta_add, transient_errors, permanent_errors)`.
- `consume_task -> bool`: True=finalised, False=retry.
- Orchestrator discards `_occupancy_started[ip]` iff finalised.
- Cadence of producer-consumer loop = natural retry delay. No explicit backoff.
- Cloud-dealloc NOT blocked by retry (acceptable).
- Node stays occupied until retry completes (acceptable).
- NO new TaskStatus, NO DB migration, NO context.extra writes.
- Optional in-memory retry cap — design decision (deferred).

## Open Questions for Design

1. In-flight consume guard mechanism (set vs UniqueQueue hold semantics).
2. `OSError` local-vs-remote disambiguation in classification.
3. Optional in-memory retry cap (yes/no, value if yes).
4. Exact return-shape naming (e.g. named tuple vs plain tuple) — affects `domain/ports.py` Protocol signature and `MachineGateway` typing.
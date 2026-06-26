## Why

`SSHMachineGateway.download_outputs` removes the remote directory unconditionally after the per-file download loop, even when some files failed to transfer (`sftp_errors` non-empty). Combined with `task.fail()` transitioning the task to terminal `DONE` and the orchestrator only re-consuming `RUNNING` tasks, partially-downloaded outputs are destroyed irrecoverably and the task cannot be retried. This is silent data loss on any transient SFTP failure.

## What Changes

- **Classify SFTP errors in the gateway** as transient (retryable transport failure) vs permanent (missing file, local disk error, permission denied). The gateway is the only layer permitted to import `SFTPRetryExc`/`SFTPError` — the `use-cases` spec forbids those imports in `consume_task`.
- **`download_outputs` returns a structured error split** — `(meta_add, transient_errors, permanent_errors)` instead of a flat `sftp_errors` list, so the use case can branch without inspecting SFTP types. **BREAKING** to `MachineGateway` Protocol implementers: return shape changes from 2-tuple to 3-tuple.
- **`consume_task` retries transient-only failures** by leaving the task in `RUNNING`, skipping `rmtree`, and returning `False` so the orchestrator re-consumes it on the next producer cycle (cadence = natural delay).
- **`consume_task` finalises on success or any permanent error** — on permanent, it continues downloading the remaining available files, then transitions to `DONE` with `task.fail()`, runs `rmtree`, and returns `True`. **BREAKING** to `consume_task` callers: signature changes from `-> None` to `-> bool`.
- **Orchestrator discards `_occupancy_started[ip]` only when `consume_task` returns `True`** (finalised), keeping the ip registered for retry otherwise.
- **`rmtree` is gated on finalisation** — it no longer runs when transient errors left files undownloaded.
- **In-flight consume guard** in the orchestrator to prevent two workers from concurrently consuming the same `RUNNING` task across overlapping producer cycles.

### Design TBD

The following are design-level decisions deferred to `design.md`:
- In-flight consume guard mechanism (in-process `set[int]` vs `UniqueQueue` hold-until-`item_done` semantics).
- `OSError` local-vs-remote disambiguation in the classification — local `OSError` (disk full, local perms) is permanent; remote transport `OSError` is transient. The classifier must distinguish by error context, not bare type.
- Optional in-memory retry cap (yes/no; value if yes). Does not survive daemon restart; acceptable since transient errors are self-resolving and permanent errors stop immediately.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `ssh-gateway`: `download_outputs` return shape changes from flat `sftp_errors` to structured `(meta_add, transient_errors, permanent_errors)`; `rmtree` becomes conditional on finalisation, not unconditional.
- `use-cases`: `consume_task` signature changes to `-> bool`; branching on transient vs permanent errors; retry semantics for transient-only failures.
- `domain-ports`: `MachineGateway.download_outputs` Protocol signature changes to the structured return shape.
- `orchestrator`: `_task_consumer_consumer` discards `_occupancy_started[ip]` only when `consume_task` returns `True`; in-flight consume guard prevents concurrent consume of the same `RUNNING` task.

## Impact

- **Code**: `yascheduler/infra/ssh/gateway.py` (classification + return shape), `yascheduler/application/consume_task.py` (branching + `-> bool`), `yascheduler/application/orchestrator.py` (consume guard + conditional `_occupancy_started` discard), `yascheduler/domain/ports.py` (Protocol signature).
- **No DB schema change**: tasks stay `RUNNING` during retry — no new `TaskStatus`, no migration.
- **No config change**: retry cadence is the existing producer-consumer loop interval.
- **Public API**: `MachineGateway.download_outputs` Protocol return type changes (affects any external Protocol implementer; in-tree only `SSHMachineGateway` implements it). `consume_task` return type changes (internal use-case, not part of public `Yascheduler` API).
- **Tests**: unit tests for `consume_task` three branches (success / permanent / transient-only); e2e for retry-then-success and permanent→DONE+error flows.
- **Accepted trade-offs**: (a) a cloud node may be deallocated while a task is in retry (`RUNNING`), causing the retry to hit the `machine is None` path and abandon the task — same as today's behaviour, accepted; (b) the node stays occupied until retry completes (the allocator's `_find_free_machines` excludes `RUNNING`-task IPs), accepted.
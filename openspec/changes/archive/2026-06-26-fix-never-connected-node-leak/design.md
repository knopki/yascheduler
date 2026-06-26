## Context

`CloudProvisionerImpl.allocate` (`infra/cloud/manager.py:149`) provisions a VM
and returns a `Node`; the caller `_persist_node_with_cleanup`
(`application/allocate_task.py:348`) writes `yascheduler_nodes` with
`enabled=True` and returns. From this point the orchestrator owns connecting
the node over SSH.

The connect loop (`application/orchestrator.py:219-257`) is a
producer-consumer pair:

- `_connect_machine_producer` (every `_sleep_interval` seconds) reads
  `uow.nodes.list_enabled()` and yields nodes whose IP is not already in
  `gateway` — so a never-connected node is re-yielded on every cycle.
- `_connect_machine_consumer` calls `gateway.connect(...)` and, on
  `MachineConnectionError`, logs the error and returns. There is no per-IP
  failure counter, no deadline, and no `tracker.discard`.

Three compounding effects produce a permanent leak:

1. **VM leak + stale DB row.** `_deallocator_producer`
   (`orchestrator.py:381-402`) builds `idle_machines` exclusively from
   `gateway.list_connected()`. A never-connected IP is structurally invisible
   to the deallocator, so `deallocate_nodes` never disables it and the VM
   bills until manual intervention.
2. **Task stuck in TO_DO.** On the cloud-allocate success path
   (`allocate_task.py:526`), `cloud_allocated = True` is set and the
   `finally` block (`:528-534`) preserves the `AllocationTracker` entry.
   `AllocationTracker.discard` is only called from `consume_task` (success or
   fail), the `TaskAbandoned` path in `_task_consumer_consumer`, or the
   cloud-fallback failure branch — never from the connect loop. On the next
   allocate cycle, `tracker.add(task_id)` returns `False` (`:492`) and the
   task silently returns without re-allocating.
3. **Infinite retry without backoff.** The producer re-yields the node every
   cycle; the consumer logs and swallows. No exhaustion point exists.

The defect window is narrow (the VM was SSH-reachable during
`CloudProvisionerImpl._setup_vm` moments earlier) but real: SSH service
crash, jump-host routing change, keypair rotation, or cloud-init finishing
post-setup and breaking the env all land in it. E2E tests with happy SSH do
not exercise it.

## Goals / Non-Goals

**Goals:**
- Bound the time a never-connected cloud node can bill: after `connect_grace`
  seconds of consecutive connection failures for an IP, the VM is deleted,
  the DB row is removed, and the originating task is released from
  `AllocationTracker` dedup so it re-allocates on the next cycle.
- Keep the fix local: no DB schema change, no new repository method, no new
  domain event, no INI parsing.
- Mirror the existing `TaskAbandoned` flow (`orchestrator.py:320-340`) so the
  new cleanup path is architecturally symmetric with the existing
  "lost-BUSY-machine" handling.

**Non-Goals:**
- Limiting the number of times a task re-allocates after repeated abandon
  cycles. A task whose cloud nodes keep failing to connect will re-allocate
  indefinitely. This matches existing cloud-fallback behavior (no retry cap)
  and is accepted here; a future change could add a per-task failure counter
  that transitions to a FAILED terminal state.
- Persisting the connect-failure timer across daemon restarts. The
  `dict[str, float]` is in-memory; a restart resets the grace window. See
  Risks.
- Wiring `connect_grace` to INI configuration. DTO defaults are the sole
  source in this change; a later change can add an INI override following the
  `idle_tolerance` precedent.
- Changing `CloudProvisionerImpl.allocate` / `_setup_vm` — the SSH setup
  contract inside `allocate` stays as-is.
- Touching the `fix-disconnect-bg-task-leak` change's scope
  (`SSHMachineGateway._bg_tasks`). The two changes are disjoint (gateway vs
  orchestrator + new use case) and can land independently.

## Decisions

### Decision 1: Bound the leak in the connect loop, not the deallocator

**Choice**: implement the deadline in `_connect_machine_consumer` and call a
new `abandon_node` use case when the deadline is exceeded.

**Alternatives considered**:

- **A. Extend `_deallocator_producer` to sweep enabled nodes not in
  `gateway.list_connected()`.** Rejected: without a timestamp on `Node`
  (schema has no `created_at`) there is no way to distinguish a
  never-connected node from a transiently-disconnected one. An unconditional
  sweep would kill any cloud node that briefly dropped its SSH session,
  including ones mid-task. Adding a DB column pulls in the `schema-migrations`
  change and violates the "no schema change" goal.
- **B. Roll back the persist inside `allocate_task` if the node never
  connects.** Rejected: `allocate_task` and the connect loop are separate
  producer-consumer pairs that communicate only via DB + gateway. Adding a
  cross-channel ack (event/awaitable) breaks the "allocate persists, connect
  reconciles" architecture and lengthens the `allocation_lock` critical
  section to connect-timeout × retries. Surface area too large for the bug.
- **C. Add a TTL inside `AllocationTracker`.** Rejected alone: discarding
  the tracker entry without deleting the VM creates a **worse** leak — the
  task re-allocates and provisions a second VM while the first still bills.
  A TTL is only safe paired with a reaper, which collapses back into
  Decision 1's shape with extra moving parts.

**Rationale**: the connect loop is the single point that already owns the
failure signal (`MachineConnectionError`) and the IP namespace. Co-locating
the deadline there avoids cross-loop coordination and reuses the existing
producer re-yield as the retry tick.

### Decision 2: Track `first_seen` as a monotonic float, not an attempt counter

**Choice**: `_connect_failures: dict[str, float]` mapping IP →
`time.monotonic()` at first failure; `age = time.monotonic() - first_seen`.

**Rationale**: the producer re-yields on every `_sleep_interval` cycle (min
`engine.sleep_interval`, default 10s), but `_connect_impl` runs its own
`@my_backoff_exc()` retries inside a single `connect()` call (which itself
has `connect_timeout=10`). An attempt counter would couple the deadline to
cycle frequency and backoff internals; a monotonic timestamp is wall-clock-
independent (consistent with how `free_since` and `idle_tolerance` already
interact — see `deallocate_nodes.py:17` CHANGE_SUMMARY noting the
monotonic-vs-wall-clock fix) and gives a deterministic grace window
regardless of how many producer cycles or inner backoff retries fire.

### Decision 3: `connect_grace` lives on `CloudConfig` with DTO defaults

**Choice**: add `connect_grace: int` to the `CloudConfig` Protocol
(`domain/ports.py:100-117`); each `ConfigCloud*` DTO declares a default.

| DTO                    | Default | Rationale                                          |
| ---------------------- | ------- | -------------------------------------------------- |
| `ConfigCloudHetzner`   | 60      | Fast cloud-init, small VMs; ~3 connect cycles      |
| `ConfigCloudUpcloud`   | 60      | Fast cloud-init                                    |
| `ConfigCloudAzure`     | 120     | Slow cloud-init, larger VMs                        |
| `ConfigCloudVastAI`    | 120     | Marketplace VMs, unpredictable boot times          |

The values are derived from `connect_timeout=10` × ~3-5 inner backoff
attempts ≈ 30-50s per consumer attempt, plus one extra cycle of slack.
60s = "well beyond normal connect"; 120s for clouds with known-slow boot.

**Alternatives considered**:

- **Global `LocalSettings.connect_grace`.** Rejected: cloud providers differ
  materially in boot time; a global value would either be too aggressive for
  Azure/VastAI or too lax for Hetzner. The `idle_tolerance` precedent is
  per-cloud.
- **Per-node persistence in DB.** Rejected: requires a new column + migration,
  out of scope.

**INI parsing**: explicitly deferred. `config_parser.py` is not modified; the
DTO defaults are the only source. A follow-up change can add an INI key
following the `idle_tolerance` parsing pattern (`config_parser.py:318` etc.)
without breaking this change's contract.

### Decision 4: `abandon_node` is a new use case, not a `deallocate_node` extension

**Choice**: new `application/abandon_node.py` with signature
`abandon_node(node, gateway, clouds, uow_factory, tracker) -> None`.

**Rationale**: `deallocate_node` (`application/deallocate_nodes.py:50`)
presupposes the node is in `gateway` (it calls `gateway.contains(ip)` →
`gateway.disconnect(ip)`). A never-connected node is **not** in the gateway,
so the disconnect branch is dead code for this case. Extending
`deallocate_node` with a "force even if not in gateway" flag would complicate
its contract and conflate two cleanup paths (idle-connected vs
never-connected). A separate use case keeps each path's contract clean and
makes the orchestrator's intent explicit at the call site.

The new use case reuses `CloudProvisioner.deallocate` + `NodeRepository.remove`
directly — no new repository method. The stuck-task lookup uses
`uow.tasks.list_by_status({TaskStatus.TO_DO})` + an in-memory
`allocated_ip == ip` filter. The TO_DO pool is normally small; an O(N) scan
per abandon is acceptable and avoids widening `TaskRepository`'s port surface.

### Decision 5: Stuck-task re-allocation is unlimited

**Choice**: `abandon_node` calls `tracker.discard(task_id)` and does not mark
the task FAILED. The task re-enters `allocate_task` on the next cycle.

**Rationale**: matches existing cloud-fallback behavior (no retry cap on
`allocate_task`). Adding a failure counter is a behavior change in its own
right (new terminal state transition, event semantics, CLI surface for
"permanently failed") and is explicitly out of scope. If a task loops
forever on a broken cloud, the operator-level signal is the same as today:
repeated `[CloudProvisionerImpl][allocate][DONE]` + `[CONNECT_ABANDON]` log
lines.

## Risks / Trade-offs

- **In-memory `_connect_failures` lost on daemon restart** → a never-connected
  node gets a fresh `connect_grace` window after restart. Mitigation: daemon
  restarts are rare and the extra 60-120s of billing is bounded; persisting
  the timer would require a DB column (out of scope). Accepted.
- **Race: abandon mid-flight vs shutdown cancellation** → if the daemon is
  stopped between `clouds.deallocate` and `uow.nodes.remove`, the VM is
  deleted but the DB row remains enabled (stale orphan). Mitigation: same
  posture as existing `deallocate_node` (`deallocate_nodes.py:89-106`), which
  logs "manual reconciliation needed" for the symmetric failure and relies on
  operator reconciliation. `abandon_node` logs identically on
  `nodes.remove` failure; no `asyncio.shield` is added to keep the change
  small.
- **Race: abandon vs concurrent `_deallocator_producer`** → analyzed and
  confirmed non-conflicting. The deallocator only disables nodes present in
  `idle_machines` (derived from `gateway.list_connected()`); a never-connected
  IP is never in that set. If `deallocate_nodes` reads `list_enabled()`
  before `abandon_node` commits the `remove`, the node is visible but skipped
  by the `ip in idle_machines` filter (`deallocate_nodes.py:140`). If it
  reads after, the node is gone. No double-delete path exists.
- **Race: abandon vs `allocate_task` re-allocation of the same task** →
  `tracker.discard(task_id)` releases dedup; the next allocate cycle may
  provision a new VM on the same provider. If the old VM's DB row hasn't been
  removed yet, `_count_nodes_by_cloud` may temporarily see capacity as
  exhausted and `select_provider` returns `None` → `NO_PROVIDER` → retry next
  cycle. This is a one-cycle delay, not a leak. Accepted.
- **`CloudConfig` Protocol surface widens from 6 fields to 7** → existing
  structural implementers (none outside the four in-tree DTOs) would lose
  `isinstance` parity. Mitigation: the Protocol stays `@runtime_checkable`
  and structural (PEP 544); the four DTOs are updated in this change. The
  `cloud-config-protocol` spec delta records the new field.
- **`connect_grace` defaults could be wrong for an unusual deployment** →
  without INI override, operators cannot tune per-deployment. Mitigation: a
  follow-up change can wire the INI key; the DTO defaults are conservative
  (≥ 60s) and derived from measured `connect_timeout` × backoff.

## Migration Plan

No data migration. Deployment is a code rollout:

1. Merge the change; the four DTOs now declare `connect_grace`; the
   orchestrator starts tracking `_connect_failures`.
2. Existing never-connected leaks from prior runs are **not** auto-cleaned by
   this change on first start (the orchestrator has no `first_seen` for IPs
   that were already failing before the new code loaded — the first failure
   under the new code starts the timer). Operators with pre-existing leaked
   VMs should run `yanodes` / manual cleanup once. New leaks are bounded.
3. Rollback: revert the commit; `_connect_failures` disappears; old behavior
   (unbounded retry) resumes. No DB residue.

## Open Questions

- Should `abandon_node` emit a structured log event beyond the
  `[Orchestrator][_connect_machine_consumer][CONNECT_ABANDON]` line, for
  observability dashboards? Tentative: no new domain event (Non-Goal), but
  the log line includes `ip`, `cloud`, `age`, `grace`, and `task_id` for
  correlation.
- Whether to later add an INI override for `connect_grace` — deferred to a
  follow-up; the DTO defaults are the contract for this change.
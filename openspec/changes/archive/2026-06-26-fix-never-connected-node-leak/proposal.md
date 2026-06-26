## Why

A cloud node that is provisioned and persisted (`enabled=True`) but then fails
to establish its SSH connection leaks forever: the VM keeps billing, the
`yascheduler_nodes` row stays enabled, and the originating task is permanently
stuck in `TO_DO`. The connect loop swallows `MachineConnectionError` with a log
line and no deadline; the deallocator only ever sees `gateway.list_connected()`,
so a never-connected node is invisible to it; and `AllocationTracker` keeps the
`task_id` pinned on the cloud-allocate success path, so the next allocate cycle
hits dedup and returns. All three symptoms persist until the daemon is
reconfigured by hand.

## What Changes

- Add a per-IP connect-failure deadline in the orchestrator's
  `_connect_machine_consumer`: track `first_seen` (monotonic) per IP on
  `MachineConnectionError`; on each failure compare elapsed age against the
  node's cloud `connect_grace`; on success pop the entry.
- Once `connect_grace` is exhausted for an IP, the orchestrator calls a new
  `abandon_node` use case that performs: best-effort `clouds.deallocate(cloud,
  ip)`, `uow.nodes.remove(ip) + commit`, then locates the originating TO_DO
  task by `allocated_ip == ip` (via existing `uow.tasks.list_by_status({TO_DO})`
  + in-memory filter — no new repository method) and calls
  `tracker.discard(task_id)` so the task re-enters allocation on the next
  cycle.
- Extend the `CloudConfig` Protocol in `yascheduler/domain/ports.py` with a
  `connect_grace: int` field; the four `ConfigCloud*` DTOs in
  `infra/cloud/cloud_configs.py` declare per-provider defaults (Hetzner/Upcloud
  = 60s, Azure/VastAI = 120s). INI parsing is **not** added in this change —
  DTO defaults are the sole source; a later change can wire an INI override.
- No DB schema change, no new repository method, no new domain event. The
  `abandon_node` use case is application-layer only and reuses
  `CloudProvisioner.deallocate` + `NodeRepository.remove` + in-memory task
  lookup. Stuck-task re-allocation is unlimited (no retry counter) — a task
  whose cloud node keeps failing to connect will re-allocate on each subsequent
  cycle, mirroring existing cloud-fallback behavior.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `orchestrator`: extend the "Connect machine loop" requirement so that
  repeated `MachineConnectionError` for the same IP past `connect_grace`
  triggers `abandon_node` cleanup instead of indefinite retry. Adds scenarios
  for the grace timer, the abandon trigger, and the success-path reset.
- `use-cases`: add a new "AbandonNode use case" requirement covering
  `abandon_node(node, gateway, clouds, uow_factory, tracker)` — VM delete +
  DB-row remove + tracker discard for the stuck TO_DO task. Adds scenarios for
  the happy path, the no-task case, and best-effort cloud-delete failure.
- `cloud-config-protocol`: extend the `CloudConfig` Protocol surface from 6
  fields to 7 by adding `connect_grace: int`; the four DTOs declare per-provider
  defaults. Adds scenarios for the new field's presence on the Protocol and on
  each DTO.

## Impact

- **Code**:
  - `yascheduler/domain/ports.py` — `CloudConfig` gains `connect_grace: int`
    (Protocol surface widening; all four DTOs already satisfy it after they
    declare the field).
  - `yascheduler/infra/cloud/cloud_configs.py` — `ConfigCloudHetzner`,
    `ConfigCloudUpcloud`, `ConfigCloudAzure`, `ConfigCloudVastAI` each gain a
    `connect_grace: int = <default>` field.
  - `yascheduler/application/abandon_node.py` — **new** use case module
    (`abandon_node` async function + MODULE_CONTRACT/MAP/CHANGE_SUMMARY per
    GRACE-lite).
  - `yascheduler/application/orchestrator.py` — `_connect_failures:
    dict[str, float]` field on `Orchestrator`; `_connect_machine_consumer`
    gains the grace-timer + abandon dispatch on the `MachineConnectionError`
    branch; successful connect pops the entry.
  - `yascheduler/application/__init__.py` — re-export `abandon_node`.
- **Public surface**: `CloudConfig` Protocol gains a field — DTO implementers
  must declare it (the four in-tree DTOs do; out-of-tree structural
  implementers are unaffected because the Protocol stays structural per PEP
  544, but they would lose `isinstance` parity if they relied on inheritance).
  No CLI, INI, DB-schema, or AiiDA-plugin change.
- **Dependencies / schema**: none. No migration, no new dependency.
- **Callers**: `_connect_machine_consumer` is the only caller of
  `abandon_node`. `deallocate_node` / `deallocate_nodes` are untouched.
- **Tests**: unit tests for the grace timer (success resets, age < grace
  retries, age >= grace abandons) and for `abandon_node` (happy path, no
  matching task, cloud-delete failure is logged not raised); integration test
  covering allocate → connect-fail → abandon → re-allocate-succeeds against
  real PostgreSQL + SSH testcontainers per `e2e-testing`.
- **GRACE-lite**: new `M-APPLICATION-ABANDON-NODE` module record in
  `docs/knowledge-graph.xml`; `M-APPLICATION-ORCHESTRATOR` annotations updated
  for the new `_connect_failures` field and the abandon dispatch;
  `CrossLink M-APPLICATION-ORCHESTRATOR -> M-APPLICATION-ABANDON-NODE
  relation="delegates never-connected cleanup"`. `M-DOMAIN-PORTS` annotations
  gain `connect_grace` on `CloudConfig`.
- **Out of scope**: the `fix-disconnect-bg-task-leak` change targets a
  different defect (`disconnect(ip)` cross-cancelling other machines' occupancy
  monitors on already-connected nodes). The two changes touch disjoint code
  regions (`gateway.py` vs `orchestrator.py` / new `abandon_node.py`) and do
  not conflict.
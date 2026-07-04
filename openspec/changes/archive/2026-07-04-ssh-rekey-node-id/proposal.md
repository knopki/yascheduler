## Why

The `Node.ip → Node.node_id` migration arc has reached its payoff surface. Prior
archived changes established `NodeId` as the strictly-unique identity (migration
003 dropped `ip UNIQUE`), rekeyed node mutators to `node_id`, and rekeyed the
deallocate queue. The uncommitted `task-allocated-node-id` change added the
`allocated_node_id` FK and write path. The remaining ip-as-identity surface is
`SSHMachineRepository._sessions` (keyed by ip) plus the nine read sites that
resolve a session or node via `task.allocated_ip` / `node.ip`. Until these flip,
duplicate IPs behind different jump hosts still collapse in session matching
(`_find_free_machines` builds `nodes_by_ip = {n.ip: n}` — last wins) and the
scheduler cannot distinguish two nodes sharing one IP. This change closes the
arc: `MachineRepository` becomes `node_id`-keyed, the read path flips to
`allocated_node_id`, and the dup-IP disambiguation actually lands.

## What Changes

- **BREAKING** `MachineRepository` port rekeys from ip to node_id:
  `connect(ip, …) → connect(node: Node, …)`, `disconnect(ip) → disconnect(node_id)`,
  `get_session(ip) → get_session(node_id)`, `contains(ip) → contains(node_id)`,
  `__contains__(ip) → __contains__(node_id)`. `ip` survives only as the
  transport address read from `node.ip` inside `connect`, not as a key or
  positional param.
- **BREAKING** `CloudProvisioner.allocate(provider) → NewNode` becomes
  `allocate(provider, tmp_node_id: NodeId) → Node`. The tmp-node row inserted by
  `_select_and_insert_tmp` (node_id=T) is reused as the real node's identity:
  the cloud setup session registers under T, and `_persist` becomes a single
  `update(node)` (enabled=TRUE, ip, ncpus) instead of insert+remove. Fixes the
  latent two-rows-per-lifecycle bug (tmp-node T and real-node R were distinct
  rows with distinct node_ids).
- **BREAKING** `ConnectedMachine` (domain model) gains `node_id: NodeId` as its
  first field. The positional constructor shifts (`ConnectedMachine(node_id, ip,
  platform, …)`), so any caller constructing it positionally breaks. Internal-only
  — no public API constructs `ConnectedMachine` — but flagged BREAKING for
  contract honesty. `MachineSession` Protocol stays clean (no node_id) — read
  via `session.machine.node_id`. `occupy`/`release`/`replace()` carry `node_id`
  automatically (frozen dataclass).
- Nine read sites flip from `allocated_ip` to `allocated_node_id`:
  orchestrator (`_task_consumer_consumer` get_session + `_occupancy_started`,
  `_start_task_on_machine` node lookup, `_deallocator_producer` idle_machines),
  `deallocate_nodes` (busy/node-idle matching), `allocate_task._find_free_machines`
  (session↔node matching by node_id — dup-IP collapse resolved here),
  `abandon_node` (stuck-task matching), `check_status` (view/json render),
  `show_nodes` (node↔task join).
- `NodeRepository` port: **BREAKING** removes `get(ip)` and `get_by_ips(ips)`;
  `get_by_id(node_id)` unchanged; adds `get_by_ids(node_ids: list[NodeId]) ->
  dict[NodeId, Node]` (batch lookup, new `sql/node/get_by_ids.sql` with
  `WHERE node_id = ANY(:node_ids)`). All remaining lookups are node_id-keyed.
- **BREAKING** domain events `TaskAllocated` and `TaskAbandoned`:
  `node_ip: str → node_id: NodeId`. Emitted with `task.allocated_node_id`
  (was `task.allocated_ip`). `webhook_handler` wire format (`WebhookPayload`:
  task_id, status, custom_params) does not read these fields — unchanged.
- `manage_node` add-path adopts the V1-pattern: `insert(enabled=False) →
  connect(node) → setup → update(enabled=True) → disconnect(node_id)`, with
  `remove(T)` on connect-failure. Removes the last ip-keyed connect site.
- `MachineConnectionError(ip, reason)` stays ip-keyed (transport-level error,
  operator reads the address; `ip` read from `node.ip` at the raise site).
- `Orchestrator._connect_failures: dict[str, float]` rekeys to
  `dict[NodeId, float]` (same lifecycle as `_occupancy_started`).

## Capabilities

### New Capabilities

(None — all changes modify existing capabilities.)

### Modified Capabilities

- `ssh-infrastructure`: `MachineRepository` port rekeys from ip to node_id
  (connect/disconnect/get_session/contains); `SSHMachineRepository._sessions`
  becomes `dict[NodeId, SSHMachineSession]`; `SSHMachineSession` stays clean
  (no node_id); `ConnectedMachine` gains `node_id`.
- `cloud`: `CloudProvisioner.allocate` contract changes — takes `tmp_node_id`,
  returns `Node` (was `NewNode`); `CloudProvisionerImpl` reuses the tmp-node
  row via UPDATE, registers the setup SSH session under `tmp_node_id`.
- `domain-ports`: `NodeRepository` removes `get(ip)`/`get_by_ips(ips)`, adds
  `get_by_ids(node_ids)`; `MachineRepository` rekeyed (also covered under
  `ssh-infrastructure`); `CloudProvisioner.allocate` signature change (also
  covered under `cloud`).
- `domain-entities`: `ConnectedMachine` gains `node_id: NodeId` (first field);
  `Node` docstring updated (ip-keyed lookup methods removed).
- `domain-events-and-dispatch`: `TaskAllocated.node_ip` and
  `TaskAbandoned.node_ip` → `node_id: NodeId`; emission sites updated.
- `orchestrator`: `_task_consumer_consumer` resolves session via
  `allocated_node_id`; `_occupancy_started` and `_connect_failures` rekeyed to
  `NodeId`; `_start_task_on_machine` resolves ncpus via `get_by_id`; 
  `_deallocator_producer` builds `idle_machines: dict[NodeId, float]`;
  `_connect_machine_producer` filters by `contains(node.node_id)`;
  `_connect_machine_consumer` connects via node-keyed path.
- `use-cases`: `allocate_task._find_free_machines` matches session↔node by
  `node_id` (dup-IP collapse resolved); `_provision_and_persist` simplified to
  single `update(node)`; `_persist_node_with_cleanup` folded into the
  update-only path. `deallocate_nodes` rekeys busy/idle matching to node_id.
  `abandon_node` matches stuck tasks by `allocated_node_id`.
- `cli`: `check_status` flips `nodes_by_ip` → `nodes_by_id`, uses
  `get_by_ids`; `_display_remote_output` connects via `Node`. `show_nodes`
  flips `tasks_by_ip` → `tasks_by_node_id`. `manage_node` add-path adopts the
  V1-pattern (insert enabled=False → connect → setup → update enabled=True).
- `postgres-persistence`: `PostgresNodeRepository` removes `get`/`get_by_ips`,
  adds `get_by_ids` with new SQL file `sql/node/get_by_ids.sql`.

## Impact

**Code (13 files)**:
- `yascheduler/domain/model.py` (`ConnectedMachine` +node_id)
- `yascheduler/domain/ports.py` (`MachineRepository`, `NodeRepository`,
  `CloudProvisioner` contracts)
- `yascheduler/domain/events.py` (`TaskAllocated`, `TaskAbandoned`)
- `yascheduler/infra/ssh/repository.py` (`_sessions` rekey, all methods)
- `yascheduler/infra/ssh/session.py` (unchanged — `MachineSession` stays clean;
  `SSHMachineSession` consumes `node_id` via `ConnectedMachine` only)
- `yascheduler/infra/cloud/manager.py` (`allocate`/`_setup_vm`/`_connect_to_vm`
  take `tmp_node_id`, return `Node`)
- `yascheduler/infra/persistence/postgres.py` (`get`/`get_by_ips` removed,
  `get_by_ids` added)
- `yascheduler/application/orchestrator.py` (4 read sites + state rekey)
- `yascheduler/application/allocate_task.py` (`_find_free_machines`,
  `_provision_and_persist` simplification)
- `yascheduler/application/deallocate_nodes.py` (busy/idle rekey)
- `yascheduler/application/abandon_node.py` (matching rekey)
- `yascheduler/entrypoints/cli/check_status.py` (nodes_by_id, get_by_ids,
  connect via Node)
- `yascheduler/entrypoints/cli/show_nodes.py` (tasks_by_node_id)
- `yascheduler/entrypoints/cli/manage_node.py` (add-path V1-pattern)

**SQL (1 new, 2 removed)**:
- NEW `yascheduler/infra/persistence/sql/node/get_by_ids.sql`
- REMOVED `yascheduler/infra/persistence/sql/node/get_by_ip.sql`
- REMOVED `yascheduler/infra/persistence/sql/node/get_by_ips.sql`

**Tests**: Unit tests for every changed use case and port; integration tests
for cloud allocation lifecycle (one-row UPDATE); e2e for full cycle
(submit→allocate→consume→done) and dup-IP disambiguation. Protocol stubs in
unit tests updated for the new `MachineRepository`/`CloudProvisioner`/`NodeRepository`
signatures.

**GRACE-lite**: `docs/knowledge-graph.xml` updated for `M-SSH-REPOSITORY`
(key change), `M-CLOUD-PROVISIONER` (allocate contract), `M-DOMAIN-MODEL`
(ConnectedMachine field), `M-DOMAIN-EVENTS` (TaskAllocated/TaskAbandoned
fields). MODULE_CONTRACT + MODULE_MAP + CHANGE_SUMMARY on all touched files.

**Public API**: `Yascheduler` public API and INI config format unchanged.
AiiDA scheduler plugin unaffected (parses `task_id status`, not node fields).
CLI commands `yasubmit`/`yastatus`/`yanodes`/`yasetnode`/`yainit`/`yascheduler`
entry points unchanged in name and exit-code contract; `yastatus --json`
payload keeps `allocated_ip` field (transport display) but adds nothing
breaking.

**DB schema**: No migration required. `allocated_node_id` FK already added by
`task-allocated-node-id` (migration 004). `ip` UNIQUE already dropped
(migration 003). This change is pure code + SQL-file-removal.

**Prerequisite**: The `task-allocated-node-id` change (58/58 tasks done in the
working tree, uncommitted) must be committed first — this change consumes its
read side (`task.allocated_node_id`). Starting from a clean tree avoids
conflating two changes in review.

**Dependencies**: None added.
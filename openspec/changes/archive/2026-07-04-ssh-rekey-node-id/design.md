## Context

This is the final surface of the `Node.ip → Node.node_id` migration arc. The
prior archived changes (`add-node-id-identity`, `node-id-keyed-mutators`,
`deallocate-node-id-identity`) rekeyed the node mutators and deallocate queue.
The uncommitted `task-allocated-node-id` change added the `allocated_node_id`
FK and the write path. This change consumes the read side and rekeys
`SSHMachineRepository._sessions` — the last ip-as-identity collection.

Current state of the two surfaces this change touches:

**SSH layer** (`infra/ssh/repository.py`): `SSHMachineRepository._sessions` is
`dict[str, SSHMachineSession]` keyed by ip. `connect(ip, …)` opens a transport,
detects platform, builds a `ConnectedMachine(ip, platform, ncpus, state, …)`,
wraps it in `SSHMachineSession`, stores under `ip`. `disconnect(ip)` pops and
closes. `get_session(ip)`, `contains(ip)`, `list_free/list_connected` all read
the ip-keyed dict. `MachineSession` Protocol exposes `ip: str` and
`machine: ConnectedMachine`.

**Cloud allocation** (`infra/cloud/manager.py` + `application/allocate_task.py`):
`_select_and_insert_tmp` inserts a tmp-node row (enabled=False, ip="") and
receives `tmp_node_id = T`. `clouds.allocate(provider)` creates the VM, connects
to it under `ip_addr` (registering the session under `ip_addr`, NOT under T),
runs cloud-init/setup, returns `NewNode(ip=ip_addr, enabled=True, …)` with **no
node_id**. `_persist_node_with_cleanup` then inserts a **new** row (generating
a **different** node_id = R) and removes the tmp row T. The cloud-setup session
registered under `ip_addr` survives by coincidence: orchestrator's
`_connect_machine_producer` checks `contains(ip)` against the new real-node's
ip, finds the session, and skips reconnect.

This coincidence has two latent bugs:
1. Two DB rows (T and R) exist for one cloud allocation lifecycle — T is removed
   only on the success path; the design intent was a single row reused via
   UPDATE.
2. The session is keyed by `ip_addr`, so the dup-IP disambiguation never lands
   here — two cloud nodes sharing an IP (different jump hosts) collapse.

## Goals / Non-Goals

**Goals:**
- Rekey `SSHMachineRepository._sessions` to `dict[NodeId, SSHMachineSession]`.
- Rekey all `MachineRepository` port methods from ip to `node_id`/`Node`.
- Flip the 9 read sites from `task.allocated_ip` to `task.allocated_node_id`.
- Resolve the dup-IP collapse in `allocate_task._find_free_machines` by matching
  session↔node via `node_id` instead of ip.
- Fix the cloud-allocation two-rows-per-lifecycle bug by reusing `tmp_node_id`
  as the real node's identity (V1: UPDATE instead of insert+remove).
- Adopt the V1-pattern in `manage_node` add-path (last ip-keyed connect site).
- Remove `NodeRepository.get(ip)` and `get_by_ips(ips)`; add `get_by_ids`.
- Flip `TaskAllocated`/`TaskAbandoned` events from `node_ip` to `node_id`.
- Keep `MachineSession` Protocol clean (no `node_id`) — identity lives on
  `ConnectedMachine`.

**Non-Goals:**
- `CloudProvisioner.deallocate(cloud, ip)` stays ip-keyed — `ip` is the cloud
  SDK host identifier; enriching it to carry `external_id`/`Node` is a future
  cloud-adapter change.
- `MachineConnectionError(ip, reason)` stays ip-keyed — transport-level error.
- DB schema migrations — none required (migration 003 dropped `ip UNIQUE`,
  migration 004 added `allocated_node_id`).
- `serial-to-generated-identity` (parallel hygiene change) — independent,
  sequenced separately.
- AiiDA scheduler plugin — unaffected (parses `task_id status`, not node
  fields).
- `Yascheduler` public API and INI config format — unchanged.

## Decisions

### D1 — `_sessions: dict[NodeId, SSHMachineSession]` (single key space)

**Choice**: One dict keyed by `NodeId`. The identity-taking methods
(`connect`, `disconnect`, `get_session`, `contains`, `__contains__`) take
`node_id` or `Node`. `ip` survives only as `node.ip` read inside `connect` for
the asyncssh transport address. The non-identity methods (`disconnect_all`,
`list_free`, `list_connected`, `__len__`) keep their signatures unchanged.

**Rejected: hybrid (b)** — `connect(ip)` for CLI/cloud + `connect_node(node)`
for orchestrator. Based on the false premise that cloud/CLI paths are
"forever ip-keyed". Cloud adapters will carry provider metadata on `Node` in
future; CLI host-spec paths can resolve `Node` before connect via the V1-pattern
(`insert(enabled=False) → connect → setup → update`). Single contract is cleaner
and unblocks future enrichment.

**Rejected: dual-key (c)** — `dict[NodeId, Session]` + `dict[ip, NodeId]` index.
Doubles the structures to keep in sync, complicates `disconnect` (two pops).
No benefit over reading `session.machine.node_id` when needed.

### D2 — `node_id` on `ConnectedMachine`, not on `MachineSession`

**Choice**: `ConnectedMachine` (domain model) gains `node_id: NodeId` as its
first field. `MachineSession` Protocol and `SSHMachineSession` impl stay clean
(no `node_id`). Read via `session.machine.node_id`.

**Rationale**: `ConnectedMachine` already carries `ip` (the implicit node
identity today). Adding `node_id` is a refinement of what's already there —
domain→domain, not an abstraction leak. `MachineSession` is the SSH-transport
handle; `NodeId` is a domain concept. Keeping `MachineSession` clean preserves
the layering. `replace(self, state=…)` on the frozen dataclass carries `node_id`
automatically — no special handling at `occupy`/`release` sites.

**Rejected: reverse-lookup in repository (A)** —
`repo.node_id_for(session) -> NodeId`. Adds a second index
`dict[id(session), NodeId]` that must stay in sync with `_sessions` (or pay
O(n) per query). `ConnectedMachine.node_id` gives O(1) via one field.

**Rejected: `node_id` on `MachineSession` (D)** — leak. The SSH-transport handle
should not know the domain identity concept.

### D3 — V1 cloud lifecycle: single row, UPDATE not insert+remove

**Choice**: `CloudProvisioner.allocate(provider, tmp_node_id: NodeId) -> Node`.
The tmp-node row inserted by `_select_and_insert_tmp` (node_id=T) is reused:
the cloud setup SSH session registers under T, `_setup_vm` returns
`Node(node_id=T, ip=ip_addr, enabled=True, …)`, and `_persist` becomes a single
`uow.nodes.update(node)` (flips enabled to TRUE, sets ip/ncpus). No
`insert(NewNode)` + `remove(tmp_node_id)` pair. On any failure after tmp insert,
`uow.nodes.remove(T)` rolls back the tmp row.

**Rationale**: Fixes the latent two-rows-per-lifecycle bug. The cloud setup
session, registered under T, is the same session orchestrator finds via
`contains(T)` after the UPDATE flips enabled — no re-connect, no coincidence.
This is the prerequisite that makes the SSH-rekey cloud path correct: without
V1, the session would be registered under `ip_addr` (pre-UPDATE) and
orchestrator's `contains(node.node_id=R)` would miss it, causing a duplicate
connect.

**Rejected: separate V1 change (C)** — V1 is ~3 lines of code but touches the
`CloudProvisioner` port contract. A 300-line spec for a 3-line code change is
disproportionate. Folded into this change because it's the prerequisite for
the SSH-rekey cloud path correctness.

**Rejected: rekey session after persist** — register under T in `_setup_vm`,
then `repository.rekey(old=T, new=R)` after persist. Introduces a rekey
operation and a race window between persist and rekey where orchestrator may
try `contains(R)` and miss. V1 avoids this entirely by making T == R.

### D4 — `manage_node` add-path adopts V1-pattern

**Choice**: `_add_node` becomes `insert(NewNode(ip=spec.host, enabled=False,
…)) → Node(T)` → `connect(node=T, …)` → optional `setup_node` →
`update(T, enabled=True)` → `disconnect(T)`. On connect-failure: `remove(T)`.

**Rationale**: The current flow (`connect(ip) → setup → insert(NewNode)`) works
only because `connect` accepts ip. After D1, `connect` requires `Node`. The
V1-pattern (identical to cloud allocation) is the natural adaptation: insert
the row first (enabled=False so orchestrator's `list_enabled()` skips it),
connect under T, enable. Orchestrator never sees the tmp row because
`enabled=False` excludes it; after UPDATE, `contains(T)` is true and reconnect
is skipped.

### D5 — `get_by_ids` batch SQL (not loop over `get_by_id`)

**Choice**: New `sql/node/get_by_ids.sql` with `WHERE node_id = ANY(:node_ids)`,
returning `dict[NodeId, Node]`. Used by `check_status` (batch lookup of nodes
for all running tasks) and any future batch consumer.

**Rationale**: `check_status` fetches nodes for N running tasks. A loop over
`get_by_id` would be N DB round-trips. The batch SQL is one round-trip.
`show_nodes` doesn't need it (it does `list_all()` + in-memory join).

### D6 — Remove `get(ip)` and `get_by_ips(ips)` from `NodeRepository`

**Choice**: Both methods are removed from the `NodeRepository` Protocol,
`PostgresNodeRepository` impl, and their SQL files (`get_by_ip.sql`,
`get_by_ips.sql`). `get_by_id(node_id)` stays (unchanged).

**Rationale**: After this change, no caller resolves a node by ip.
`manage_node` host_spec path resolves via `get_by_id` through `NodeTarget`
(`target.node_id` is set by the parser when the operator passes a node_id; the
host_spec path resolves the node through a validation UoW and passes the
`Node` forward). `check_status` flips to `get_by_ids`. Removing dead methods
prevents future ip-keyed regressions.

### D7 — `TaskAllocated`/`TaskAbandoned` events: `node_ip → node_id`

**Choice**: Both events replace `node_ip: str` with `node_id: NodeId`. Emission
sites pass `task.allocated_node_id` (was `task.allocated_ip`). `webhook_handler`
builds `WebhookPayload(task_id, status, custom_params)` — does not read
`node_ip`/`node_id`, so the wire format is unchanged. No external breakage.

**Rationale**: Internal event field consistency — the events describe task→node
binding, and `node_id` is the node identity. Keeping `node_ip` would be a
leftover ip-as-identity field. Both events flip together because they share the
same field and the same emission pattern.

### D8 — `MachineConnectionError(ip, reason)` unchanged

**Choice**: `MachineConnectionError` keeps its `(ip: str, reason: str)` shape.
At the raise site (`SSHMachineRepository.connect`), `ip` is read from `node.ip`.

**Rationale**: This is a transport-level error. The operator reading the error
message wants the address that failed to connect, not the internal node_id. The
error is raised exactly at the point where `ip` is the meaningful identifier
(the asyncssh connect just failed against that host).

### D9 — `_connect_failures` and `_occupancy_started` rekey to `NodeId`

**Choice**: `Orchestrator._connect_failures: dict[NodeId, float]` (was
`dict[str, float]` keyed by ip). `_occupancy_started: set[NodeId]` (was
`set[str]`). Both keyed by `node.node_id` (from `_connect_machine_consumer`'s
`Node`) or `task.allocated_node_id` (from `_task_consumer_consumer`).

**Rationale**: These are in-memory orchestrator state tracking per-node. They
must key on the same identity as `_sessions` to stay consistent. Trivial rekey
— same lifecycle, same pop/discard patterns.

## Risks / Trade-offs

**[R1] Cloud allocation race between `_setup_vm` connect and orchestrator scan**
→ Mitigation: The tmp-node row is `enabled=False` during `_setup_vm`.
`_connect_machine_producer` filters by `list_enabled()`, so the tmp row is
invisible. After `_persist`'s `update(enabled=True)`, orchestrator sees the
node, but `contains(T)` is already true (session registered during `_setup_vm`)
— reconnect is skipped. No race window.

**[R2] `manage_node` add-path now creates a DB row before SSH verification**
→ Mitigation: The row is `enabled=False` (invisible to orchestrator). On
connect-failure, `remove(T)` rolls back. The operator-visible behavior is
unchanged: success → "Added host", failure → error + no row remains. The
TOCTOU window (row exists briefly during connect) is acceptable for a
single-operator CLI (matches the existing D18 design decision in `manage_node`).

**[R3] `ConnectedMachine` positional constructor shifts (BREAKING)**
→ Mitigation: Internal-only — only `SSHMachineRepository._connect_impl` (and
tests) construct `ConnectedMachine`. All construction sites are updated in this
change. No public API constructs it. Tests using keyword args are unaffected;
tests using positional args are updated.

**[R4] `CloudProvisioner.allocate` contract change is BREAKING for any external
implementor of the port** → Mitigation: `CloudProvisioner` is an internal port
(`Protocol` in `domain/ports.py`); the only implementor is
`CloudProvisionerImpl`. No external consumers. The contract change is
coordinated with the impl change in the same commit.

**[R5] Removed `get(ip)`/`get_by_ips` may be used by untracked callers**
→ Mitigation: grep confirms all callers are within the changed files. The
`NodeRepository` Protocol is `runtime_checkable` but internal. No external
plugin or client uses these methods.

**[R6] `_find_free_machines` matching semantics change intentionally**
→ Acknowledgement (not a hazard): the dup-IP resolution is the *goal* of the
change. Two enabled nodes sharing an ip (different jump hosts) now have
distinct `node_id` keys in `nodes_by_id`, and each session matches its own node
via `s.machine.node_id`. The prior `nodes_by_ip` collapse (last-wins) was the
bug. Verified by an e2e test with two nodes sharing one ip.

**[R7] `TaskAllocated`/`TaskAbandoned` event field rename is BREAKING for any
consumer reading `node_ip`** → Mitigation: `webhook_handler` is the only
registered handler and does not read the field. No external consumer parses
these events. The rename is internal-only.

## Migration Plan

No DB migration. No config migration. No deployment ordering constraint beyond
the prerequisite: commit `task-allocated-node-id` first.

**Data flows** (per explore-brief, unchanged in this change — decision sections
describe the per-site modifications):
- **Cloud allocation**: `_provision_and_persist(tmp_node_id=T)` →
  `CloudProvisionerImpl.allocate(provider, T)` → `_setup_vm(ip_addr, T, …)` →
  `connect(Node(node_id=T, ip=ip_addr), …)` → `uow.nodes.update(node)` (see D3).
- **Task consumption**: `_task_consumer_consumer(task)` →
  `get_session(task.allocated_node_id)` → `_start_task_on_machine` →
  `get_by_id(task.allocated_node_id)` (see D9).
- **Deallocation**: `_deallocator_producer` → `list_connected()` →
  `idle_machines: dict[NodeId, float]` → `deallocate_nodes` (node_id-keyed
  busy/idle matching) (see D9).
- **CLI check_status**: `get_by_ids([t.allocated_node_id…])` →
  `nodes_by_id.get(t.allocated_node_id)` → `_display_remote_output`
  connects via `Node` (see D5).

**Rollback**: Revert the commit. The DB schema is unchanged by this change
(migrations 003/004 are from prior changes and stay). Reverting restores
ip-keyed behavior. No data loss risk — the change is pure code + SQL file
addition/removal.

**Verification gates** (per OpenSpec `testing-unit`, `test-db-integration`,
`e2e-testing`):
- `uv run pytest -m unit` — all changed use cases and ports have unit tests.
- `uv run pytest -m integration` — cloud allocation lifecycle (single-row
  UPDATE), `get_by_ids` batch query.
- `uv run pytest -m e2e` — full cycle (submit→allocate→consume→done) with
  dup-IP disambiguation scenario.
- `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run lint-imports` — static checks.
- `python3 scripts/grace_check.py` — GRACE-lite validation.
- `openspec validate --all --json` — spec validation.

## Open Questions

None outstanding — all 8 open questions from the explore-brief are resolved
(see Decisions D1–D9 and the proposal's "What Changes" section).
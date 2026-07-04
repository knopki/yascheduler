# Explore Brief — ssh-rekey-node-id

## Context

This change continues the Node.ip → Node.node_id migration arc. Prior archived
changes established the foundation: `add-node-id-identity` (NodeId value object,
migration 003 dropping ip UNIQUE), `node-id-keyed-mutators` (enable/disable/remove
/update rekeyed to node_id), `deallocate-node-id-identity` (deallocate_nodes
returns list[Node], _deallocate_q rekeyed to NodeId). The active uncommitted
change `task-allocated-node-id` added `allocated_node_id` FK + write path
(allocate_to binds both allocated_ip and allocated_node_id) — its 58 tasks are
done in the working tree. This change consumes the read side.

## Rejected Alternatives

### A. Reverse-lookup in SSHMachineRepository (session → node_id)

Rejected. Adds a second index `dict[id(session), NodeId]` that must stay in sync
with `_sessions` (or pay O(n) per query). `ConnectedMachine.node_id` (chosen
approach) gives O(1) via one frozen-dataclass field that `replace()` carries
automatically. Reverse-lookup was motivated only to avoid `node_id` on
`ConnectedMachine`, which was ruled acceptable.

### B. Hybrid connect: `connect(ip)` for CLI/cloud + `connect_node(node)` for orchestrator

Rejected. Based on the false premise that cloud adapter and CLI host-spec paths
are "forever ip-keyed". Cloud adapters will carry additional provider metadata
(external_id etc.) stored on Node in future; CLI host-spec paths can resolve
Node before connect (insert(enabled=False) → connect → setup →
update(enabled=True)). Single node-keyed connect contract is cleaner and
unblocks future cloud-adapter enrichment.

### C. Separate V1 change (cloud tmp-node lifecycle: UPDATE instead of insert+remove)

Rejected as standalone. The current implementation has a bug: tmp-node and
real-node are two separate DB rows with different node_ids for one cloud
allocation lifecycle. V1 fix (one row, UPDATE, tmp_node_id reused as real
node_id) is ~3 lines of code change but touches the CloudProvisioner port
contract. Folded into this change because: (1) it's the prerequisite that makes
the SSH-rekey cloud path correct (session registered under tmp_node_id survives
as the real node's session), (2) separating a 3-line code change with a 300-line
spec is disproportionate overhead.

### D. node_id on MachineSession Protocol

Rejected as abstraction leak. MachineSession is the SSH-transport handle;
NodeId is a domain concept. node_id lives on ConnectedMachine (the domain
machine snapshot), read via `session.machine.node_id`. MachineSession Protocol
stays clean.

## Final Approach — Labels, Dimensions, Mapping Tables

### Identity model

```
DOMAIN                              INFRA
Node          ip, node_id, ncpus, …
ConnectedMachine  node_id, ip, platform, state, ncpus, free_since
                                     ↑ replace() carries node_id automatically
MachineSession (Protocol)   ip, machine, …   ← NO node_id (clean)
SSHMachineSession           _machine, _conn   ← NO node_id
SSHMachineRepository  _sessions: dict[NodeId, Session]
                       get_session(node_id), contains(node_id), disconnect(node_id)
                       list_free/list_connected (unchanged shape; machine.node_id readable)
```

### MachineRepository port — final contract

```
METHOD                  TODAY (ip-keyed)              AFTER (node-keyed)
─────────────────────────────────────────────────────────────────────
connect(ip, username,    → MachineSession             connect(node: Node, username, …) → MachineSession
  client_keys, *, port, …)                              (ip read from node.ip for transport)
disconnect(ip)           → None                       disconnect(node_id: NodeId) → None
disconnect_all()         → None                       disconnect_all() → None (unchanged)
get_session(ip)          → MachineSession | None      get_session(node_id: NodeId) → MachineSession | None
contains(ip)             → bool                       contains(node_id: NodeId) → bool
__contains__(ip)         → bool                       __contains__(node_id: NodeId) → bool
list_free(platforms)     → list[MachineSession]       list_free(platforms) → list[MachineSession] (unchanged)
list_connected()         → list[MachineSession]       list_connected() → list[MachineSession] (unchanged)
__len__()                → int                        __len__() → int (unchanged)
```

### CloudProvisioner port — final contract

```
METHOD                  TODAY                         AFTER
─────────────────────────────────────────────────────────────────────
allocate(provider)      → NewNode                     allocate(provider, tmp_node_id: NodeId) → Node
deallocate(cloud, ip)   → None                        deallocate(cloud, ip) → None (unchanged — ip is cloud SDK host)
select_provider(...)    → str | None                  select_provider(...) → str | None (unchanged)
get_capacity(...)       → int                         get_capacity(...) → int (unchanged)
```

### NodeRepository port — additive method

```
METHOD                  STATUS
─────────────────────────────────────────────────────────────────────
get(ip)                 REMOVED (no ip-keyed callers after this change)
get_by_id(node_id)      unchanged
get_by_ids(node_ids)    NEW — batch lookup, dict[NodeId, Node] return
get_by_ips(ips)         REMOVED (no ip-keyed callers after this change)
list_enabled()          unchanged
list_disabled()         unchanged
list_all()              unchanged
insert/update/enable/disable/remove  unchanged (already node_id-keyed)
count_by_status()       unchanged
count_by_cloud()        unchanged
```

### Domain events — final shape

```
EVENT             TODAY                         AFTER
─────────────────────────────────────────────────────────────────────
TaskAllocated     node_ip: str                  node_id: NodeId
                  engine_name: str              engine_name: str
TaskAbandoned     node_ip: str                  node_id: NodeId
TaskCompleted     (unchanged)                   (unchanged)
TaskCreated       (unchanged)                   (unchanged)
TaskFailed        (unchanged)                   (unchanged)
```

### Read-site flip mapping (9 sites)

```
#  SITE                                                TODAY                                  AFTER
──────────────────────────────────────────────────────────────────────────────────────────────────────────
1  orchestrator._task_consumer_consumer get_session    get_session(task.allocated_ip)        get_session(task.allocated_node_id)
2  orchestrator._task_consumer_consumer _occupancy_started  set[str] keyed by ip              set[NodeId] keyed by allocated_node_id
3  orchestrator._start_task_on_machine uow.nodes.get   uow.nodes.get(task.allocated_ip)      uow.nodes.get_by_id(task.allocated_node_id)
4  orchestrator._deallocator_producer idle_machines    dict[ip→ts]                           dict[NodeId→ts]
5  deallocate_nodes busy_ips/nodes_by_ip/idle_match    ip-keyed                              node_id-keyed
6  allocate_task._find_free_machines matching          nodes_by_ip[s.machine.ip]             nodes_by_id[s.machine.node_id]  ← dup-IP collapse resolved here
7  abandon_node matching                               [t if t.allocated_ip == node.ip]      [t if t.allocated_node_id == node.node_id]
8  check_status _render_view/_render_json              nodes_by_ip.get(t.allocated_ip)       nodes_by_id.get(t.allocated_node_id)
                                                          get_by_ips([t.allocated_ip…])         get_by_ids([t.allocated_node_id…])
9  show_nodes _fetch_nodes_view tasks_by_ip            {t.allocated_ip: t}                   {t.allocated_node_id: t}
```

### V1 cloud lifecycle — final flow (single row, UPDATE not insert+remove)

```
_select_and_insert_tmp:
  insert(NewNode(cloud, enabled=False, ip="")) → tmp_node (node_id=T)

_allocate_cloud_node → clouds.allocate(provider, tmp_node_id=T):
  CloudProvisionerImpl.allocate:
    adapter.create_node() → ip_addr
    _setup_vm(ip_addr, tmp_node_id=T, …):
      connect(node=Node(node_id=T, ip=ip_addr, …), …)  ← session registered under T
      cloud-init, setup_node, get_cpu_cores
      return Node(node_id=T, ip=ip_addr, enabled=True, ncpus, cloud, username, port)
    return Node   ← not NewNode; row T already exists

_persist (simplified):
  uow.nodes.update(node)   ← UPDATE row T: enabled=TRUE, ip=ip_addr, ncpus
  commit
  (NO remove(tmp_node_id) — T IS node.node_id)

on failure (anywhere after tmp insert):
  uow.nodes.remove(T)   ← rollback tmp row
```

### manage_node add-path — final flow (V1-pattern parity)

```
_add_node:
  insert(NewNode(ip=spec.host, enabled=False, …)) → Node(T)
  connect(node=T, ip=spec.host)   ← session under T
  setup_node(session)   ← optional
  update(T, enabled=True)
  disconnect(T)
on connect-fail: remove(T)
```

## Cross-module Data Flows

### Cloud allocation (daemon)

```
allocate_task._provision_and_persist(tmp_node_id=T)
  → CloudProvisionerImpl.allocate(provider, T)
      → _setup_vm(ip_addr, T, …)
          → SSHMachineRepository.connect(Node(node_id=T, ip=ip_addr), …) → MachineSession
          → machine_operations.setup_node(session)
      → return Node(node_id=T, ip=ip_addr, enabled=True, …)
  → uow.nodes.update(node)   [enables row T, sets ip/ncpus]
  → commit
```

### Task consumption (daemon)

```
orchestrator._task_consumer_consumer(task)
  → repository.get_session(task.allocated_node_id) → session
  → _start_task_on_machine(session, engine, task)
      → uow.nodes.get_by_id(task.allocated_node_id) → node (ncpus resolution)
      → operations.start_task_on_machine(session, engine, task, ncpus, …)
```

### Deallocation (daemon)

```
orchestrator._deallocator_producer()
  → repository.list_connected() → sessions
  → idle_machines = {s.machine.node_id: s.machine.free_since for FREE sessions}
  → deallocate_nodes(uow_factory, clouds, idle_machines)
      → list_disabled() → nodes; busy_node_ids from RUNNING tasks
      → disable each node where node.node_id in idle_machines and node.node_id not in busy_node_ids
      → return list[Node]
  → yield UMessage(node.node_id, node) for each
```

### CLI check_status (separate SSHMachineRepository instance)

```
check_status._check_status_async
  → uow.tasks.list_by_status
  → uow.nodes.get_by_ids([t.allocated_node_id for t in tasks]) → nodes_by_id
  → for each running task:
      node = nodes_by_id.get(task.allocated_node_id)
      _resolve_conn_params(node, config) → (username, port, jump_host, jump_username)
      _display_remote_output(task, conn_params, config)
          → SSHMachineRepository().connect(Node(node_id=node.node_id, ip=node.ip), …) → session
          → tail OUTPUT, parse convergence
          → repository.disconnect(session.machine.node_id)
```

## Open Questions

1. **Migration requirement**: Does `get_by_ids` need a new SQL file
   `sql/node/get_by_ids.sql` (`WHERE node_id = ANY(:node_ids)`), or reuse
   `get_by_id` in a loop? → Decision: new batch SQL file (check_status is the
   hot batch consumer; loop would be N round-trips).

2. **MachineConnectionError field shape**: Keep `(ip, reason)` (transport-level
   error, operator reads address). `ip` read from `node.ip` at raise site.
   Confirmed.

3. **TaskAbandoned flip**: Same as TaskAllocated — `node_ip: str` →
   `node_id: NodeId`. Emitted from orchestrator._task_consumer_consumer with
   `task.allocated_node_id` (was `ip = task.allocated_ip`). Confirmed.

4. **webhook_handler wire format**: `WebhookPayload(task_id, status,
   custom_params)` does NOT read node_ip/node_id. Wire format unchanged. Safe.

5. **AiiDA scheduler plugin**: Parses `task_id status` (2 fields) from
   `yastatus` default output. Does NOT parse allocated_ip/node_id. Unaffected.

6. **_connect_failures: dict[str, float] in Orchestrator**: Today keyed by
   `node.ip`. Rekey to `dict[NodeId, float]` — trivial, same lifecycle as
   _occupancy_started.

7. **commit task-allocated-node-id before this change**: Recommended — start
   from clean tree. This change consumes its read side (task.allocated_node_id).

8. **get(ip) / get_by_ips removal**: Both methods have no remaining callers
   after this change (manage_node host_spec path now goes through get_by_id via
   NodeTarget; check_status flips to get_by_ids). Remove from Protocol + impl +
   SQL files. Confirmed in scope.
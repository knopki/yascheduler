## MODIFIED Requirements

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineRepository`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-node connect-failure timer
(`dict[NodeId, float]` mapping `node_id` to the monotonic timestamp of the
first consecutive failure) in memory. On a successful
`repository.connect(node, client_keys, ...)` for a node, the orchestrator SHALL
pop that node's `node_id` from the failure timer. For cloud-provisioned nodes,
on `MachineConnectionError`, the orchestrator SHALL compare the elapsed monotonic
age against the node's cloud `connect_grace` (looked up from
`active_clouds` by `prefix == node.cloud`).

The orchestrator SHALL NOT resolve jump-leg parameters (no `config.remote`
lookup, no `CloudConfig` prefix-match loop for jump). All connection identity
comes from the `Node` itself; `repository.connect` reads `node.jump_host` /
`node.jump_port` / `node.jump_username` directly.

The connect-machine producer SHALL yield all enabled nodes that are not
currently registered in the repository, regardless of `cloud`. Static
operator-managed nodes (`cloud is None`) SHALL be connected like cloud nodes.
On `MachineConnectionError` for a static node (`cloud is None`), the
orchestrator SHALL log a `CONNECT_RETRY_STATIC` warning and return early
BEFORE the grace-check — so static nodes retry indefinitely on every producer
cycle, never accumulate entries in the failure timer, and NEVER reach the
`abandon_node` use case. A transient SSH outage (e.g. after a daemon restart)
must not silently delete an operator's node row.

For cloud nodes (`cloud is not None`):

- If `age < connect_grace`, the orchestrator SHALL log the failure and return;
  the next producer cycle re-yields the node (retry behavior unchanged).
- If `age >= connect_grace`, the orchestrator SHALL call the `abandon_node`
  use case with the node, the cloud provisioner, the UoW factory, and the
  allocation tracker, then pop the `node_id` from the failure timer. The
  `abandon_node` use case deletes the cloud VM, removes the
  `yascheduler_nodes` row, and discards the tracker entry linked to the node
  via `tracker.discard_by_node(node.node_id)` so the task re-allocates on the
  next cycle. The discard is by node, not by a TO_DO task lookup — the
  cloud-provisioning path never binds the task to the node, so the
  task-to-node link is held by the tracker (established by `allocate_task`'s
  `set_node` call), not by `Task.allocated_node_id`.

The failure timer SHALL NOT be persisted across daemon restarts (in-memory
only). A restart resets the grace window for any node that was mid-failure.

For nodes whose `node.cloud` is a non-None value that does not match any
`CloudConfig.prefix` in `active_clouds`, the orchestrator SHALL fall
back to a conservative default `connect_grace` of 120 seconds (matches the
slowest cloud default) so the abandon path still fires for misconfigured or
unknown clouds. This fallback does NOT apply to `cloud is None` (static
nodes), which are handled before the grace-check and never reach the abandon
path.

#### Scenario: New node connected

- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via `repository.connect(node, client_keys, ...)` with no `jump_host` / `jump_username` arguments (the repository reads them from `node`)

#### Scenario: Connection failure within grace retries, past grace triggers abandon

- **WHEN** `repository.connect(node, client_keys, ...)` raises `MachineConnectionError` for a cloud node
- **THEN** if elapsed failure age < `connect_grace`, the orchestrator logs and returns (retry next cycle); if age >= `connect_grace`, the orchestrator calls `abandon_node` (which discards the tracker entry by node via `discard_by_node`) and pops the `node_id` from the failure timer

#### Scenario: Successful connect resets the failure timer

- **WHEN** `repository.connect(node, client_keys, ...)` succeeds for a node that had a prior `MachineConnectionError`
- **THEN** the orchestrator pops the `node_id` from the failure timer

#### Scenario: Connect reads jump identity from Node

- **WHEN** the orchestrator calls `repository.connect(node, client_keys, connect_timeout=10, data_dir=..., engines_dir=..., tasks_dir=...)` for a node with `jump_host="bastion.example.com"`
- **THEN** no inline resolution loop runs (no iteration over `config.clouds`, no read of `config.remote.jump_host`), and the tunnel leg is built from `node.jump_host` / `node.jump_username` / `node.jump_port` inside the repository

## MODIFIED Requirements

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineGateway`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-IP connect-failure timer
(`dict[str, float]` mapping IP to the monotonic timestamp of the first
consecutive failure) in memory. On a successful `gateway.connect(...)` for an
IP, the orchestrator SHALL pop that IP from the failure timer. For
cloud-provisioned nodes, on `MachineConnectionError`, the orchestrator SHALL
compare the elapsed monotonic age against the node's cloud `connect_grace`
(looked up from `self._config_clouds` by `prefix == node.cloud`).

The connect-machine producer SHALL yield all enabled nodes that are not
currently registered in the gateway, regardless of `cloud`. Static
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
  use case with the node, the gateway, the cloud provisioner, the UoW
  factory, and the allocation tracker, then pop the IP from the failure timer.
  The `abandon_node` use case deletes the cloud VM, removes the
  `yascheduler_nodes` row, and discards the stuck task's entry from
  `AllocationTracker` so the task re-allocates on the next cycle.

The failure timer SHALL NOT be persisted across daemon restarts (in-memory
only). A restart resets the grace window for any IP that was mid-failure.

For nodes whose `node.cloud` is a non-None value that does not match any
`CloudConfig.prefix` in `self._config_clouds`, the orchestrator SHALL fall
back to a conservative default `connect_grace` of 120 seconds (matches the
slowest cloud default) so the abandon path still fires for misconfigured or
unknown clouds. This fallback does NOT apply to `cloud is None` (static
nodes), which are handled before the grace-check and never reach the abandon
path.

#### Scenario: New node connected
- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via gateway and the machine is registered

#### Scenario: Connection failure caught as domain error
- **WHEN** `gateway.connect(...)` fails
- **THEN** the orchestrator catches `MachineConnectionError` and logs the error

#### Scenario: Connection failure within grace retries
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for an IP whose elapsed failure age is less than the node's cloud `connect_grace`
- **THEN** the orchestrator logs the failure and returns without calling `abandon_node`; the IP remains in the failure timer and the next producer cycle re-yields the node

#### Scenario: Connection failure past grace triggers abandon
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for an IP whose elapsed failure age is greater than or equal to the node's cloud `connect_grace`
- **THEN** the orchestrator calls `abandon_node(node, gateway, clouds, uow_factory, tracker)`, pops the IP from the failure timer, and the node is no longer yielded by subsequent producer cycles (its DB row is removed)

#### Scenario: Successful connect resets the failure timer
- **WHEN** `gateway.connect(...)` succeeds for an IP that had a prior `MachineConnectionError` recorded in the failure timer
- **THEN** the orchestrator pops the IP from the failure timer and subsequent failures for that IP start a fresh grace window

#### Scenario: Unknown cloud falls back to conservative grace
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for a node whose `cloud` is a non-None value that does not match any `CloudConfig.prefix` in `self._config_clouds`
- **THEN** the orchestrator uses a `connect_grace` of 120 seconds for the age comparison

#### Scenario: Daemon restart resets failure timers
- **WHEN** the daemon restarts with an IP that was mid-failure (age had accumulated toward `connect_grace`)
- **THEN** the in-memory failure timer is empty on start and the IP's next `MachineConnectionError` starts a fresh grace window

#### Scenario: Static node connected by orchestrator
- **WHEN** an enabled node has `cloud is None` (a static operator-managed node) and is not currently registered in the gateway
- **THEN** the connect-machine producer yields the node to the consumer, an SSH connection is established via gateway, the machine is registered, and the failure timer is not populated for that IP

#### Scenario: Non-cloud node retried without abandon
- **WHEN** an enabled node has `cloud is None` (a static operator-managed node), is not currently registered in the gateway, and `gateway.connect(...)` raises `MachineConnectionError`
- **THEN** the orchestrator logs a `CONNECT_RETRY_STATIC` warning and returns without calling `abandon_node`, without populating the failure timer, and without removing the `yascheduler_nodes` row — even across daemon restarts, transient SSH outages, or failures past 120 seconds
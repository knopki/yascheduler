## MODIFIED Requirements

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineGateway`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-IP connect-failure timer
(`dict[str, float]` mapping IP to the monotonic timestamp of the first
consecutive failure) in memory. On a successful `gateway.connect(...)` for an
IP, the orchestrator SHALL pop that IP from the failure timer. On
`MachineConnectionError`, the orchestrator SHALL compare the elapsed monotonic
age against the node's cloud `connect_grace` (looked up from
`self._config_clouds` by `prefix == node.cloud`):

The connect-machine producer SHALL only yield enabled nodes whose `cloud` is
not None (cloud-provisioned nodes). Static operator-managed nodes
(`cloud is None`) SHALL NOT be yielded to the connect-machine consumer and
therefore SHALL NEVER reach the abandon path — the application has never
auto-removed static nodes and a transient SSH outage (e.g. after a daemon
restart) must not silently delete an operator's node row.

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

For nodes whose `node.cloud` does not match any `CloudConfig.prefix` in
`self._config_clouds`, the orchestrator SHALL fall back to a conservative
default `connect_grace` of 120 seconds (matches the slowest cloud default) so
the abandon path still fires for misconfigured or unknown clouds.

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
- **WHEN** `gateway.connect(...)` raises `MachineConnectionError` for a node whose `cloud` does not match any `CloudConfig.prefix` in `self._config_clouds`
- **THEN** the orchestrator uses a `connect_grace` of 120 seconds for the age comparison

#### Scenario: Daemon restart resets failure timers
- **WHEN** the daemon restarts with an IP that was mid-failure (age had accumulated toward `connect_grace`)
- **THEN** the in-memory failure timer is empty on start and the IP's next `MachineConnectionError` starts a fresh grace window

#### Scenario: Non-cloud node excluded from abandon path
- **WHEN** an enabled node has `cloud is None` (a static operator-managed node) and is not currently registered in the gateway
- **THEN** the connect-machine producer SHALL NOT yield the node to the consumer, so it never reaches the grace timer, never reaches `abandon_node`, and its `yascheduler_nodes` row is never auto-removed by this change — even across daemon restarts or transient SSH outages
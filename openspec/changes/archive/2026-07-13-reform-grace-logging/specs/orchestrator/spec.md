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
orchestrator SHALL emit a `trace("CONNECT_RETRY_STATIC", ...)` DEBUG record
(test target) plus a separate `warning(...)` narrative record (user target)
and return early BEFORE the grace-check — so static nodes retry indefinitely
on every producer cycle, never accumulate entries in the failure timer, and
NEVER reach the `abandon_node` use case. A transient SSH outage (e.g. after a
daemon restart) must not silently delete an operator's node row.

For cloud nodes (`cloud is not None`):

- If `age < connect_grace`, the orchestrator SHALL emit a `trace("CONNECT_RETRY", ...)`
  DEBUG record plus a separate narrative record and return; the next producer
  cycle re-yields the node (retry behavior unchanged).
- If `age >= connect_grace`, the orchestrator SHALL emit a
  `trace("CONNECT_ABANDON", ...)` DEBUG record plus a separate narrative record,
  call the `abandon_node` use case with the node, the cloud provisioner, the
  UoW factory, and the allocation tracker, then pop the `node_id` from the
  failure timer. The `abandon_node` use case deletes the cloud VM, removes the
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
- **THEN** if elapsed failure age < `connect_grace`, the orchestrator emits a `trace("CONNECT_RETRY", ...)` DEBUG record plus a narrative record and returns (retry next cycle); if age >= `connect_grace`, the orchestrator emits a `trace("CONNECT_ABANDON", ...)` DEBUG record plus a narrative record, calls `abandon_node` (which discards the tracker entry by node via `discard_by_node`), and pops the `node_id` from the failure timer

#### Scenario: Static node connection failure emits trace plus narrative and retries indefinitely

- **GIVEN** a static node (`cloud is None`) raises `MachineConnectionError`
- **WHEN** the connect-machine producer handles the failure
- **THEN** a `trace("CONNECT_RETRY_STATIC", ...)` DEBUG record is emitted (test target)
- **AND** a separate `warning(...)` narrative record is emitted (user target)
- **AND** the orchestrator returns early BEFORE the grace-check
- **AND** the node is never added to the failure timer and never reaches `abandon_node`

#### Scenario: Successful connect resets the failure timer

- **WHEN** `repository.connect(node, client_keys, ...)` succeeds for a node that had a prior `MachineConnectionError`
- **THEN** the orchestrator pops the `node_id` from the failure timer

#### Scenario: Connect reads jump identity from Node

- **WHEN** the orchestrator calls `repository.connect(node, client_keys, connect_timeout=10, data_dir=..., engines_dir=..., tasks_dir=...)` for a node with `jump_host="bastion.example.com"`
- **THEN** no inline resolution loop runs (no iteration over `config.clouds`, no read of `config.remote.jump_host`), and the tunnel leg is built from `node.jump_host` / `node.jump_username` / `node.jump_port` inside the repository

### Requirement: Stats logging

The system SHALL periodically log queue sizes, node counts, and task counts
at a configurable interval using `repository.list_connected()`. When the
stats background job raises a non-`CancelledError` exception, the orchestrator
SHALL emit a `trace("ERROR", ...)` DEBUG record carrying the stats context
(test target) plus a separate `error(...)` narrative record (user target),
and continue on the next tick.

#### Scenario: Stats tolerates empty or partial count mappings
- **WHEN** the stats logger reads `nodes.count_by_status()` and the mapping lacks the `True` key
- **THEN** it SHALL use `Mapping.get(key, 0)` and SHALL NOT raise `KeyError`

#### Scenario: Stats error splits into trace plus narrative
- **GIVEN** the stats background job raises a non-`CancelledError` exception
- **WHEN** the error is logged
- **THEN** a `trace("ERROR", ...)` DEBUG record carrying the stats context is emitted (test target)
- **AND** a separate `error(...)` narrative record is emitted (user target)
- **AND** the stats job continues on the next tick

### Requirement: Producer error resilience

The orchestrator SHALL catch non-`CancelledError` exceptions raised by
producer and consumer coroutines. For a consumer exception, the orchestrator
SHALL emit a `trace("CONSUMER_ERROR", ...)` DEBUG record (test target) plus a
separate `error(...)` narrative record (user target), log the error, and
continue the loop on the next tick. For a producer exception, the orchestrator
SHALL emit a `trace("PRODUCER_ERROR", ...)` DEBUG record (test target) plus a
separate `error(...)` narrative record (user target), log the error, and
continue the loop on the next tick. A transient failure in a producer's
dependency (DB query, repository read) SHALL NOT silently kill the subsystem
for the daemon's lifetime. A consumer exception SHALL NOT silently kill the
worker `asyncio.Task` — the queue item is still dequeued via
`finally: queue.item_done(msg)` and the worker continues.

`CancelledError` (a `BaseException`) SHALL propagate past the `except
Exception` clauses to the graceful-shutdown drain path. Workers SHALL be
registered in a background-jobs registry so `stop()`'s cancel cascade reaches
them even if the parent coroutine exits via a `BaseException` that `except
Exception` does not catch. Cancelling an already-cancelled worker SHALL be
a no-op.

The stats background job SHALL catch non-`CancelledError`
exceptions from its reads, log, and continue on its next tick.

#### Scenario: Transient producer error does not kill the loop
- **WHEN** a producer coroutine raises an `Exception` (e.g. DB timeout)
- **THEN** the orchestrator emits a `trace("PRODUCER_ERROR", ...)` DEBUG record plus an `error(...)` narrative record, and the loop continues on the next tick

#### Scenario: Transient consumer error does not kill the worker
- **WHEN** the consumer callable raises an `Exception` while processing a queue message
- **THEN** the orchestrator emits a `trace("CONSUMER_ERROR", ...)` DEBUG record plus an `error(...)` narrative record, the queue item is dequeued, and the worker continues

#### Scenario: CancelledError preserves graceful shutdown
- **WHEN** the producer or consumer receives `asyncio.CancelledError` during shutdown
- **THEN** `CancelledError` propagates past `except Exception` to the graceful-drain path

### Requirement: Orchestrator.stop is idempotent and exception-safe

`Orchestrator.stop()` SHALL be idempotent via a boolean guard
initialized to `False` in `__init__`, checked and set with no `await` between
them. If the guard is already `True`, `stop()` returns immediately.

`stop()` SHALL be exception-safe: each cleanup step (`clouds.stop()`,
`repository.disconnect_all()`, `http_session.close()`) SHALL be wrapped in
its own `try/except Exception` so a failure in one step does not skip the
remaining steps. A cleanup-step failure SHALL be logged as a plain
`warning(...)` narrative record (user target) with no grace block marker and
no accompanying `trace(...)` DEBUG double, because these cleanup warnings are
not test-targeted. The `http_session` SHALL be set to `None` after close.
Background jobs that died with a non-`CancelledError` exception before
shutdown SHALL be caught and logged without aborting the cleanup chain.

#### Scenario: stop() runs cleanup body exactly once
- **WHEN** `orch.stop()` is called twice
- **THEN** the cleanup body executes exactly once; the second invocation returns immediately

#### Scenario: failing cleanup step does not skip remaining steps
- **WHEN** `await clouds.stop()` raises an `Exception` during `orch.stop()`
- **THEN** the failure is logged as a plain `warning(...)` narrative record (no grace block marker, no trace double), and `stop()` proceeds to `repository.disconnect_all()` and `http_session.close()`
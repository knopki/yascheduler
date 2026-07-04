## MODIFIED Requirements

### Requirement: Orchestrator manages producer-consumer loops

The system SHALL provide an `Orchestrator` class that runs 4 producer-consumer
loops. The `Orchestrator` SHALL accept `uow_factory: Callable[[],
AbstractUnitOfWork]`, `repository: MachineRepository` and `operations:
MachineOperations` (Protocol types for all code paths), `clouds: CloudProvisioner` (Protocol type), `allocation_tracker:
AllocationTracker`, `active_clouds: Sequence[CloudConfig]` (domain Protocol
type), and `allocation_lock: asyncio.Lock`. The orchestrator SHALL own the
tracker, the filtered cloud config list, and the lock — constructing them once
and injecting them into use cases.

The `Orchestrator` SHALL NOT import `AllSSHRetryExc` or `backoff` from
`yascheduler.infra` at runtime. The `Orchestrator` SHALL NOT apply
`@backoff.on_exception` decorators — all retry logic SHALL live in the
adapter.

The `Orchestrator` SHALL type `self._repository` as `MachineRepository` and
`self._operations` as `MachineOperations` (Protocols). The orchestrator's
`_start_task_on_machine` SHALL be a thin wrapper that resolves `ncpus` via
`uow.nodes.get_by_id(task.allocated_node_id)` (falling back to
`operations.get_cpu_cores(session)` when the node is absent) and delegates
the actual upload + spawn to `operations.start_task_on_machine(session, ...)`.
The orchestrator SHALL NOT contain any reference to adapter-specific methods
(`get_sftp`, `get_path`, `get_quote`, `run_full`).

The orchestrator SHALL NOT read `self._clouds.configs` — the filtered
`active_clouds` list is injected at construction. The orchestrator SHALL
NOT hold `adapters` or `configs` dicts — provider selection is delegated
to the `clouds.select_provider` port method.

The `Orchestrator.__init__` SHALL NOT accept a `config: Config` parameter.
The `Config` aggregate lives in `yascheduler.entrypoints` and SHALL NOT be
imported by `yascheduler.application`. The orchestrator SHALL accept
`local_settings: LocalSettings` and `remote_defaults: RemoteDefaults` (both
from `yascheduler.domain`) and store them as `self._local_settings` and
`self._remote_defaults`. The `list_private_keys_fn: Callable[[Path],
Sequence[PurePath]]` callable (introduced in P1) SHALL be retained. The
orchestrator SHALL NOT hold an `self._config` reference.

#### Scenario: Orchestrator starts all loops

- **WHEN** `await orchestrator.start()` is called
- **THEN** all 4 loops begin executing concurrently, using `uow_factory` for all persistence queries, `repository` for all SSH collection operations, and `operations` for all per-machine SSH operations

#### Scenario: Graceful shutdown

- **WHEN** `await orchestrator.stop()` is called
- **THEN** all loops receive cancellation, pending queue items are drained, and connections are closed via `repository.disconnect_all()`

#### Scenario: No adapter imports at runtime

- **WHEN** `orchestrator.py` is imported
- **THEN** it does NOT import `AllSSHRetryExc`, `SFTPRetryExc`, or `backoff` from `yascheduler.infra` at runtime (TYPE_CHECKING imports are allowed)

#### Scenario: Task deployment delegated to operations resolves session by allocated_node_id

- **WHEN** the orchestrator allocates a task to a machine
- **THEN** the orchestrator resolves a `session` via `repository.get_session(task.allocated_node_id)`, resolves `ncpus` via `uow.nodes.get_by_id(task.allocated_node_id)` (falling back to `operations.get_cpu_cores(session)` when the node is absent), and calls `operations.start_task_on_machine(session, engine, task, ncpus, self._remote_defaults.engines_dir)` — never touches `get_sftp`, `get_path`, or `get_quote` directly, never keys a session lookup by `ip`

#### Scenario: Orchestrator does not import Config

- **WHEN** `orchestrator.py` is inspected for `Config` imports
- **THEN** no `from yascheduler.entrypoints import Config` or `from yascheduler.entrypoints.config import Config` import appears (TYPE_CHECKING or runtime); the orchestrator imports `LocalSettings` and `RemoteDefaults` from `yascheduler.domain` under TYPE_CHECKING

#### Scenario: Orchestrator constructed with unpacked settings

- **WHEN** `Orchestrator(...)` is constructed by the composition root
- **THEN** the call passes `local_settings=` and `remote_defaults=` keyword arguments (instances of `LocalSettings` and `RemoteDefaults`), not a `Config` aggregate; the `list_private_keys_fn` callable is passed as before; `repository=` and `operations=` are passed as separate keyword arguments (not a single `gateway=`)

### Requirement: Consume loop

The system SHALL poll RUNNING tasks via UoW and dispatch to the `consume_task`
use case when the remote machine reports completion. Queue messages SHALL
carry domain `Task` objects. Per-machine SSH operations SHALL use
`MachineOperations` with a `session` resolved via
`repository.get_session(task.allocated_node_id)`.

The orchestrator SHALL maintain an in-process `set[TaskId]` of in-flight consume
task ids (`self._consuming`). The consume producer SHALL skip yielding a task
whose id is in `self._consuming`. The consume consumer SHALL add the task id to
`self._consuming` before awaiting `consume_task` and remove it in a `finally`
block so a failed consume does not permanently block re-yield.

The orchestrator SHALL maintain an in-process `set[NodeId]` of node_ids whose
occupancy check has been started (`self._occupancy_started`). On the first
consumer tick for a task, the orchestrator SHALL add `task.allocated_node_id`
to `_occupancy_started` and call `operations.start_occupancy_check(session,
engine)`. On finalised consume, the orchestrator SHALL discard the node_id
from `_occupancy_started`.

#### Scenario: Consume task in-flight guard

- **WHEN** the consume producer is about to yield a task whose id is in `self._consuming`
- **THEN** the producer skips it and moves to the next RUNNING task

#### Scenario: Consume task id removed after completion

- **WHEN** `consume_task` returns (either `True` or `False`)
- **THEN** the consumer's `finally` block removes the task id from `self._consuming`, allowing a future producer cycle to yield the task again if it is still RUNNING

#### Scenario: Session resolved by allocated_node_id

- **WHEN** `_task_consumer_consumer` runs for a task with `allocated_node_id=NodeId(7)`
- **THEN** it calls `self._repository.get_session(NodeId(7))` once at the top; if `None`, the `MACHINE_GONE` path runs; if a session is returned, it is threaded through the consumer body

#### Scenario: occupancy_started keyed by NodeId

- **WHEN** `_task_consumer_consumer` starts an occupancy check for a task with `allocated_node_id=NodeId(7)`
- **THEN** `NodeId(7)` is added to `self._occupancy_started`; on finalised consume, `NodeId(7)` is discarded

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned nodes via `MachineRepository` and `CloudProvisioner`. The
`_deallocator_consumer` SHALL call
`deallocate_node(node, repository, clouds, uow_factory)` directly with the
`Node` taken from `msg.payload` — it SHALL NOT open a UoW to read the node
via `uow.nodes.get(ip)` (the `Node` is already carried in the queue message,
eliminating the round-trip lookup). `deallocate_node` performs SSH
disconnect + disable + cloud delete + remove in two short UoWs bracketing
the pure cloud call. The orchestrator SHALL use `repository.list_connected()`
instead of `gateway.items()` for iterating connected machines.

The `_deallocate_q` queue SHALL be typed `UniqueQueue[NodeId, Node]`
(was `UniqueQueue[str, str]`). The producer SHALL yield
`UMessage(node.node_id, node)` for each `Node` returned by `deallocate_nodes`
— the message id is `node.node_id` (a `NodeId`, strictly unique `SERIAL PK`),
the payload is the `Node`. This rekeys the dedup from `ip` (non-unique post
migration 003 — duplicate IPs are valid behind different jump hosts) to
`NodeId` (strictly unique), so two distinct nodes sharing an IP are both
processed rather than one being silently dropped.

The `_deallocator_producer` SHALL build `idle_machines: dict[NodeId, float]`
(was `dict[str, float]` keyed by ip) by iterating
`repository.list_connected()` and keying each FREE session by
`session.machine.node_id` (was `session.machine.ip`). The `free_since`
monotonic timestamp is the value. This dict is passed to `deallocate_nodes`,
which matches it against `node.node_id` (was `node.ip`).

The `_deallocator_consumer` SHALL NOT perform its own SSH
`elif self._repository.contains(node_id): await self._repository.disconnect(node_id)`
fallback. SSH teardown is owned by `deallocate_node` (which calls
`repository.contains(node.node_id)` + `repository.disconnect(node.node_id)`
internally before the `if node.cloud:` guard). The consumer SHALL wrap
`deallocate_node` in a `try/except Exception` that logs `node_id`, `ip`, and
the error and continues (the worker-resilience wrapper in
`_create_producer_consumers` already catches consumer exceptions, but the
deallocator consumer keeps its own explicit error log with `node_id`/`ip`
fields for correlation, matching the prior behavior).

#### Scenario: Cloud node idle too long

- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB via `uow.nodes.disable(node.node_id)` and returns the `Node` (carrying `node_id`) for SSH cleanup and cloud deletion

#### Scenario: Deallocator uses list_connected and keys idle_machines by NodeId

- **WHEN** `_deallocator_producer` iterates connected machines to build `idle_machines`
- **THEN** it uses `repository.list_connected()` and accesses `session.machine.node_id` (and `session.machine.free_since`) directly; the resulting `idle_machines` is `dict[NodeId, float]`

#### Scenario: Deallocator queue is keyed on NodeId

- **WHEN** `_deallocator_producer` enqueues disabled nodes
- **THEN** it yields `UMessage(node.node_id, node)` where `node.node_id` is a `NodeId` (the queue dedup key) and `node` is the full `Node` (the payload); the queue is `UniqueQueue[NodeId, Node]`

#### Scenario: Deallocator consumer takes Node from payload without DB lookup

- **WHEN** `_deallocator_consumer` processes a disabled node message
- **THEN** it takes `node = msg.payload` directly and calls `deallocate_node(node, self._repository, self._clouds, self._uow_factory)` — it SHALL NOT call `uow.nodes.get(ip)` to reconstruct the `Node`; the `Node` is already carried in the message

#### Scenario: Deallocator consumer does not duplicate SSH teardown

- **WHEN** `_deallocator_consumer` processes a node
- **THEN** it SHALL NOT call `self._repository.contains(node.node_id)` or `self._repository.disconnect(node.node_id)` directly; SSH teardown is owned by `deallocate_node`'s internal `repository.contains(node.node_id)` + `repository.disconnect(node.node_id)` calls (which run before the `if node.cloud:` guard)

#### Scenario: Deallocator consumer logs node_id and ip on error

- **WHEN** `deallocate_node(node, ...)` raises an `Exception` inside `_deallocator_consumer`
- **THEN** the consumer's `except Exception` block logs `node_id=%s ip=%s err=%s` and the worker continues processing subsequent messages

### Requirement: Connect machine loop

The system SHALL poll enabled nodes from `NodeRepository` via UoW and establish
SSH connections via `MachineRepository`. Connection failures SHALL be caught as
`MachineConnectionError` (domain exception), not `asyncssh.misc.Error`.

The orchestrator SHALL maintain a per-node connect-failure timer
(`dict[NodeId, float]` mapping `node_id` to the monotonic timestamp of the
first consecutive failure) in memory. On a successful
`repository.connect(node, ...)` for a node, the orchestrator SHALL pop that
node's `node_id` from the failure timer. For cloud-provisioned nodes, on
`MachineConnectionError`, the orchestrator SHALL compare the elapsed monotonic
age against the node's cloud `connect_grace` (looked up from
`self._config_clouds` by `prefix == node.cloud`).

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
  `yascheduler_nodes` row, and discards the stuck task's entry from
  `AllocationTracker` so the task re-allocates on the next cycle.

The failure timer SHALL NOT be persisted across daemon restarts (in-memory
only). A restart resets the grace window for any node that was mid-failure.

For nodes whose `node.cloud` is a non-None value that does not match any
`CloudConfig.prefix` in `self._config_clouds`, the orchestrator SHALL fall
back to a conservative default `connect_grace` of 120 seconds (matches the
slowest cloud default) so the abandon path still fires for misconfigured or
unknown clouds. This fallback does NOT apply to `cloud is None` (static
nodes), which are handled before the grace-check and never reach the abandon
path.

#### Scenario: New node connected

- **WHEN** a new enabled node appears in the database
- **THEN** an SSH connection is established via `repository.connect(node, ...)` and the session is registered under `node.node_id`

#### Scenario: Connection failure caught as domain error

- **WHEN** `repository.connect(node, ...)` fails
- **THEN** the orchestrator catches `MachineConnectionError` and logs the error

#### Scenario: Connection failure within grace retries

- **WHEN** `repository.connect(node, ...)` raises `MachineConnectionError` for a node whose elapsed failure age is less than the node's cloud `connect_grace`
- **THEN** the orchestrator logs the failure and returns without calling `abandon_node`; the `node_id` remains in the failure timer and the next producer cycle re-yields the node

#### Scenario: Connection failure past grace triggers abandon

- **WHEN** `repository.connect(node, ...)` raises `MachineConnectionError` for a node whose elapsed failure age is greater than or equal to the node's cloud `connect_grace`
- **THEN** the orchestrator calls `abandon_node(node, clouds, uow_factory, tracker)`, pops the `node_id` from the failure timer, and the node is no longer yielded by subsequent producer cycles (its DB row is removed)

#### Scenario: Successful connect resets the failure timer

- **WHEN** `repository.connect(node, ...)` succeeds for a node that had a prior `MachineConnectionError` recorded in the failure timer
- **THEN** the orchestrator pops the `node_id` from the failure timer and subsequent failures for that node start a fresh grace window

#### Scenario: Unknown cloud falls back to conservative grace

- **WHEN** `repository.connect(node, ...)` raises `MachineConnectionError` for a node whose `cloud` is a non-None value that does not match any `CloudConfig.prefix` in `self._config_clouds`
- **THEN** the orchestrator uses a `connect_grace` of 120 seconds for the age comparison

#### Scenario: Daemon restart resets failure timers

- **WHEN** the daemon restarts with a node that was mid-failure (age had accumulated toward `connect_grace`)
- **THEN** the in-memory failure timer is empty on start and the node's next `MachineConnectionError` starts a fresh grace window

### Requirement: Free-machine selection gated on DB-enabled nodes

The `allocate_task` use case SHALL only consider a machine allocatable
when its `node_id` is enabled in `yascheduler_nodes`. The
`_find_free_machines` helper SHALL read `uow.nodes.list_enabled()` in the
same Unit of Work it opens for `uow.tasks.list_by_status({RUNNING})`,
build `nodes_by_id = {n.node_id: n for n in enabled_nodes}`, and filter
`MachineRepository.list_free(platforms)` down to sessions whose
`machine.node_id` is in `nodes_by_id` AND not in the busy-node node_ids
derived from RUNNING tasks (`busy_node_ids = {t.allocated_node_id for t
in running_tasks if t.allocated_node_id}`).

This restores the invariant that a machine is allocatable ONLY after its
DB row is `enabled=TRUE`. The DB row is flipped from `enabled=FALSE`
(the tmp-node inserted by `_select_and_insert_tmp` during provider
selection) to `enabled=TRUE` by `allocate_task`'s persist step after
`clouds.allocate` returns successfully — i.e. only after `_setup_vm` has
completed cloud-init, engine setup, and CPU detection. The persist step
is a single `uow.nodes.update(node)` (the cloud adapter returns a `Node`
carrying `tmp_node_id` as its `node_id`; UPDATE flips enabled, sets
ip/ncpus).

The gate SHALL live in the use case, not in `MachineRepository`. The
`MachineRepository` Protocol (an infrastructure-layer SSH collection port)
SHALL NOT be coupled to `NodeRepository` (a persistence port). Joining the
two data sources is the use case's responsibility.

A side effect of this gate: a node that was disabled in DB but not yet
disconnected (the window between `deallocate_nodes.disable` and
`repository.disconnect`) also has a `FREE` session in the repository. The
previous filter (RUNNING tasks only) would let it through; the new gate
excludes it because its `node_id` is no longer in `nodes_by_id` (it's not
enabled). This closes a second, latent registry-vs-DB desync window.

#### Scenario: Setup-in-flight tmp-node is invisible to the allocator

- **WHEN** `CloudProvisionerImpl._setup_vm` has called `machine_repository.connect(node)` registering a `FREE` session under `tmp_node_id`, but `clouds.allocate` has not yet returned and `allocate_task`'s persist step has not yet set the DB row to `enabled=TRUE`
- **THEN** `_find_free_machines` excludes that session because `tmp_node_id not in nodes_by_id` (the row is `enabled=FALSE`, so `list_enabled()` does not return it), so no task is dispatched to the not-yet-setup node

#### Scenario: Multiple allocator workers do not pile onto the same setup-in-flight node

- **WHEN** two allocator workers run `_find_free_machines` concurrently while one setup-in-flight session is registered (DB row `enabled=FALSE`)
- **THEN** both workers exclude that session from `free_sessions`, neither attempts `_try_start_on_machine` on it, and no `MachineBusyError` pile-on occurs

#### Scenario: Enabled node is allocatable after setup completes

- **WHEN** `clouds.allocate` returned successfully and `allocate_task`'s persist step (`uow.nodes.update(node)`) flipped the DB row to `enabled=TRUE`
- **THEN** on the next allocator tick `_find_free_machines` includes the session in `free_sessions` because its `node_id` is now in `nodes_by_id`

#### Scenario: Disabled-but-not-disconnected node is excluded

- **WHEN** a node's DB row was set to `enabled=FALSE` by `deallocate_nodes` but its SSH session has not yet been removed from `MachineRepository._sessions` (still `FREE`)
- **THEN** `_find_free_machines` excludes that session because its `node_id` is no longer in `nodes_by_id`, so no task is dispatched to a node being deallocated

#### Scenario: Gate lives in the use case, not the repository

- **WHEN** `MachineRepository.list_free` is inspected for any reference to `NodeRepository`, `list_enabled`, or persistence imports
- **THEN** none are present; the repository returns FREE sessions filtered only by platform, and the enabled-node_id intersection is applied by `_find_free_machines` in the application layer

#### Scenario: Dup-IP nodes are disambiguated by node_id

- **WHEN** two enabled nodes share the same `ip` (dup-IP configuration behind different jump hosts) with distinct `node_id`s (`NodeId(1)` and `NodeId(2)`), and a free session exists for each
- **THEN** `nodes_by_id = {NodeId(1): node_1, NodeId(2): node_2}` (no collapse); each session is paired with its own `Node` via `s.machine.node_id`; both pairs are returned in `free_sessions` (the prior `nodes_by_ip` collapse that dropped one of the duplicates is resolved)
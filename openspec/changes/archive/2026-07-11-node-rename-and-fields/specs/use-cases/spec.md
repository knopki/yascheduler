## MODIFIED Requirements

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`,
`config_clouds: Sequence[CloudConfig]`, and `idle_machines: dict[NodeId, float]`
(`NodeId` -> free_since monotonic timestamp). It SHALL NOT accept `repository`
or `operations` (the per-node SSH/cloud teardown lives in `deallocate_node`).

The per-node wrapper `deallocate_node(node, repository, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(node)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `hostname`).
`clouds.deallocate(node)` SHALL take the whole `Node` and read `node.cloud`
(provider) and `node.hostname` (cloud host) internally. `deallocate_node` SHALL
call `repository.contains(node.node_id)` and `repository.disconnect(node.node_id)`
BEFORE the `if node.cloud:` guard, so SSH teardown is owned by
`deallocate_node` and runs regardless of whether the node is a cloud node.

`deallocate_nodes` SHALL iterate the enabled nodes returned by
`uow.nodes.list_enabled()` and call `uow.nodes.disable(node.node_id)` for
each node whose `node_id` is in `idle_machines` and whose `node_id` is not
in `busy_node_ids` (the node_ids of RUNNING tasks' `allocated_node_id`).

`deallocate_nodes` SHALL return `list[Node]`. Phase 2
(collect free disabled cloud nodes) SHALL return the `Node` objects it
reads from `uow.nodes.list_disabled()`, each carrying `node_id`.

`deallocate_nodes` phase 2 SHALL filter disabled nodes by
`node.node_id not in busy_node_ids and node.cloud`.

Internal log lines in both `deallocate_nodes` and `deallocate_node` SHALL
include both `node_id` and `hostname` for correlation.

#### Scenario: Idle cloud node disabled
- **WHEN** `deallocate_nodes(...)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` is included in the returned `list[Node]`

#### Scenario: Returns disabled Node objects carrying node_id
- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned; each `Node` carries its `node_id`, so the orchestrator can call `deallocate_node(node, ...)` directly without a DB round-trip

#### Scenario: Deallocate node brackets cloud delete with disable+remove
- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** SSH disconnect runs first, then `uow.nodes.disable` + commit, then `clouds.deallocate(node)`, then `uow.nodes.remove` + commit

### Requirement: AbandonNode use case

The system SHALL provide an `abandon_node` async function that cleans up a
cloud node that never established its SSH connection, releasing the originating
task to re-allocate on the next cycle. The function SHALL accept `node: Node`,
`clouds: CloudProvisioner` (Protocol type), `uow_factory: Callable[[],
AbstractUnitOfWork]`, and `tracker: AllocationTracker`. It SHALL NOT import
from `yascheduler.infra` at runtime (TYPE_CHECKING only).

The use case SHALL NOT call `repository.disconnect` — by construction the
node was never registered in the repository (that is why it is being
abandoned). The use case SHALL:

1. If `node.cloud` is non-None, call `clouds.deallocate(node)`
   as a best-effort cloud VM deletion. Failure here SHALL be logged at
   `error` level with `node_id`, `hostname`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.tasks.list_by_status({TaskStatus.TO_DO})`, and
   in-memory filter for the task whose `allocated_node_id == node.node_id`.
   This read SHALL happen BEFORE the node-row removal in step 3 — the
   `allocated_node_id` FK is `ON DELETE SET NULL`, so removing the node row
   first would null `allocated_node_id` and the in-memory filter would no
   longer match. Hold the matching task(s) in memory.
3. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `hostname`, and the exception and
   re-raised.
4. If exactly one matching task was found in step 2, call
   `tracker.discard(task.task_id)`. If zero or multiple matched, no `discard`
   is called.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `hostname` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released
- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node with one matching TO_DO task
- **THEN** `clouds.deallocate(node)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard(task.task_id)` is called, and the function returns without raising

#### Scenario: Cloud deletion failure does not block DB cleanup
- **WHEN** `clouds.deallocate(node)` raises an exception
- **THEN** the exception is logged, `uow.nodes.remove(node.node_id)` is still called and committed, and the function continues to the stuck-task lookup

#### Scenario: No matching TO_DO task skips tracker discard
- **WHEN** the stuck-task lookup finds zero TO_DO tasks with `allocated_node_id == node.node_id`
- **THEN** `tracker.discard` is NOT called, the function returns without raising, and the VM deletion + DB removal still ran
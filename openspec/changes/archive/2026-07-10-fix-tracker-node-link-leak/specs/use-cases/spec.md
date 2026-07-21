## MODIFIED Requirements

### Requirement: AllocateTask use case

The system SHALL provide an `allocate_task` async function that matches a
TO_DO task to a free machine or requests cloud provisioning. The function SHALL
accept `task_id: TaskId`, `uow_factory`, `repository: MachineRepository`
(Protocol type), `occupancy_checker: OccupancyChecker` (concrete collaborator
type), `clouds: CloudProvisioner` (Protocol type), `tracker: AllocationTracker`,
and `allocation_lock: asyncio.Lock`. It SHALL NOT import from
`yascheduler.infra` at runtime. It SHALL NOT accept `adapters` or `configs`
parameters — provider selection is delegated to the `clouds.select_provider`
port method.

The orchestrator reads task ids from `list_by_status -> [Task]` (each carrying
`TaskId`) and feeds `allocate_task(task_id=task.task_id, ...)`, so `TaskId`
flows end-to-end internally with no conversion. `tracker.add`/`discard(task_id)`
keys are `TaskId` (the tracker's internal `dict` becomes
`dict[TaskId, NodeId | None]`).

For the cloud-fallback path, the use case SHALL own the full flow:
tracker dedup (via `tracker.add(task_id)` with `node_id=None`, before any DB
write so the dedup gate precedes tmp-node insertion), capacity check, provider
selection (via `clouds.select_provider` port method returning `str | None`),
tmp-node insertion via `uow.nodes.insert` (NOT `add_tmp`), node-link patching
(via `tracker.set_node(task_id, tmp_node.node_id)` after the tmp node is
inserted), cloud allocation (via `clouds.allocate(selection, node)` returning a
`Node` reusing the tmp node's `node_id`), final node persistence via
`uow.nodes.update(node)` (a single UPDATE flipping `enabled=TRUE` and setting
`ip`/`ncpus`), and tmp-node cleanup on failure (`uow.nodes.remove(tmp_node_id)`).
The `allocation_lock` SHALL serialize the capacity-read + select + tmp-insert
sequence so two concurrent `allocate_task` calls for the same engine cannot
both provision a cloud node when only one slot is free. The `tracker.add` dedup
gate SHALL run outside the lock and before any DB write; `tracker.set_node`
SHALL run after `_select_and_insert_tmp` returns (outside the lock, since the
lock is released inside `_select_and_insert_tmp` before its caller receives the
result) — there is no `await` between `set_node` and the surrounding code, so
the `None` window for the entry's node link is a single synchronous step with
no concurrency surface.

The function SHALL read `task.engine` when matching the task against engines.
The use case SHALL reject an unsupported engine via
`task.reject("unsupported engine")` (a single atomic transition that emits
`TaskFailed` inline — no separate `with_event` call, no duplicated reason
string). The use case SHALL compute `remote_folder` from `task.task_id` and
transition the task via `task.run(node.node_id, remote_folder)` (a single
atomic transition that sets `allocated_node_id` + `remote_folder`, moves to
RUNNING, and emits `TaskAllocated` inline). No `TaskContext` indirection.

#### Scenario: Successful allocation to a free machine
- **WHEN** `allocate_task(...)` is called and a free compatible machine exists
- **THEN** the use case computes `remote_folder` from `task.task_id`, calls `task.run(node.node_id, remote_folder)` (transitioning TO_DO→RUNNING and emitting `TaskAllocated` inline), starts the occupancy check, saves, commits, and the function returns True

#### Scenario: No free machine matches, cloud-fallback attempted
- **WHEN** `allocate_task(...)` is called and no free machine matches
- **THEN** the cloud-fallback path is attempted (tracker dedup with `node_id=None`, capacity check, provider selection, tmp-node insert, `tracker.set_node` linking the task to the tmp node, cloud allocation, final persist); returns False if no provider available

#### Scenario: Duplicate allocation rejected by tracker
- **WHEN** `allocate_task` is called for a `task_id` already in `AllocationTracker`
- **THEN** `tracker.add(task_id)` returns False and the cloud-fallback path returns immediately without inserting a tmp node or writing to the DB

#### Scenario: Unsupported engine
- **WHEN** `allocate_task(...)` is called and the task's engine is not in `EngineRepository`
- **THEN** the use case calls `task.reject("unsupported engine")` (emitting `TaskFailed` inline), saves, commits, and the function returns False

#### Scenario: Occupancy check started via occupancy_checker

- **WHEN** `allocate_task(...)` successfully starts a task on a machine
- **THEN** `occupancy_checker.start_occupancy_check(session, engine)` is called

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
   `error` level with `node_id`, `ip`, `cloud`, and the exception, and SHALL NOT
   suppress the subsequent DB-row removal.
2. Open a UoW, call `uow.nodes.remove(node.node_id)`, and commit. Failure here
   SHALL be logged at `error` level with `node_id`, `ip`, and the exception and
   re-raised.
3. Call `tracker.discard_by_node(node.node_id)`. If the returned count is
   greater than 1, a warning SHALL be logged at `warning` level with
   `node_id`, `ip`, and the count (signals tracker corruption — under normal
   operation exactly one tracker entry links to the node). The discard SHALL
   run even if the count is zero (no-op) or greater than one (all matching
   entries removed).

The use case SHALL NOT read `uow.tasks` or filter TO_DO tasks by
`allocated_node_id` — the cloud-provisioning path never binds the task to the
node (the task stays TO_DO with `allocated_node_id = None` throughout cloud
provisioning), so such a lookup is structurally empty. The `discard_by_node`
mechanism uses the tracker's task-to-node link (established by
`allocate_task`'s `set_node` call) instead.

The use case SHALL NOT mark the task `FAILED` or emit a domain event — the
task re-enters `allocate_task` on the next cycle. The use case SHALL NOT
modify `node.enabled` or call `uow.nodes.disable` — the row is removed
directly.

Internal log lines SHALL include both `node_id` and `ip` for correlation.

#### Scenario: Happy path — VM deleted, DB row removed, tracker released
- **WHEN** `abandon_node(node, clouds, uow_factory, tracker)` is called for a cloud node whose `node_id` is linked to one tracker entry
- **THEN** `clouds.deallocate(node)` is called, `uow.nodes.remove(node.node_id)` is called and committed, `tracker.discard_by_node(node.node_id)` is called and returns 1, and the function returns without raising

#### Scenario: Cloud deletion failure does not block DB cleanup
- **WHEN** `clouds.deallocate(node)` raises an exception
- **THEN** the exception is logged, `uow.nodes.remove(node.node_id)` is still called and committed, and the function continues to `tracker.discard_by_node`

#### Scenario: No tracker entry for the node is a no-op discard
- **WHEN** `tracker.discard_by_node(node.node_id)` returns 0 (no tracker entry links to this node)
- **THEN** no warning is logged, the function returns without raising, and the VM deletion + DB removal still ran

#### Scenario: Multiple tracker entries for one node logs a warning
- **WHEN** `tracker.discard_by_node(node.node_id)` returns a count greater than 1 (signals tracker corruption)
- **THEN** a warning is logged with `node_id`, `ip`, and the count, all matching entries are removed, and the function returns without raising

### Requirement: AllocationTracker tracks in-flight cloud allocations

The system SHALL provide an `AllocationTracker` class that maintains an
in-memory `dict[TaskId, NodeId | None]` of task_ids with in-flight cloud
allocations, mapping each tracked task to its provisioning tmp node (or
`None` between the dedup gate and the tmp-node insert).
The class SHALL expose:

- `add(task_id: TaskId, node_id: NodeId | None = None) -> bool` — returns
  True if newly added, False if already tracked. The optional `node_id`
  parameter defaults to `None` so the dedup gate can call `add(task_id)`
  before the tmp node exists.
- `set_node(task_id: TaskId, node_id: NodeId) -> None` — patches the node
  link into an existing entry. If the `task_id` is not tracked, the call
  SHALL be a no-op (defensive — the entry is added by `add` and removed by
  `discard`; `set_node` only runs on the success path between them).
- `discard(task_id: TaskId) -> None` — removes the entry by `task_id`
  (unchanged semantics; the `NodeId | None` value is discarded with it).
- `discard_by_node(node_id: NodeId) -> int` — removes ALL entries whose
  linked node matches `node_id` and returns the count removed. Returns 0 if
  no entry links to the node (no-op).
- `__contains__(task_id: TaskId) -> bool` — unchanged.

The tracker SHALL be constructed once by the orchestrator and injected into
the `allocate_task`, `consume_task`, and `abandon_node` use cases. It is
internal to the orchestrator and never crosses the public `Yascheduler`
facade boundary.

#### Scenario: AllocationTracker is a dict[TaskId, NodeId|None] deduplication helper
- **WHEN** `tracker.add(TaskId(42))` is called for an untracked task_id
- **THEN** returns True and `TaskId(42)` is in `tracker`; a second `add(TaskId(42))` returns False; `discard(TaskId(42))` removes it; `discard` of an untracked id is a no-op

#### Scenario: set_node patches the node link into an existing entry
- **WHEN** `tracker.add(TaskId(42))` is called (returning True), then `tracker.set_node(TaskId(42), NodeId(7))` is called
- **THEN** `tracker.discard_by_node(NodeId(7))` returns 1 and `TaskId(42)` is no longer in `tracker`

#### Scenario: set_node on an untracked task is a no-op
- **WHEN** `tracker.set_node(TaskId(99), NodeId(7))` is called for a task_id that was never added
- **THEN** `tracker.discard_by_node(NodeId(7))` returns 0 and `TaskId(99)` is not in `tracker`

#### Scenario: discard_by_node removes the matching entry and returns the count
- **WHEN** `tracker.add(TaskId(1), NodeId(5))` and `tracker.add(TaskId(2), NodeId(6))` are called, then `tracker.discard_by_node(NodeId(5))` is called
- **THEN** returns 1, `TaskId(1)` is no longer in `tracker`, and `TaskId(2)` is still in `tracker`

#### Scenario: discard_by_node with no matching entry returns 0
- **WHEN** `tracker.discard_by_node(NodeId(99))` is called on a tracker with entries for other nodes
- **THEN** returns 0 and no entries are removed

#### Scenario: discard_by_node removes multiple entries for the same node
- **WHEN** two entries link to the same `NodeId(5)` (corruption state), then `tracker.discard_by_node(NodeId(5))` is called
- **THEN** returns 2 and both entries are removed (defensive — all matching entries cleaned)
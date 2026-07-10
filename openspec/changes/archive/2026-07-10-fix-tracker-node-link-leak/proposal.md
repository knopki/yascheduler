## Why

The `AllocationTracker` keeps an entry for a cloud-provisioned task
intentionally (to dedup re-provisioning while the VM boots), but when the
cloud node never connects and is abandoned via `abandon_node`, the entry is
never discarded: `abandon_node`'s stuck-task lookup filters TO_DO tasks by
`allocated_node_id == node.node_id`, yet the cloud-provisioning path never
binds the task to the node (`task.run()` is only called on the free-machine
path). The lookup is structurally always empty — dead code in production.
The leaked entry blocks the cloud path for that `task_id` until daemon
restart: `tracker.add(task_id)` returns `False` on every subsequent cycle.
Pure-cloud deployments with a flaky SSH-up phase accumulate stuck tasks.

## What Changes

- `AllocationTracker` internal shape changes from `set[TaskId]` to
  `dict[TaskId, NodeId | None]`, storing the link from the in-flight
  provisioning task to its tmp node.
- `AllocationTracker.add(task_id, node_id=None) -> bool` keeps the dedup
  semantics (returns `False` if already tracked) and accepts an optional
  `node_id` link (passed as `None` at the dedup gate, before the tmp node
  exists).
- `AllocationTracker.set_node(task_id, node_id) -> None` is added to patch
  the node link into an existing entry after the tmp node is inserted.
- `AllocationTracker.discard_by_node(node_id) -> int` is added to discard
  all entries whose linked node matches, returning the count removed (for
  a multi-match warning).
- `allocate_task` calls `tracker.set_node(task.task_id, tmp_node.node_id)`
  after `_select_and_insert_tmp` returns, preserving the existing
  `tracker.add(task.task_id)` position at the dedup gate (before any DB
  write).
- `abandon_node` replaces the dead TO_DO + `allocated_node_id` filter
  lookup with a single `tracker.discard_by_node(node.node_id)` call; the
  stuck-task DB read (`list_by_status({TO_DO})`) and the ambiguous-match
  warning block are removed.
- The existing `discard(task_id)` call sites
  (`allocate_task.py:150,521`, `consume_task.py:201,236`,
  `orchestrator.py:480`) are unchanged — the dict shape supports
  by-`task_id` removal without modification.

## Capabilities

### New Capabilities

<!-- None — this change modifies existing behavior, introduces no new capability. -->

### Modified Capabilities

- `use-cases`: the `AllocationTracker tracks in-flight cloud allocations`
  requirement changes shape from `set[TaskId]` to
  `dict[TaskId, NodeId | None]` and gains `set_node` / `discard_by_node`;
  the `AbandonNode` use case replaces the
  TO_DO + `allocated_node_id` stuck-task lookup with
  `tracker.discard_by_node(node.node_id)`.
- `orchestrator`: the connect-abandon flow description changes from
  "discards the stuck task's entry" (via the dead by-task lookup) to
  discarding by node via `tracker.discard_by_node(node.node_id)`.

## Impact

- **Code**: `yascheduler/application/allocation_tracker.py` (shape +
  new methods), `yascheduler/application/allocate_task.py` (one new
  `set_node` call after tmp-node insert), `yascheduler/application/abandon_node.py`
  (replace lookup block with `discard_by_node`).
- **Tests**: `tests/unit/test_allocation_tracker.py` (shape + new
  methods), `tests/unit/test_abandon_node.py` (lookup-based scenarios
  rewritten for `discard_by_node`), `tests/integration/test_never_connected_node_abandon.py`
  (the dropped tracker-release assertion is restored — the leak is now
  fixed).
- **No DB migration** — the tracker is in-memory.
- **No domain entity or port change** — the tracker is an application
  service, not a domain entity; `Task.allocated_node_id` semantics are
  unchanged (still `None` for TO_DO tasks throughout cloud provisioning).
- **Public API**: no change — `AllocationTracker` is internal to the
  orchestrator and never crosses the `Yascheduler` facade boundary.
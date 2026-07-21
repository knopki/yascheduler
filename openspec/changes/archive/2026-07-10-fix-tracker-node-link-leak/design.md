## Context

`AllocationTracker` is an in-memory service that dedups in-flight cloud
provisioning: when `allocate_task` enters the cloud path, it calls
`tracker.add(task_id)`, which returns `False` if the task is already being
provisioned. The entry is intentionally kept on success (the VM is booting,
the task is still TO_DO) so a re-allocate cycle doesn't double-provision.

The entry must be discarded when the task reaches a terminal path. The
free-machine path discards via `allocate_task.py:150` (when the task re-
allocates to any free machine — the now-connected cloud node or a static
node). The cloud-path failure discards via `allocate_task.py:521` (the
`finally` block). `consume_task` discards on finalise and on task-not-found.
The orchestrator discards on RunningTask abandon.

The gap: when the cloud node **never connects** (SSH never comes up), the
node is abandoned via `abandon_node` after the `connect_grace` timeout, but
`abandon_node`'s stuck-task lookup (`list_by_status({TO_DO})` filtered by
`allocated_node_id == node.node_id`) is structurally empty — the cloud path
never calls `task.run()`, so `allocated_node_id` stays `None` throughout
provisioning. The lookup is dead code. The leaked entry blocks the cloud
path for that `task_id` until daemon restart.

This is documented in the codebase: `tests/integration/test_never_connected_node_abandon.py:228-237`
explicitly notes the dead code and drops the tracker-release assertion.

## Goals / Non-Goals

**Goals:**

- Close the tracker-entry leak for never-connected cloud nodes.
- Preserve the dedup-before-DB-write invariant (the dedup gate at
  `allocate_task.py:489` runs before `_select_and_insert_tmp` inserts any
  tmp-node row).
- Preserve all existing `discard(task_id)` call sites unchanged.
- No domain entity change (`Task.allocated_node_id` semantics unchanged).
- No DB migration (tracker is in-memory).

**Non-Goals:**

- TTL/sweep of tracker entries (not needed once `discard_by_node` closes the
  steady-state leak).
- Fixing the redundant `consume_task.py:201` discard (harmless — the entry
  is already discarded by `:150` before consume runs; left as-is).
- Changing `Task.allocated_node_id` to be set during cloud provisioning
  (rejected — see Decision D2).
- Reordering `tracker.add` to after `_select_and_insert_tmp` (rejected — see
  Decision D1).

## Decisions

### D1: Tracker shape — `dict[TaskId, NodeId | None]` with `add` + `set_node`

**Choice**: `set[TaskId]` → `dict[TaskId, NodeId | None]`. `add(task_id,
node_id=None)` keeps its current position (line 489, outside the lock, before
any DB write). `set_node(task_id, node_id)` patches the node link after
`_select_and_insert_tmp` returns.

**Why over reorder (`dict[TaskId, NodeId]`, move `add` after tmp insert)**:
moving `add` after `_select_and_insert_tmp` breaks the dedup-before-DB-write
invariant. On a race (two concurrent `allocate_task` for the same
`task_id`), both racers insert a tmp-node under the lock (sequentially),
then the second racer's `add` returns `False` and it must clean up its
orphaned tmp-node — an extra insert+remove round-trip per race. With `add`
in its current position, the second racer returns `False` before touching
the DB. The `None` window for the entry's node link is a single synchronous
step (no `await` between `_select_and_insert_tmp` and `set_node`), so there
is no concurrency surface; the `finally: discard` cleans any half-linked
entry on exception.

**Why over parallel structures (`set[TaskId]` + `dict[NodeId, TaskId]`)**:
two data structures for one fact. `discard(task_id)` would need to scan the
reverse map (O(n)) to keep them in sync. A single `dict` supports both
lookups without synchronization overhead.

**Why over domain (`Task.allocated_node_id` set during provisioning)**:
see D2.

### D2: Link in the tracker, not in the domain

**Choice**: the task-to-node link lives in the in-memory tracker, not in
`Task.allocated_node_id`.

**Why not set `allocated_node_id` during provisioning**: this would make the
dead lookup in `abandon_node` work (the filter `allocated_node_id ==
node.node_id` would match), but introduces three problems:

1. **Double-allocation risk**: the free-machine path runs before the cloud
   path and does not check the tracker. A TO_DO task with
   `allocated_node_id` set (bound to a tmp node) could be `run()` on a free
   machine while the cloud VM is still booting — `task.run()` overwrites
   `allocated_node_id` and the task goes RUNNING on the free machine, but
   the cloud VM for the tmp node comes up as an orphan. Today this can't
   happen because TO_DO tasks have `allocated_node_id = None` and the
   tracker blocks re-provisioning.

2. **New domain transitions**: `Task` has no `bind_node()` (TO_DO→TO_DO)
   or `unbind_node()` method. Adding two domain transitions that exist only
   for this use case, plus a `save`+`commit` on every failure path, is
   disproportionate.

3. **Domain invariant change**: the current spec
   (`domain-entities/spec.md:93`) states "allocated_node_id is None for
   unallocated tasks (TO_DO with no node bound)". Setting it during
   provisioning breaks this invariant and ripples through
   `domain-entities`, `use-cases`, and possibly `postgres-persistence`.

The tracker is an application service, not a domain entity — adding a link
there is semantically smaller and has no blast radius beyond the tracker
itself.

### D3: `abandon_node` discards by node, not by task lookup

**Choice**: replace the dead `list_by_status({TO_DO})` + `allocated_node_id`
filter + conditional `tracker.discard(matching[0].task_id)` with a single
`tracker.discard_by_node(node.node_id)`.

**Rationale**: the task-to-node link is now in the tracker (Decision D1), so
`abandon_node` can discard by node directly. The DB read (`list_by_status`)
and the ambiguous-match warning block are removed — the tracker handles the
ambiguous case by discarding all matching entries and returning the count.

**Multi-match warning**: if `discard_by_node` returns a count > 1, a warning
is logged. Under normal operation this is always 1 (node_id is a DB primary
key, one tracker entry per provisioning task). The warning signals tracker
corruption if it ever fires — defense-in-depth at zero cost on the happy
path.

### D4: `set_node` is a no-op on untracked task

**Choice**: `set_node(task_id, node_id)` for a task_id not in the tracker is
a silent no-op (not a raise).

**Rationale**: `set_node` only runs on the success path between `add` (line
489) and `discard` (line 526 `finally`). A call on an untracked task_id
would indicate a logic bug in the caller, but raising would turn a tracker
inconsistency into an allocation failure. The defensive no-op keeps the
tracker self-healing; the missing link just means `discard_by_node` won't
find the entry (and the `finally: discard(task_id)` still cleans it).

## Risks / Trade-offs

- **`None` window in the dict value** → The entry's node link is `None`
  between `add` and `set_node`. This window is a single synchronous step
  (no `await`), so no concurrent code observes it. If an exception escapes
  before `set_node`, the `finally: discard(task_id)` removes the half-linked
  entry. No leak, no incorrect `discard_by_node` behavior.

- **`set_node` silently no-ops on untracked task** → If a caller bug causes
  `set_node` to run on a task_id that was never added (or already
  discarded), the link is lost. `discard_by_node` won't find the entry, but
  `discard(task_id)` in the `finally` still cleans it by task_id. The leak
  is self-healing on the next allocation cycle (the task re-allocates, the
  old entry was discarded by task_id). Acceptable for an in-memory service.

- **`discard_by_node` removing multiple entries** → Under normal operation
  this never happens (one entry per node). If it does (corruption), all
  matching entries are removed — defensive. The warning logs the anomaly.
  No data is lost (the tasks re-allocate on the next cycle).

- **No persistence across restart** → The tracker is in-memory. A daemon
  restart loses all entries. This is the existing behavior — a restarted
  daemon re-allocates from scratch, and the cloud path can re-provision. Not
  a regression; the leak fix doesn't change restart semantics.

- **`discard_by_node` skipped if `uow.nodes.remove` raises** → The new
  `abandon_node` ordering (step 2: remove + commit, step 3:
  `discard_by_node`) means if `uow.nodes.remove` raises and re-raises, the
  tracker entry is NOT discarded. The orchestrator catches the exception
  (`orchestrator.py:349`) and pops the node from the failure timer (line
  357), so the node is not retried for abandon — the entry stays until daemon
  restart. This matches the current behavior (the current code also discards
  AFTER the remove block, so a remove failure skips the discard). Not a
  regression, but worth documenting: the leak is closed for the
  never-connected-node path (the common case), not for the
  DB-remove-failure edge case. Putting `discard_by_node` in a `finally` was
  considered but rejected — if the node row wasn't removed, the node still
  exists in the DB, and discarding the tracker entry would let the task
  re-provision onto a different node while the abandoned node row lingers.
  The current ordering is correct: remove first, then discard.
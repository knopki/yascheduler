"""In-memory dedup of in-flight cloud allocations by task_id, with a task-to-node link for discard-by-node on abandon."""
# FILE: yascheduler/application/allocation_tracker.py
# VERSION: 2.0.0
# START_MODULE_CONTRACT
#   PURPOSE: In-memory dedup of in-flight cloud allocations by task_id, with a task-to-node link for discard-by-node on abandon.
#   SCOPE: AllocationTracker class — in-memory dict[TaskId, NodeId | None] tracking in-flight cloud allocations and their provisioning tmp node, constructed once by orchestrator.
#   DEPENDS: none
#   LINKS: M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AllocationTracker - In-memory dict[TaskId, NodeId | None] tracking in-flight cloud allocations with a task-to-node link
#   add - Add a task_id with an optional node_id link; returns True if newly added, False if already tracked
#   set_node - Patch the node link into an existing tracker entry; no-op if the task_id is not tracked
#   discard - Remove a tracker entry by task_id; no-op if not present
#   discard_by_node - Remove all tracker entries linked to the given node_id and return the count removed
#   __contains__ - Membership check by task_id
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Shape set[TaskId] -> dict[TaskId, NodeId | None]; add gains optional node_id (default None, preserves existing call sites); new set_node patches the node link after tmp-node insert; new discard_by_node removes entries by node_id and returns the count (for abandon_node's multi-match warning). discard/__contains__ key on the dict.
#   PREVIOUS_CHANGE: v1.1.0 - AllocationTracker tracks set[TaskId]; add/discard/__contains__ take task_id: TaskId.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import NodeId, TaskId


# START_CONTRACT: AllocationTracker
#   PURPOSE: Track task_ids (TaskId) with in-flight cloud allocations to prevent duplicate provisioning, mapping each tracked task to its provisioning tmp node (or None between the dedup gate and the tmp-node insert).
#   INPUTS: { None - constructor takes no args; methods take task_id: TaskId and, for set_node/discard_by_node, node_id: NodeId }
#   OUTPUTS: { AllocationTracker instance }
#   SIDE_EFFECTS: None — in-memory only.
#   LINKS: M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-ABANDON-NODE
# END_CONTRACT: AllocationTracker
class AllocationTracker:
    """In-memory dedup of in-flight cloud allocations.

    Constructed once by the orchestrator and injected into allocate_task
    (calls add/set_node), consume_task (calls discard), and abandon_node
    (calls discard_by_node).
    """

    def __init__(self) -> None:
        self._entries: dict[TaskId, NodeId | None] = {}

    def add(self, task_id: TaskId, node_id: NodeId | None = None) -> bool:
        """Return True if newly added, False if already tracked.

        The optional node_id defaults to None so the dedup gate can call
        add(task_id) before the tmp node exists; set_node patches the link
        once the tmp node is inserted.
        """
        if task_id in self._entries:
            return False
        self._entries[task_id] = node_id
        return True

    # START_CONTRACT: set_node
    #   PURPOSE: Patch the node link into an existing tracker entry.
    #   INPUTS: { task_id: TaskId, node_id: NodeId }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None — in-memory only. No-op if task_id is not tracked.
    #   LINKS: M-APPLICATION-ALLOCATE
    # END_CONTRACT: set_node
    def set_node(self, task_id: TaskId, node_id: NodeId) -> None:
        """Patch the node link into an existing tracker entry."""
        if task_id in self._entries:
            self._entries[task_id] = node_id

    def discard(self, task_id: TaskId) -> None:
        """Remove a tracker entry by ``task_id`` (no-op if absent)."""
        self._entries.pop(task_id, None)

    # START_CONTRACT: discard_by_node
    #   PURPOSE: Remove all tracker entries linked to the given node and return the count removed.
    #   INPUTS: { node_id: NodeId }
    #   OUTPUTS: { int - count of entries removed }
    #   SIDE_EFFECTS: None — in-memory only.
    #   LINKS: M-APPLICATION-ABANDON-NODE
    # END_CONTRACT: discard_by_node
    def discard_by_node(self, node_id: NodeId) -> int:
        """Remove all tracker entries linked to the given node and return the count removed."""
        matching = [tid for tid, nid in self._entries.items() if nid == node_id]
        for tid in matching:
            self._entries.pop(tid, None)
        return len(matching)

    def __contains__(self, task_id: TaskId) -> bool:
        return task_id in self._entries

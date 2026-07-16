"""In-memory dedup of in-flight cloud allocations by task_id, with a task-to-node link for discard-by-node on abandon."""
# region MODULE_CONTRACT
# PURPOSE: Prevent the daemon from provisioning duplicate cloud VMs for the same task while providing an abandon path to discard entries linked to a specific node.
# SCOPE: AllocationTracker class for cloud allocation dedup.
# INVARIANTS: In-memory only — daemon restart resets state; entries dict is the sole source of truth.
# KEYWORDS: allocation tracker, dedup, in-flight, cloud, task_id, node_id
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import NodeId, TaskId

__all__ = ["AllocationTracker"]


# region CLASS_AllocationTracker
# PURPOSE: Prevent the daemon from provisioning duplicate cloud VMs for the same task, with a task-to-node link so abandon can discard by node.
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

    # region METHOD_set_node
    # PURPOSE: Bridge the allocation gap where the tmp node is created after the tracker slot, so abandon can trace which tasks are tied to that node and discard them.
    def set_node(self, task_id: TaskId, node_id: NodeId) -> None:
        """Patch the node link into an existing tracker entry."""
        if task_id in self._entries:
            self._entries[task_id] = node_id

    # endregion METHOD_set_node

    def discard(self, task_id: TaskId) -> None:
        """Remove a tracker entry by ``task_id`` (no-op if absent)."""
        self._entries.pop(task_id, None)

    # region METHOD_discard_by_node
    # PURPOSE: Release all in-flight allocation slots associated with a failed node so the tracker does not accumulate stale entries and future tasks are not falsely deduped.
    def discard_by_node(self, node_id: NodeId) -> int:
        """Remove all tracker entries linked to the given node and return the count removed."""
        matching = [tid for tid, nid in self._entries.items() if nid == node_id]
        for tid in matching:
            self._entries.pop(tid, None)
        return len(matching)

    # endregion METHOD_discard_by_node

    def __contains__(self, task_id: TaskId) -> bool:
        return task_id in self._entries


# endregion CLASS_AllocationTracker

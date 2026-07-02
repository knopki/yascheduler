# FILE: yascheduler/application/allocation_tracker.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: In-memory dedup of in-flight cloud allocations by task_id.
#   SCOPE: AllocationTracker class — constructed once by orchestrator, injected into allocate_task and consume_task use cases.
#   DEPENDS: none
#   LINKS: M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AllocationTracker - In-memory set[TaskId] tracking task_ids with in-flight cloud allocations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - AllocationTracker tracks set[TaskId] (was set[int]); add/discard/__contains__ take task_id: TaskId (add-task-id-identity). The tracker is internal to the orchestrator and never crosses the public Yascheduler facade boundary. Added `from __future__ import annotations` + TYPE_CHECKING import of TaskId.
#   PREVIOUS_CHANGE: v1.0.0 - Extract on_tasks set + mark_task_done from CloudProvisionerImpl (cloud-provisioner-pure).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import TaskId


# START_CONTRACT: AllocationTracker
#   PURPOSE: Track task_ids (TaskId) with in-flight cloud allocations to prevent duplicate provisioning.
#   INPUTS: { None - constructor takes no args }
#   OUTPUTS: { AllocationTracker instance }
#   SIDE_EFFECTS: None — in-memory only.
#   LINKS: M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME
# END_CONTRACT: AllocationTracker
class AllocationTracker:
    """In-memory dedup of in-flight cloud allocations.

    Constructed once by the orchestrator and injected into allocate_task
    (calls add) and consume_task (calls discard).
    """

    def __init__(self) -> None:
        self._on_tasks: set[TaskId] = set()

    # START_CONTRACT: AllocationTracker.add
    #   PURPOSE: Record a task as having an in-flight cloud allocation.
    #   INPUTS: { task_id: TaskId }
    #   OUTPUTS: { bool - True if newly added, False if already tracked }
    #   SIDE_EFFECTS: Mutates internal set.
    #   LINKS: M-APPLICATION-ALLOCATE
    # END_CONTRACT: AllocationTracker.add
    def add(self, task_id: TaskId) -> bool:
        """Returns True if newly added, False if already tracked."""
        if task_id in self._on_tasks:
            return False
        self._on_tasks.add(task_id)
        return True

    # START_CONTRACT: AllocationTracker.discard
    #   PURPOSE: Release an in-flight allocation slot (no-op if not tracked).
    #   INPUTS: { task_id: TaskId }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Mutates internal set (idempotent).
    #   LINKS: M-APPLICATION-CONSUME, M-APPLICATION-ALLOCATE
    # END_CONTRACT: AllocationTracker.discard
    def discard(self, task_id: TaskId) -> None:
        self._on_tasks.discard(task_id)

    def __contains__(self, task_id: TaskId) -> bool:
        return task_id in self._on_tasks

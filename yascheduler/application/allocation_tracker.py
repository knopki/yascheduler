# FILE: yascheduler/application/allocation_tracker.py
# VERSION: 1.1.0
# START_MODULE_CONTRACT
#   PURPOSE: In-memory dedup of in-flight cloud allocations by task_id.
#   SCOPE: AllocationTracker class — in-memory set[TaskId] tracking in-flight cloud allocations, constructed once by orchestrator.
#   DEPENDS: none
#   LINKS: M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AllocationTracker - In-memory set[TaskId] tracking task_ids with in-flight cloud allocations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - AllocationTracker tracks set[TaskId]; add/discard/__contains__ take task_id: TaskId.
#   PREVIOUS_CHANGE: v1.0.0 - Extract on_tasks set + mark_task_done from CloudProvisionerImpl.
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

    def add(self, task_id: TaskId) -> bool:
        """Returns True if newly added, False if already tracked."""
        if task_id in self._on_tasks:
            return False
        self._on_tasks.add(task_id)
        return True

    def discard(self, task_id: TaskId) -> None:
        self._on_tasks.discard(task_id)

    def __contains__(self, task_id: TaskId) -> bool:
        return task_id in self._on_tasks

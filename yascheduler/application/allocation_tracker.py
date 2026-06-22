# FILE: yascheduler/application/allocation_tracker.py
# VERSION: 1.0.0
# START_MODULE_CONTRACT
#   PURPOSE: In-memory dedup of in-flight cloud allocations by task_id.
#   SCOPE: AllocationTracker class — constructed once by orchestrator, injected into allocate_task and consume_task use cases.
#   DEPENDS: none
#   LINKS: M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   AllocationTracker - In-memory set tracking task_ids with in-flight cloud allocations
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract on_tasks set + mark_task_done from CloudProvisionerImpl (cloud-provisioner-pure).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY


# START_CONTRACT: AllocationTracker
#   PURPOSE: Track task_ids with in-flight cloud allocations to prevent duplicate provisioning.
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
        self._on_tasks: set[int] = set()

    # START_CONTRACT: AllocationTracker.add
    #   PURPOSE: Record a task as having an in-flight cloud allocation.
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { bool - True if newly added, False if already tracked }
    #   SIDE_EFFECTS: Mutates internal set.
    #   LINKS: M-APPLICATION-ALLOCATE
    # END_CONTRACT: AllocationTracker.add
    def add(self, task_id: int) -> bool:
        """Returns True if newly added, False if already tracked."""
        if task_id in self._on_tasks:
            return False
        self._on_tasks.add(task_id)
        return True

    # START_CONTRACT: AllocationTracker.discard
    #   PURPOSE: Release an in-flight allocation slot (no-op if not tracked).
    #   INPUTS: { task_id: int }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: Mutates internal set (idempotent).
    #   LINKS: M-APPLICATION-CONSUME, M-APPLICATION-ALLOCATE
    # END_CONTRACT: AllocationTracker.discard
    def discard(self, task_id: int) -> None:
        self._on_tasks.discard(task_id)

    def __contains__(self, task_id: int) -> bool:
        return task_id in self._on_tasks

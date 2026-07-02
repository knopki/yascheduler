# FILE: tests/unit/test_allocation_tracker.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for AllocationTracker — in-flight cloud allocation dedup.
#   SCOPE: AllocationTracker add/discard/__contains__ behavior.
#   DEPENDS: M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAllocationTracker - Tests for add (new/duplicate), discard (tracked/untracked), __contains__
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial test suite for AllocationTracker (cloud-provisioner-pure).
#   PREVIOUS_CHANGE: none
# END_CHANGE_SUMMARY

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.domain.model import TaskId


class TestAllocationTracker:
    def test_add_new_task_returns_true(self) -> None:
        """Spec: Add new task to tracker — returns True and 42 is in tracker."""
        tracker = AllocationTracker()
        assert tracker.add(TaskId(42)) is True
        assert TaskId(42) in tracker

    def test_add_duplicate_task_returns_false(self) -> None:
        """Spec: Add duplicate — returns False, set unchanged."""
        tracker = AllocationTracker()
        assert tracker.add(TaskId(42)) is True
        assert tracker.add(TaskId(42)) is False
        assert TaskId(42) in tracker

    def test_discard_tracked_task_removes_it(self) -> None:
        """Spec: Discard tracked task — 42 no longer in tracker."""
        tracker = AllocationTracker()
        tracker.add(TaskId(42))
        tracker.discard(TaskId(42))
        assert TaskId(42) not in tracker

    def test_discard_untracked_task_is_noop(self) -> None:
        """Spec: Discard untracked — no error raised, set unchanged."""
        tracker = AllocationTracker()
        tracker.add(TaskId(42))
        # Discarding an untracked task should not raise
        tracker.discard(TaskId(99))
        assert TaskId(42) in tracker
        assert TaskId(99) not in tracker

    def test_containment_check(self) -> None:
        """Spec: 42 in tracker returns True if tracked, False otherwise."""
        tracker = AllocationTracker()
        assert TaskId(42) not in tracker
        tracker.add(TaskId(42))
        assert TaskId(42) in tracker

    def test_multiple_tasks_tracked_independently(self) -> None:
        """Bonus: multiple task_ids coexist."""
        tracker = AllocationTracker()
        assert tracker.add(TaskId(1)) is True
        assert tracker.add(TaskId(2)) is True
        assert tracker.add(TaskId(3)) is True
        assert TaskId(1) in tracker
        assert TaskId(2) in tracker
        assert TaskId(3) in tracker
        # Discarding one doesn't affect others
        tracker.discard(TaskId(2))
        assert TaskId(1) in tracker
        assert TaskId(2) not in tracker
        assert TaskId(3) in tracker

    def test_readd_after_discard_returns_true(self) -> None:
        """Bonus: a task can be re-added after discard."""
        tracker = AllocationTracker()
        tracker.add(TaskId(42))
        tracker.discard(TaskId(42))
        # Re-adding should succeed
        assert tracker.add(TaskId(42)) is True
        assert TaskId(42) in tracker

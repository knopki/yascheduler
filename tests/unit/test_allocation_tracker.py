# FILE: tests/unit/test_allocation_tracker.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for AllocationTracker — in-flight cloud allocation dedup with a task-to-node link.
#   SCOPE: AllocationTracker add/set_node/discard/discard_by_node/__contains__ behavior.
#   DEPENDS: M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ALLOCATION-TRACKER
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAllocationTracker - Tests for add (new/duplicate/with node_id), set_node (tracked/untracked), discard (tracked/untracked), discard_by_node (single/multiple/none), __contains__
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Cover set_node (tracked/untracked) and discard_by_node (single/multiple/none) for the task-to-node link; add with node_id form.
#   PREVIOUS_CHANGE: v1.0.0 - Initial test suite for AllocationTracker (cloud-provisioner-pure).
# END_CHANGE_SUMMARY

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.domain.model import NodeId, TaskId


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

    def test_set_node_patches_link_into_existing_entry(self) -> None:
        """Spec: add(TaskId(42)) then set_node(TaskId(42), NodeId(7)) -> discard_by_node(NodeId(7)) returns 1, 42 gone."""
        tracker = AllocationTracker()
        tracker.add(TaskId(42))
        tracker.set_node(TaskId(42), NodeId(7))
        assert tracker.discard_by_node(NodeId(7)) == 1
        assert TaskId(42) not in tracker

    def test_set_node_on_untracked_task_is_noop(self) -> None:
        """Spec: set_node on a task_id never added -> discard_by_node(NodeId(7)) returns 0, 99 not in tracker."""
        tracker = AllocationTracker()
        tracker.set_node(TaskId(99), NodeId(7))
        assert tracker.discard_by_node(NodeId(7)) == 0
        assert TaskId(99) not in tracker

    def test_discard_by_node_removes_matching_entry_returns_count(self) -> None:
        """Spec: add(1, NodeId(5)) + add(2, NodeId(6)) -> discard_by_node(NodeId(5)) returns 1, 1 gone, 2 survives."""
        tracker = AllocationTracker()
        tracker.add(TaskId(1), NodeId(5))
        tracker.add(TaskId(2), NodeId(6))
        assert tracker.discard_by_node(NodeId(5)) == 1
        assert TaskId(1) not in tracker
        assert TaskId(2) in tracker

    def test_discard_by_node_no_matching_entry_returns_zero(self) -> None:
        """Spec: entries link to other nodes -> discard_by_node(NodeId(99)) returns 0, no removal."""
        tracker = AllocationTracker()
        tracker.add(TaskId(1), NodeId(5))
        tracker.add(TaskId(2), NodeId(6))
        assert tracker.discard_by_node(NodeId(99)) == 0
        assert TaskId(1) in tracker
        assert TaskId(2) in tracker

    def test_discard_by_node_removes_multiple_entries_for_same_node(self) -> None:
        """Spec: corruption case — two entries link to NodeId(5) -> discard_by_node returns 2, both removed."""
        tracker = AllocationTracker()
        tracker.add(TaskId(1), NodeId(5))
        tracker.add(TaskId(2), NodeId(5))
        assert tracker.discard_by_node(NodeId(5)) == 2
        assert TaskId(1) not in tracker
        assert TaskId(2) not in tracker

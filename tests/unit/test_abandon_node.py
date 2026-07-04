# FILE: tests/unit/test_abandon_node.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the abandon_node use case (never-connected cloud-node cleanup).
#   SCOPE: Happy path, non-cloud skip, cloud-delete failure tolerance, DB-remove failure re-raise, no-task no-op, ambiguous-task warning.
#   DEPENDS: M-APPLICATION-ABANDON-NODE, M-APPLICATION-UOW, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAbandonNode - Happy path, non-cloud skip, cloud-delete failure, DB-remove failure, no-task, ambiguous-task
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - node-id-keyed-mutators: uow.nodes.remove asserts expect NodeId(1) (was ip string "10.0.0.5").
#   PREVIOUS_CHANGE: v1.1.0 - add-node-id-identity: import NodeId, add node_id=NodeId(1) to _cloud_node Node(...) helper.
# END_CHANGE_SUMMARY
"""Unit tests for the abandon_node use case.

Covers all six scenarios from the use-cases spec:

- Happy path: VM deleted, DB row removed, tracker released
- Non-cloud node skips VM deletion
- Cloud deletion failure does not block DB cleanup
- DB remove failure is re-raised
- No matching TO_DO task → no discard
- Multiple matching TO_DO tasks → warning logged, no discard
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.abandon_node import abandon_node
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.domain.model import Node, NodeId, Task, TaskContext, TaskId, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.application.uow import AbstractUnitOfWork


def _cloud_node(ip: str = "10.0.0.5", cloud: str | None = "aws") -> Node:
    return Node(
        node_id=NodeId(1),
        ip=ip,
        ncpus=2,
        cloud=cloud,
        username="root",
        port=22,
        enabled=True,
    )


def _todo_task(
    task_id: int,
    allocated_ip: str = "10.0.0.5",
    allocated_node_id: NodeId | None = None,
) -> Task:
    return Task(
        task_id=TaskId(task_id),
        label="t",
        context=TaskContext(engine="e"),
        status=TaskStatus.TO_DO,
        allocated_ip=allocated_ip,
        allocated_node_id=allocated_node_id,
    )


def _build_uow(
    *,
    todo_tasks: list[Task] | None = None,
    remove_side_effect: Exception | None = None,
) -> AsyncMock:
    """Build a UoW mock whose tasks.list_by_status returns the given tasks.

    `remove_side_effect`, when set, makes uow.nodes.remove raise on first call.
    """
    uow = AsyncMock()
    uow.tasks = AsyncMock()
    uow.tasks.list_by_status = AsyncMock(return_value=todo_tasks or [])
    uow.nodes = AsyncMock()
    if remove_side_effect is not None:
        uow.nodes.remove = AsyncMock(side_effect=remove_side_effect)
    uow.commit = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return uow


def _uow_factory(uow: AsyncMock) -> Callable[[], AbstractUnitOfWork]:
    def _factory() -> AbstractUnitOfWork:
        return uow

    return _factory


class TestAbandonNode:
    """abandon_node — VM delete + DB remove + tracker discard."""

    @pytest.mark.asyncio
    async def test_happy_path_vm_deleted_row_removed_tracker_discarded(self) -> None:
        """cloud node + one matching TO_DO task → all three actions fire, no raise."""
        node = _cloud_node()
        task = _todo_task(42, allocated_ip="10.0.0.5", allocated_node_id=node.node_id)
        uow = _build_uow(todo_tasks=[task])

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)

        await abandon_node(
            node,
            clouds=clouds,
            uow_factory=_uow_factory(uow),
            tracker=tracker,
        )

        clouds.deallocate.assert_awaited_once_with("aws", "10.0.0.5")
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        uow.commit.assert_awaited_once()
        tracker.discard.assert_called_once_with(TaskId(42))

    @pytest.mark.asyncio
    async def test_abandon_node_non_cloud_skips_vm_deletion(self) -> None:
        """node.cloud is None → clouds.deallocate NOT called, DB remove still runs."""
        node = _cloud_node(cloud=None)
        uow = _build_uow(todo_tasks=[])

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)

        await abandon_node(
            node,
            clouds=clouds,
            uow_factory=_uow_factory(uow),
            tracker=tracker,
        )

        clouds.deallocate.assert_not_called()
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        uow.commit.assert_awaited_once()
        tracker.discard.assert_not_called()

    @pytest.mark.asyncio
    async def test_abandon_node_cloud_delete_failure_does_not_block_db_cleanup(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """clouds.deallocate raises → logged at error, DB remove still runs, no raise."""
        node = _cloud_node()
        uow = _build_uow(todo_tasks=[])

        clouds = AsyncMock()
        clouds.deallocate = AsyncMock(side_effect=RuntimeError("vm gone"))
        tracker = MagicMock(spec=AllocationTracker)

        with caplog.at_level(
            logging.ERROR, logger="yascheduler.application.abandon_node"
        ):
            # Must NOT raise — cloud delete failure is logged not raised.
            await abandon_node(
                node,
                clouds=clouds,
                uow_factory=_uow_factory(uow),
                tracker=tracker,
            )

        clouds.deallocate.assert_awaited_once_with("aws", "10.0.0.5")
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        uow.commit.assert_awaited_once()
        assert any(
            "CLOUD_DELETE_FAILED" in r.message
            and "10.0.0.5" in r.message
            and "aws" in r.message
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_abandon_node_db_remove_failure_reraised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """uow.nodes.remove raises → logged at error + re-raised (caller keeps worker alive)."""
        node = _cloud_node()
        uow = _build_uow(
            todo_tasks=[],
            remove_side_effect=RuntimeError("db gone"),
        )

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)

        with caplog.at_level(
            logging.ERROR, logger="yascheduler.application.abandon_node"
        ):
            with pytest.raises(RuntimeError, match="db gone"):
                await abandon_node(
                    node,
                    clouds=clouds,
                    uow_factory=_uow_factory(uow),
                    tracker=tracker,
                )

        clouds.deallocate.assert_awaited_once_with("aws", "10.0.0.5")
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        assert any(
            "REMOVE_FAILED" in r.message and "10.0.0.5" in r.message
            for r in caplog.records
        )
        # Tracker never reached (DB remove failed before the release-task block).
        tracker.discard.assert_not_called()

    @pytest.mark.asyncio
    async def test_abandon_node_no_matching_task_no_discard(self) -> None:
        """Zero TO_DO tasks with allocated_ip == node.ip → tracker.discard NOT called."""
        node = _cloud_node()
        # Unrelated task pointing at a different IP.
        unrelated = _todo_task(99, allocated_ip="10.0.0.99")
        uow = _build_uow(todo_tasks=[unrelated])

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)

        await abandon_node(
            node,
            clouds=clouds,
            uow_factory=_uow_factory(uow),
            tracker=tracker,
        )

        uow.tasks.list_by_status.assert_awaited_once_with({TaskStatus.TO_DO})
        tracker.discard.assert_not_called()

    @pytest.mark.asyncio
    async def test_abandon_node_multiple_matching_tasks_logs_warning_no_discard(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two TO_DO tasks with same allocated_ip → warning logged, no discard, no raise."""
        node = _cloud_node()
        t1 = _todo_task(101, allocated_ip="10.0.0.5", allocated_node_id=node.node_id)
        t2 = _todo_task(102, allocated_ip="10.0.0.5", allocated_node_id=node.node_id)
        uow = _build_uow(todo_tasks=[t1, t2])

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)

        with caplog.at_level(
            logging.WARNING, logger="yascheduler.application.abandon_node"
        ):
            await abandon_node(
                node,
                clouds=clouds,
                uow_factory=_uow_factory(uow),
                tracker=tracker,
            )

        tracker.discard.assert_not_called()
        assert any(
            "AMBIGUOUS_TASK" in r.message
            and "10.0.0.5" in r.message
            and "2" in r.message
            for r in caplog.records
        )

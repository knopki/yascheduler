# FILE: tests/unit/test_abandon_node.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for the abandon_node use case (never-connected cloud-node cleanup via discard_by_node).
#   SCOPE: Happy path, non-cloud node, cloud-delete failure tolerance, DB-remove failure re-raise, no-entry no-op, ambiguous-tracker warning.
#   DEPENDS: M-APPLICATION-ABANDON-NODE, M-APPLICATION-UOW, M-APPLICATION-ALLOCATION-TRACKER
#   LINKS: M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAbandonNode - Happy path, non-cloud, cloud-delete failure, DB-remove failure, no-entry no-op, ambiguous-tracker warning
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Rewrite for discard_by_node mechanism: drop _todo_task helper + uow.tasks.list_by_status setup (DB read removed); assert tracker.discard_by_node called with node.node_id; add no-entry (count=0) and ambiguous (count>1) scenarios.
#   PREVIOUS_CHANGE: v1.5.0 - drop-task-context-entity: update Task construction (flat fields, no TaskContext); remove TaskContext import.
# END_CHANGE_SUMMARY
"""Unit tests for the abandon_node use case.

Covers the six scenarios from the use-cases spec:

- Happy path: VM deleted, DB row removed, tracker entry discarded by node
- Non-cloud node skips VM deletion (discard_by_node still runs)
- Cloud deletion failure does not block DB cleanup
- DB remove failure is re-raised (discard_by_node skipped)
- No matching tracker entry -> no warning, no raise
- Multiple tracker entries for one node -> warning logged, no raise
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.abandon_node import abandon_node
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.domain.model import Node, NodeId

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


def _build_uow(*, remove_side_effect: Exception | None = None) -> AsyncMock:
    """Build a UoW mock. The DB read (list_by_status) is no longer used by
    abandon_node, so no tasks mock is set up.

    `remove_side_effect`, when set, makes uow.nodes.remove raise on first call.
    """
    uow = AsyncMock()
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
    """abandon_node — VM delete + DB remove + tracker discard_by_node."""

    @pytest.mark.asyncio
    async def test_happy_path_vm_deleted_row_removed_tracker_discarded(self) -> None:
        """cloud node + one tracker entry linked -> all three actions fire, discard_by_node returns 1, no raise."""
        node = _cloud_node()
        uow = _build_uow()

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)
        tracker.discard_by_node.return_value = 1

        await abandon_node(
            node,
            clouds=clouds,
            uow_factory=_uow_factory(uow),
            tracker=tracker,
        )

        clouds.deallocate.assert_awaited_once_with(node)
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        uow.commit.assert_awaited_once()
        tracker.discard_by_node.assert_called_once_with(node.node_id)

    @pytest.mark.asyncio
    async def test_abandon_node_non_cloud_skips_vm_deletion(self) -> None:
        """node.cloud is None -> clouds.deallocate NOT called, DB remove still runs, discard_by_node still runs (unconditional)."""
        node = _cloud_node(cloud=None)
        uow = _build_uow()

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)
        tracker.discard_by_node.return_value = 0

        await abandon_node(
            node,
            clouds=clouds,
            uow_factory=_uow_factory(uow),
            tracker=tracker,
        )

        clouds.deallocate.assert_not_called()
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        uow.commit.assert_awaited_once()
        tracker.discard_by_node.assert_called_once_with(node.node_id)

    @pytest.mark.asyncio
    async def test_abandon_node_cloud_delete_failure_does_not_block_db_cleanup(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """clouds.deallocate raises -> logged at error, DB remove still runs, discard_by_node still runs, no raise."""
        node = _cloud_node()
        uow = _build_uow()

        clouds = AsyncMock()
        clouds.deallocate = AsyncMock(side_effect=RuntimeError("vm gone"))
        tracker = MagicMock(spec=AllocationTracker)
        tracker.discard_by_node.return_value = 0

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

        clouds.deallocate.assert_awaited_once_with(node)
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        uow.commit.assert_awaited_once()
        tracker.discard_by_node.assert_called_once_with(node.node_id)
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
        """uow.nodes.remove raises -> logged at error + re-raised (caller keeps worker alive). discard_by_node is NOT called (discard runs after the remove; remove failure skips it)."""
        node = _cloud_node()
        uow = _build_uow(remove_side_effect=RuntimeError("db gone"))

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

        clouds.deallocate.assert_awaited_once_with(node)
        uow.nodes.remove.assert_awaited_once_with(NodeId(1))
        assert any(
            "REMOVE_FAILED" in r.message and "10.0.0.5" in r.message
            for r in caplog.records
        )
        # discard_by_node runs AFTER the remove block; a remove failure
        # re-raises before reaching it, so the tracker entry stays until
        # the next abandon attempt. Not a regression — matches the prior
        # ordering (the old code also discarded after the remove block).
        tracker.discard_by_node.assert_not_called()

    @pytest.mark.asyncio
    async def test_abandon_node_no_matching_tracker_entry_no_discard(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """discard_by_node returns 0 -> no warning logged, function returns without raising."""
        node = _cloud_node()
        uow = _build_uow()

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)
        tracker.discard_by_node.return_value = 0

        with caplog.at_level(
            logging.WARNING, logger="yascheduler.application.abandon_node"
        ):
            await abandon_node(
                node,
                clouds=clouds,
                uow_factory=_uow_factory(uow),
                tracker=tracker,
            )

        tracker.discard_by_node.assert_called_once_with(node.node_id)
        assert not any("AMBIGUOUS_TRACKER" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_abandon_node_multiple_tracker_entries_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """discard_by_node returns 2 (corruption) -> warning logged with AMBIGUOUS_TRACKER, node_id, ip, count=2, no raise."""
        node = _cloud_node()
        uow = _build_uow()

        clouds = AsyncMock()
        tracker = MagicMock(spec=AllocationTracker)
        tracker.discard_by_node.return_value = 2

        with caplog.at_level(
            logging.WARNING, logger="yascheduler.application.abandon_node"
        ):
            await abandon_node(
                node,
                clouds=clouds,
                uow_factory=_uow_factory(uow),
                tracker=tracker,
            )

        tracker.discard_by_node.assert_called_once_with(node.node_id)
        assert any(
            "AMBIGUOUS_TRACKER" in r.message
            and "10.0.0.5" in r.message
            and "count=2" in r.message
            for r in caplog.records
        )

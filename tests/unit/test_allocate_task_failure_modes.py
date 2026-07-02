# FILE: tests/unit/test_allocate_task_failure_modes.py
# VERSION: 1.5.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Failure-mode tests for allocate_task cloud-fallback hardening (outer try/finally with success-flag + step-3 VM-leak fix).
#   SCOPE: Step 1 commit failure, step 2 cleanup failure (best-effort logging), step 3 final persist failure (VM deallocate + tmp cleanup) —
#          all verify tracker.discard via outer finally, correct exception propagation, and no leaked VM/tmp-node.
#   DEPENDS: M-APPLICATION-ALLOCATE
#   LINKS: M-APPLICATION-ALLOCATE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestAllocateTaskFailureModes - allocate_task hardening: step1/step2-cleanup/step3 failures all release tracker entry; step3 also verifies best-effort VM+tmp cleanup
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: [v1.5.0 - remove-tmp-node-fake-ip: _make_uow sets uow.nodes.insert to return a tmp Node (NewNode(cloud=..., enabled=False) → Node with node_id); step2/step3 cleanup asserts remove(tmp_node_id) directly (no get lookup).]
#   PREVIOUS_CHANGE: [v1.4.1 - add-node-id-identity test update: prepend node_id=NodeId(1) to Node(...) construction and add NodeId import.]
# END_CHANGE_SUMMARY
#
"""Failure-mode tests for allocate_task cloud-fallback hardening.

Validates that the outer try/finally with success-flag correctly releases the
tracker entry on any unhandled exception (step 1 commit, step 2 cleanup, step
3 final persist) while preserving it on the success path.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.allocate_task import allocate_task
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.domain import Engine, EngineRepository
from yascheduler.domain.exceptions import CloudAllocateError
from yascheduler.domain.model import (
    Node,
    NodeId,
    Task,
    TaskContext,
    TaskId,
    TaskStatus,
)
from yascheduler.domain.ports import CloudProvisioner


def _make_uow(todo_task: Task) -> AsyncMock:
    uow = AsyncMock()
    uow.tasks = AsyncMock()
    uow.tasks.get = AsyncMock(return_value=todo_task)
    uow.tasks.list_by_status = AsyncMock(return_value=[])
    uow.nodes = AsyncMock()
    uow.nodes.list_all = AsyncMock(return_value=[])
    # remove-tmp-node-fake-ip: tmp-node insertion is insert(NewNode(cloud=...,
    # enabled=False)) → Node carrying the generated node_id (the cleanup handle).
    tmp_node = Node(node_id=NodeId(2), ip="", ncpus=0, enabled=False, cloud="aws")
    uow.nodes.insert = AsyncMock(return_value=tmp_node)
    uow.collect_events = AsyncMock(return_value=[])
    uow.publish_events = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return uow


def _make_clouds(
    selection: str, allocate_side_effect: object | None = None
) -> MagicMock:
    clouds = MagicMock(spec=CloudProvisioner)
    clouds.select_provider.return_value = selection
    clouds.allocate = (
        AsyncMock(side_effect=allocate_side_effect)
        if allocate_side_effect is not None
        else AsyncMock()
    )
    clouds.deallocate = AsyncMock()
    return clouds


class TestAllocateTaskFailureModes:
    """allocate_task hardening: all failure paths release the tracker entry via outer finally."""

    @pytest.fixture
    def todo_task(self) -> Task:
        return Task(
            task_id=TaskId(1),
            label="test",
            context=TaskContext(engine="test_engine"),
            status=TaskStatus.TO_DO,
        )

    @pytest.fixture
    def engine(self) -> Engine:
        return Engine(
            name="test_engine",
            spawn="echo {task_path}",
            check_cmd="echo ok",
            check_pname=None,
            input_files=("inp",),
            output_files=("OUTPUT",),
            platforms=("linux",),
        )

    async def test_step1_commit_failure_discards_tracker(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """Step 1 uow.commit() failure -> tracker.discard via outer finally, exception propagates. No tmp-node leaks in tracker."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[])
        operations = MagicMock()

        uow = _make_uow(todo_task)
        uow.commit = AsyncMock(side_effect=RuntimeError("db connection lost"))

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = True

        clouds = _make_clouds(
            "aws",
            allocate_side_effect=None,
        )

        with pytest.raises(RuntimeError, match="db connection lost"):
            await allocate_task(
                task_id=todo_task.task_id,
                engines=engines,
                uow_factory=lambda: uow,
                repository=repository,
                operations=operations,
                clouds=clouds,
                start_task_on_machine=AsyncMock(),
                tracker=tracker,
                allocation_lock=asyncio.Lock(),
            )

        tracker.discard.assert_called_once_with(todo_task.task_id)
        clouds.allocate.assert_not_called()

    async def test_step2_cleanup_failure_still_discards_tracker(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """Cloud allocate fails AND tmp-node cleanup also fails -> tracker.discard via outer finally, original CloudAllocateError propagates (not masked by cleanup error)."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[])
        operations = MagicMock()

        uow = _make_uow(todo_task)
        uow.nodes.remove = AsyncMock(side_effect=RuntimeError("cleanup db lost"))

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = True

        clouds = _make_clouds(
            "aws",
            allocate_side_effect=CloudAllocateError("VM create failed"),
        )

        with pytest.raises(CloudAllocateError, match="VM create failed"):
            await allocate_task(
                task_id=todo_task.task_id,
                engines=engines,
                uow_factory=lambda: uow,
                repository=repository,
                operations=operations,
                clouds=clouds,
                start_task_on_machine=AsyncMock(),
                tracker=tracker,
                allocation_lock=asyncio.Lock(),
            )

        # Original CloudAllocateError propagates, not the cleanup RuntimeError.
        tracker.discard.assert_called_once_with(todo_task.task_id)
        # cleanup called remove(tmp_node_id) directly (no get lookup); the
        # RuntimeError is swallowed by the best-effort wrapper.
        assert uow.nodes.remove.call_count >= 1
        uow.nodes.get.assert_not_called()

    async def test_step3_persist_failure_discards_tracker(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """Step 3 final persist commit failure -> tracker.discard via outer finally, exception propagates. VM is best-effort deallocated and tmp-node cleaned up so no billable orphan or capacity-consuming stale row leaks."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[])
        operations = MagicMock()

        uow = _make_uow(todo_task)
        cloud_node = Node(node_id=NodeId(1), ip="10.0.0.100", ncpus=4, cloud="aws")
        uow.nodes.remove = AsyncMock()
        # First commit (step 1) succeeds; second commit (step 3 persist) fails;
        # subsequent commits (best-effort tmp cleanup) succeed.
        commit_calls = [0]

        async def _commit_side_effect() -> None:
            commit_calls[0] += 1
            if commit_calls[0] == 2:
                raise RuntimeError("final persist db lost")

        uow.commit = AsyncMock(side_effect=_commit_side_effect)

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = True

        clouds = _make_clouds(
            "aws",
            allocate_side_effect=None,
        )
        clouds.allocate = AsyncMock(return_value=cloud_node)

        with pytest.raises(RuntimeError, match="final persist db lost"):
            await allocate_task(
                task_id=todo_task.task_id,
                engines=engines,
                uow_factory=lambda: uow,
                repository=repository,
                operations=operations,
                clouds=clouds,
                start_task_on_machine=AsyncMock(),
                tracker=tracker,
                allocation_lock=asyncio.Lock(),
            )

        # Original persist exception propagates.
        tracker.discard.assert_called_once_with(todo_task.task_id)
        clouds.allocate.assert_called_once_with("aws")
        # VM is best-effort deallocated so no billable orphan leaks.
        clouds.deallocate.assert_called_once_with("aws", "10.0.0.100")
        # tmp-node best-effort cleanup also runs (remove(tmp_node_id) is called
        # directly — once in the persist attempt before commit raises, once in
        # the best-effort cleanup path after persist fails).
        assert uow.nodes.remove.call_count >= 2
        uow.nodes.get.assert_not_called()

    async def test_empty_platforms_short_circuits_cloud_fallback(
        self,
        todo_task: Task,
    ) -> None:
        """Engine with empty platforms never enters cloud-fallback (select_provider would silently return None and the task would spin in TO_DO forever)."""
        engine_no_platforms = Engine(
            name="test_engine",
            spawn="echo {task_path}",
            check_cmd="echo ok",
            check_pname=None,
            input_files=("inp",),
            output_files=("OUTPUT",),
            platforms=(),
        )

        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine_no_platforms

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[])
        operations = MagicMock()

        uow = _make_uow(todo_task)

        tracker = MagicMock(spec=AllocationTracker)
        clouds = _make_clouds("aws")

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=lambda: uow,
            repository=repository,
            operations=operations,
            clouds=clouds,
            start_task_on_machine=AsyncMock(),
            tracker=tracker,
            allocation_lock=asyncio.Lock(),
        )

        assert result is False
        # Short-circuit happens before tracker dedup and before port calls.
        tracker.add.assert_not_called()
        clouds.select_provider.assert_not_called()
        clouds.allocate.assert_not_called()

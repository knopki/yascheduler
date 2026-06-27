# FILE: tests/unit/test_application_events.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for domain event recording from application use cases.
#   SCOPE: submit_task records TaskCreated, allocate_task records TaskFailed/TaskAllocated, consume_task records TaskCompleted/TaskFailed.
#   DEPENDS: M-APPLICATION-SUBMIT, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME
#   LINKS: M-APPLICATION-SUBMIT, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestSubmitTaskEvents - submit_task: records TaskCreated event
#   TestAllocateTaskEvents - allocate_task: records TaskFailed (unsupported engine) and TaskAllocated (free machine) events
#   TestConsumeTaskEvents - consume_task: records TaskCompleted (success) and TaskFailed (permanent download failure) events
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Update TestConsumeTaskEvents for 3-tuple download_outputs (meta_add, transient_errors, permanent_errors); permanent failure now in permanent_errors list (fix-download-rmtree-data-loss).
#   PREVIOUS_CHANGE: v1.0.0 - Extracted from test_application_use_cases.py (size limit). Event recording tests moved to own file.
# END_CHANGE_SUMMARY
#
"""Unit tests for domain event recording from application use cases.

Tests cover:
- submit_task records TaskCreated event
- allocate_task records TaskFailed or TaskAllocated event
- consume_task records TaskCompleted or TaskFailed event
"""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePath
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.allocate_task import allocate_task
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.consume_task import consume_task
from yascheduler.application.submit_task import submit_task
from yascheduler.application.uow import AbstractUnitOfWork
from yascheduler.domain import Engine, EngineRepository
from yascheduler.domain.events import (
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from yascheduler.domain.model import (
    Task,
    TaskContext,
    TaskStatus,
)
from yascheduler.domain.ports import CloudProvisioner

# =============================================================================
# Event recording characterization tests (D4)
# =============================================================================


class TestSubmitTaskEvents:
    """Verify submit_task records TaskCreated event."""

    async def test_submit_task_records_task_created_event(
        self, engine: Engine, mock_engine_repo: MagicMock, mock_uow_factory: MagicMock
    ) -> None:
        uow = mock_uow_factory.return_value

        def _insert_side_effect(task: Task) -> Task:
            return replace(task, task_id=55)

        uow.tasks.insert = AsyncMock(side_effect=_insert_side_effect)

        await submit_task(
            label="evt_test",
            metadata={"inp": "data"},
            engine_name="test_engine",
            engines=mock_engine_repo,
            uow_factory=mock_uow_factory,
            remote_tasks_dir=PurePath("/remote/tasks"),
        )

        saved_arg: Task = uow.tasks.save.call_args[0][0]
        assert len(saved_arg._events) == 1
        event = saved_arg._events[0]
        assert isinstance(event, TaskCreated)
        assert event.task_id == 55
        assert event.engine_name == "test_engine"


class TestAllocateTaskEvents:
    """Verify allocate_task records TaskFailed or TaskAllocated events."""

    async def test_validate_engine_records_task_failed_event(self) -> None:
        """Unsupported engine records TaskFailed event."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = None

        todo_task = Task(
            task_id=1,
            label="t",
            context=TaskContext(engine="bad"),
            status=TaskStatus.TO_DO,
        )
        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        allocation_lock = asyncio.Lock()

        await allocate_task(
            task_id=1,
            engines=engines,
            uow_factory=uow_factory,
            repository=MagicMock(),
            operations=MagicMock(),
            clouds=MagicMock(),
            start_task_on_machine=AsyncMock(),
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert len(saved_task._events) == 1
        event = saved_task._events[0]
        assert isinstance(event, TaskFailed)
        assert event.reason == "unsupported engine"

    async def test_allocate_free_machine_records_task_allocated_event(
        self, engine: Engine
    ) -> None:
        """Successful allocation records TaskAllocated event."""
        import time

        from yascheduler.domain.model import ConnectedMachine, MachineState

        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        free_machine = MagicMock(spec=ConnectedMachine)
        free_machine.ip = "10.0.0.1"
        free_machine.state = MachineState.FREE
        free_machine.free_since = time.monotonic()

        repository = MagicMock()
        repository.list_free = MagicMock(return_value=[free_machine])
        operations = MagicMock()
        operations.start_occupancy_check = MagicMock()

        todo_task = Task(
            task_id=1,
            label="t",
            context=TaskContext(engine="test_engine"),
            status=TaskStatus.TO_DO,
        )
        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        allocation_lock = asyncio.Lock()
        clouds = MagicMock(spec=CloudProvisioner)
        start_on_machine = AsyncMock(return_value=True)

        await allocate_task(
            task_id=1,
            engines=engines,
            uow_factory=uow_factory,
            repository=repository,
            operations=operations,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        # save was called — check the last save has a TaskAllocated event
        save_calls = uow.tasks.save.call_args_list
        last_save_task: Task = save_calls[-1][0][0]
        allocated_events = [
            e for e in last_save_task._events if isinstance(e, TaskAllocated)
        ]
        assert len(allocated_events) == 1
        assert allocated_events[0].node_ip == "10.0.0.1"
        assert allocated_events[0].engine_name == "test_engine"
        # tracker.discard called (machine path discards immediately)
        tracker.discard.assert_called_once_with(1)


class TestConsumeTaskEvents:
    """Verify consume_task records TaskCompleted or TaskFailed events."""

    @pytest.fixture
    def mock_operations(self) -> MagicMock:
        operations = MagicMock()
        operations.download_outputs = AsyncMock(return_value=([], [], []))
        return operations

    async def _run_consume(
        self,
        ip: str,
        operations: MagicMock,
        task: Task,
        uow_factory: Callable[[], AbstractUnitOfWork],
        engines: EngineRepository,
        local_tasks_dir: Path,
        tracker: MagicMock,
    ) -> None:
        await consume_task(
            task_id=task.task_id,
            ip=ip,
            operations=operations,
            engines=engines,
            uow_factory=uow_factory,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

    async def test_consume_success_records_task_completed_event(
        self,
        mock_operations: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=running_task)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        local_tasks_dir = MagicMock(spec=Path)

        await self._run_consume(
            ip=running_task.allocated_ip,  # type: ignore[arg-type]
            operations=mock_operations,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert len(saved_task._events) == 1
        event = saved_task._events[0]
        assert isinstance(event, TaskCompleted)
        assert event.task_id == 1
        tracker.discard.assert_called_once_with(1)

    async def test_consume_failure_records_task_failed_event(
        self,
        mock_operations: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        mock_operations.download_outputs = AsyncMock(
            return_value=([], [], [("/remote/file", OSError("Connection refused"))])
        )

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=running_task)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        local_tasks_dir = MagicMock(spec=Path)

        await self._run_consume(
            ip=running_task.allocated_ip,  # type: ignore[arg-type]
            operations=mock_operations,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert len(saved_task._events) == 1
        event = saved_task._events[0]
        assert isinstance(event, TaskFailed)
        assert event.task_id == 1
        tracker.discard.assert_called_once_with(1)

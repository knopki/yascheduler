# FILE: tests/unit/test_consume_task.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for consume_task finalise/defer branches and task-not-found path.
#   SCOPE: Success (True), permanent-only (True, DONE+error), transient-only (False, deferred),
#          mixed permanent+transient (True, DONE+error with combined msg), task-not-found (True, tracker discarded).
#   DEPENDS: M-APPLICATION-CONSUME
#   LINKS: M-APPLICATION-CONSUME
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestConsumeTask - consume_task: success, permanent-only, transient-only defer, mixed permanent priority, task-not-found
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extracted from test_application_use_cases.py (GRACE 1000-line hard limit). Covers consume_task bool return + 3-tuple download_outputs branches (fix-download-rmtree-data-loss).
# END_CHANGE_SUMMARY
#
"""Unit tests for consume_task finalise/defer branches.

Covers the four finalisation branches (success, permanent-only, transient-only
defer, mixed permanent-priority) plus the task-not-found vacuous-finalisation
path. The `running_task` and `mock_engine_repo` fixtures come from
`tests/unit/conftest.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncssh.sftp import SFTPFailure

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.consume_task import consume_task
from yascheduler.domain.model import Task, TaskStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from yascheduler.application.uow import AbstractUnitOfWork
    from yascheduler.domain import EngineRepository


class TestConsumeTask:
    """consume_task — download outputs, finalise (True) or defer (False)."""

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
    ) -> bool:
        return await consume_task(
            task_id=task.task_id,
            ip=ip,
            operations=operations,
            engines=engines,
            uow_factory=uow_factory,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

    async def test_consume_task_download_success_marks_done(
        self,
        mock_operations: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """All output files downloaded -> save DONE + tracker discarded, returns True."""
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

        result = await self._run_consume(
            ip=running_task.allocated_ip,  # type: ignore[arg-type]
            operations=mock_operations,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # download_outputs called with correct params
        mock_operations.download_outputs.assert_called_once()
        assert mock_operations.download_outputs.call_args[1]["ip"] == "10.0.0.1"
        assert (
            mock_operations.download_outputs.call_args[1]["remote_dir"]
            == "/remote/tasks/20250101_120000_42"
        )
        assert mock_operations.download_outputs.call_args[1]["task_id"] == 1
        # DB saved with DONE status
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is None
        uow.commit.assert_called_once()
        # tracker.discard called instead of clouds.mark_task_done
        tracker.discard.assert_called_once_with(1)
        # finalised -> True
        assert result is True

    async def test_consume_task_download_failure_marks_error(
        self,
        mock_operations: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """Permanent-only errors -> save DONE with error, tracker discarded, returns True."""
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

        result = await self._run_consume(
            ip=running_task.allocated_ip,  # type: ignore[arg-type]
            operations=mock_operations,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # save was called with DONE + error
        uow.tasks.save.assert_called_once()
        saved_task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is not None
        # tracker.discard called on permanent failure path too
        tracker.discard.assert_called_once_with(1)
        # finalised -> True
        assert result is True

    async def test_consume_task_transient_only_defers(
        self,
        mock_operations: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """Transient-only errors -> no save, no event, no tracker.discard, returns False."""
        mock_operations.download_outputs = AsyncMock(
            return_value=(
                [],
                [("/remote/file", SFTPFailure("transient blip"))],
                [],
            )
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

        result = await self._run_consume(
            ip=running_task.allocated_ip,  # type: ignore[arg-type]
            operations=mock_operations,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # Deferred: no save, no commit, no tracker.discard
        uow.tasks.save.assert_not_called()
        uow.commit.assert_not_called()
        tracker.discard.assert_not_called()
        # returns False (deferred for retry)
        assert result is False

    async def test_consume_task_mixed_permanent_priority(
        self,
        mock_operations: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """Both transient and permanent -> permanent priority, task.fail, returns True."""
        transient = [("/remote/a", SFTPFailure("transient"))]
        permanent = [("/remote/b", OSError("permanent missing"))]
        mock_operations.download_outputs = AsyncMock(
            return_value=([], transient, permanent)
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

        result = await self._run_consume(
            ip=running_task.allocated_ip,  # type: ignore[arg-type]
            operations=mock_operations,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # finalised: save, commit, tracker.discard
        uow.tasks.save.assert_called_once()
        saved_task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is not None
        # error message includes both permanent and transient details
        error_str = str(saved_task.context.error)
        assert "permanent missing" in error_str
        assert "transient" in error_str
        uow.commit.assert_called_once()
        tracker.discard.assert_called_once_with(1)
        assert result is True

    async def test_consume_task_not_found_discards_tracker_returns_true(
        self,
        mock_operations: MagicMock,
        mock_engine_repo: MagicMock,
    ) -> None:
        """Task not found in DB -> tracker.discard called, no download/save, returns True."""
        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=None)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        local_tasks_dir = MagicMock(spec=Path)

        result = await consume_task(
            task_id=999,
            ip="10.0.0.1",
            operations=mock_operations,
            engines=mock_engine_repo,
            uow_factory=uow_factory,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # No download attempted, no save, no commit; tracker slot discarded
        mock_operations.download_outputs.assert_not_called()
        uow.tasks.save.assert_not_called()
        uow.commit.assert_not_called()
        tracker.discard.assert_called_once_with(999)
        # Vacuously finalised -> True
        assert result is True

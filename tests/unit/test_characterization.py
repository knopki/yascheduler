# FILE: tests/unit/test_characterization.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Characterization tests — verify refactored Scheduler v2.0.0 (delegates to
#            Orchestrator + use cases) produces the same results as the old Scheduler.
#   SCOPE: Scheduler.create_new_task, .start, .stop delegation; Client.queue_submit_task_async.
#   DEPENDS: M-SCHEDULER, M-CLIENT, M-DI, M-APPLICATION-SUBMIT, M-APPLICATION-ORCHESTRATOR
#   LINKS: M-SCHEDULER, M-CLIENT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestSchedulerCreateNewTask - Scheduler.create_new_task delegates to submit_task use case
#   TestSchedulerStart - Scheduler.start delegates to Orchestrator via make_daemon
#   TestSchedulerStop - Scheduler.stop delegates to Orchestrator (or falls back)
#   TestClientQueueSubmitTaskAsync - Client.queue_submit_task_async uses CLIDeps, no Scheduler
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial characterization tests for v2.0.0 refactoring.
# END_CHANGE_SUMMARY

"""Characterization tests (task 5.7): verify old Scheduler behavior == new use case behavior.

These tests verify that the refactored Scheduler (v2.0.0 which delegates to
Orchestrator + use cases) produces the same results as the old Scheduler would have.
"""

from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestSchedulerCreateNewTask:
    """Scheduler.create_new_task delegates to submit_task use case."""

    @pytest.mark.asyncio
    @patch("yascheduler.scheduler.submit_task", new=AsyncMock(return_value=42))
    @patch("yascheduler.scheduler.make_cli_deps")
    async def test_create_new_task_delegates_to_submit_task(
        self, mock_make_deps
    ) -> None:
        """create_new_task passes label, metadata, engine_name to submit_task and fetches result via db.get_task."""
        # Arrange
        mock_deps = MagicMock()
        mock_deps.engines = MagicMock()
        mock_deps.uow_factory = MagicMock()
        mock_deps.remote_tasks_dir = PurePosixPath("/tmp/tasks")
        mock_make_deps.return_value = mock_deps

        mock_db = MagicMock()
        mock_db.get_task = AsyncMock(return_value=MagicMock(task_id=42))

        from yascheduler.scheduler import Scheduler

        scheduler = Scheduler(
            config=MagicMock(), db=mock_db, clouds=MagicMock(), log=MagicMock()
        )

        # Act
        result = await scheduler.create_new_task(
            label="test", metadata={"inp": "data"}, engine_name="fleur"
        )

        # Assert
        assert result.task_id == 42
        mock_make_deps.assert_called_once_with(scheduler.config)
        # Access the patched submit_task from scheduler module
        import yascheduler.scheduler as sched_mod

        sched_mod.submit_task.assert_awaited_once_with(  # type: ignore[attr-defined]
            label="test",
            metadata={"inp": "data"},
            engine_name="fleur",
            engines=mock_deps.engines,
            uow_factory=mock_deps.uow_factory,
            remote_tasks_dir=mock_deps.remote_tasks_dir,
        )
        mock_db.get_task.assert_awaited_once_with(42)


class TestSchedulerStart:
    """Scheduler.start delegates to Orchestrator via make_daemon."""

    @pytest.mark.asyncio
    @patch("yascheduler.scheduler.make_daemon")
    async def test_start_delegates_to_orchestrator(self, mock_make_daemon) -> None:
        """start() creates Orchestrator via make_daemon, transfers resources, and calls orchestrator.start()."""
        # Arrange
        from yascheduler.scheduler import Scheduler

        mock_orch = MagicMock()
        mock_orch.start = AsyncMock()
        mock_make_daemon.return_value = mock_orch

        scheduler = Scheduler(
            config=MagicMock(), db=MagicMock(), clouds=MagicMock(), log=MagicMock()
        )

        # Act
        await scheduler.start()

        # Assert
        mock_make_daemon.assert_awaited_once_with(
            scheduler.config, scheduler.log, db=scheduler.db, clouds=scheduler.clouds
        )
        assert scheduler._orchestrator is mock_orch
        mock_orch.start.assert_awaited_once()


class TestSchedulerStop:
    """Scheduler.stop delegates to Orchestrator when available, falls back otherwise."""

    @pytest.mark.asyncio
    async def test_stop_delegates_to_orchestrator_when_available(self) -> None:
        """stop() calls orchestrator.stop() when _orchestrator is set."""
        from yascheduler.scheduler import Scheduler

        scheduler = Scheduler(
            config=MagicMock(), db=MagicMock(), clouds=MagicMock(), log=MagicMock()
        )
        mock_orch = MagicMock()
        mock_orch.stop = AsyncMock()
        scheduler._orchestrator = mock_orch

        await scheduler.stop()

        mock_orch.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_falls_back_to_clouds_and_db_when_no_orchestrator(self) -> None:
        """stop() calls clouds.stop() and db.close() when _orchestrator is None."""
        from yascheduler.scheduler import Scheduler

        mock_db = MagicMock()
        mock_db.close = AsyncMock()
        mock_clouds = MagicMock()
        mock_clouds.stop = AsyncMock()

        scheduler = Scheduler(
            config=MagicMock(), db=mock_db, clouds=mock_clouds, log=MagicMock()
        )
        assert scheduler._orchestrator is None

        await scheduler.stop()

        mock_clouds.stop.assert_awaited_once()
        mock_db.close.assert_awaited_once()


class TestClientQueueSubmitTaskAsync:
    """Client.queue_submit_task_async uses CLIDeps (no Scheduler import)."""

    @pytest.mark.asyncio
    @patch("yascheduler.client.Config.from_config_parser")
    @patch("yascheduler.di.make_cli_deps")
    async def test_queue_submit_task_async_uses_cli_deps(
        self, mock_make_cli_deps, mock_from_cfg
    ) -> None:
        """queue_submit_task_async calls deps.submit() via make_cli_deps, not Scheduler."""
        from yascheduler.client import Yascheduler

        # Arrange
        mock_deps = MagicMock()
        mock_deps.submit = AsyncMock(return_value=99)
        mock_make_cli_deps.return_value = mock_deps
        mock_from_cfg.return_value = MagicMock()

        client = Yascheduler()

        # Act
        result = await client.queue_submit_task_async(
            label="test-job",
            metadata={"key": "val"},
            engine_name="fleur",
        )

        # Assert
        assert result == 99
        mock_make_cli_deps.assert_called_once_with(client.config)
        mock_deps.submit.assert_awaited_once_with("test-job", {"key": "val"}, "fleur")

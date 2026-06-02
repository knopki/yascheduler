# FILE: tests/unit/test_application_use_cases.py
# VERSION: 2.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for application use cases (submit, allocate, consume, deallocate).
#   SCOPE: submit_task validation and success, allocate_task free/cloud/error paths, consume_task success/failure, deallocate_nodes disable/skip.
#   DEPENDS: M-APPLICATION-SUBMIT, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE
#   LINKS: M-APPLICATION-SUBMIT, M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestSubmitTask - submit_task: unknown engine, missing input, success path
#   TestAllocateTask - allocate_task: unsupported engine, free machine, cloud fallback
#   TestConsumeTask - consume_task: download success, download failure
#   TestDeallocateNodes - deallocate_nodes: idle disable, non-cloud skip
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.0.0 - Update to UoW-based signatures (task_id, uow_factory) across allocate, consume, deallocate.
#   PREVIOUS_CHANGE: v1.0.0 - Initial use case unit tests covering all 4 application functions.
# END_CHANGE_SUMMARY
#
"""Unit tests for application use cases.

Tests cover the 4 application use cases:
- submit_task    (yascheduler.application.submit_task)
- allocate_task  (yascheduler.application.allocate_task)
- consume_task   (yascheduler.application.consume_task)
- deallocate_nodes (yascheduler.application.deallocate_nodes)
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePath, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.application.allocate_task import allocate_task
from yascheduler.application.consume_task import consume_task
from yascheduler.application.deallocate_nodes import deallocate_nodes
from yascheduler.application.submit_task import submit_task
from yascheduler.application.uow import AbstractUnitOfWork
from yascheduler.config import Engine, EngineRepository
from yascheduler.config.cloud import ConfigCloudAzure
from yascheduler.domain.exceptions import MissingInputFileError, UnsupportedEngineError
from yascheduler.domain.model import Node, Task, TaskContext, TaskStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def engine() -> Engine:
    """A valid engine with one input file, one output file, linux platform."""
    return Engine(
        name="test_engine",
        spawn="echo {task_path}",
        check_cmd="echo ok",
        check_pname=None,
        input_files=("inp",),
        output_files=("OUTPUT",),
        platforms=("linux",),
    )


@pytest.fixture
def mock_engine_repo(engine: Engine) -> MagicMock:
    """EngineRepository that contains ``test_engine``."""
    repo = MagicMock(spec=EngineRepository)
    repo.__contains__.return_value = True
    repo.__getitem__.return_value = engine
    repo.get.return_value = engine
    return repo


@pytest.fixture
def mock_uow_factory() -> MagicMock:
    """Factory that returns a fully-mocked UnitOfWork with async methods."""
    uow = AsyncMock()
    uow.tasks = AsyncMock()
    uow.tasks.insert = AsyncMock()
    uow.tasks.save = AsyncMock()
    uow.tasks.get = AsyncMock()
    uow.commit = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=uow)


@pytest.fixture
def running_task() -> Task:
    """A RUNNING domain Task for use with consume_task."""
    return Task(
        task_id=1,
        label="test",
        context=TaskContext(
            engine="test_engine",
            remote_folder="/remote/tasks/20250101_120000_42",
        ),
        status=TaskStatus.RUNNING,
        allocated_ip="10.0.0.1",
    )


# =============================================================================
# submit_task  (3 tests)
# =============================================================================


class TestSubmitTask:
    """submit_task — validates engine & inputs, persists via UoW."""

    async def test_submit_task_unknown_engine(
        self, mock_engine_repo: MagicMock, mock_uow_factory: MagicMock
    ) -> None:
        """Engine not in repository -> UnsupportedEngineError."""
        mock_engine_repo.__contains__.return_value = False

        with pytest.raises(UnsupportedEngineError) as exc_info:
            await submit_task(
                label="test",
                metadata={"inp": "data"},
                engine_name="nonexistent_engine",
                engines=mock_engine_repo,
                uow_factory=mock_uow_factory,
                remote_tasks_dir=PurePath("/remote/tasks"),
            )
        assert "nonexistent_engine" in str(exc_info.value)
        mock_uow_factory.assert_not_called()

    async def test_submit_task_missing_input_file(
        self, mock_engine_repo: MagicMock, mock_uow_factory: MagicMock
    ) -> None:
        """Engine requires 'inp' but metadata lacks it -> MissingInputFileError."""
        with pytest.raises(MissingInputFileError) as exc_info:
            await submit_task(
                label="test",
                metadata={"other": "data"},  # 'inp' is missing
                engine_name="test_engine",
                engines=mock_engine_repo,
                uow_factory=mock_uow_factory,
                remote_tasks_dir=PurePath("/remote/tasks"),
            )
        assert "inp" in str(exc_info.value)
        assert "test_engine" in str(exc_info.value)
        mock_uow_factory.assert_not_called()

    async def test_submit_task_success_returns_task_id(
        self, engine: Engine, mock_engine_repo: MagicMock, mock_uow_factory: MagicMock
    ) -> None:
        """Happy path: validates, inserts, saves with remote_folder, commits, returns id."""
        uow = mock_uow_factory.return_value

        def _insert_side_effect(task: Task) -> Task:
            return replace(task, task_id=42)

        uow.tasks.insert = AsyncMock(side_effect=_insert_side_effect)

        task_id = await submit_task(
            label="my_job",
            metadata={"inp": "content"},
            engine_name="test_engine",
            engines=mock_engine_repo,
            uow_factory=mock_uow_factory,
            remote_tasks_dir=PurePath("/remote/tasks"),
        )

        assert task_id == 42

        # insert was called with a TO_DO task
        uow.tasks.insert.assert_called_once()
        inserted_arg: Task = uow.tasks.insert.call_args[0][0]
        assert inserted_arg.label == "my_job"
        assert inserted_arg.status == TaskStatus.TO_DO
        assert inserted_arg.context.extra == {"inp": "content"}
        assert inserted_arg.context.engine == "test_engine"

        # save was called with the task that now has remote_folder set
        uow.tasks.save.assert_called_once()
        saved_arg: Task = uow.tasks.save.call_args[0][0]
        assert saved_arg.task_id == 42
        assert saved_arg.context.remote_folder is not None
        assert str(saved_arg.context.remote_folder).startswith("/remote/tasks/")
        assert saved_arg.context.remote_folder.endswith("_42")  # dt_str_taskid

        uow.commit.assert_called_once()


# =============================================================================
# allocate_task  (3 tests)
# =============================================================================


class TestAllocateTask:
    """allocate_task — match a TO_DO task to free machine or request cloud."""

    @pytest.fixture
    def todo_task(self) -> Task:
        return Task(
            task_id=1,
            label="test",
            context=TaskContext(engine="test_engine"),
            status=TaskStatus.TO_DO,
        )

    async def test_allocate_task_unsupported_engine(self, todo_task: Task) -> None:
        """Engine name not in repo -> reject via UoW, return False."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = None  # engine lookup fails

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        do_webhook = AsyncMock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            remote_machines=MagicMock(),
            clouds=MagicMock(),
            start_task_on_machine=AsyncMock(),
            do_task_webhook=do_webhook,
        )

        assert result is False
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error == "unsupported engine"
        do_webhook.assert_called_once()
        _wh_id, _wh_meta, _wh_status = do_webhook.call_args[0]
        assert _wh_id == 1
        assert _wh_status == TaskStatus.DONE

    async def test_allocate_task_finds_free_machine(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """Free compatible machine exists -> allocated, returns True."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        free_machine = MagicMock()
        free_machine.start_occupancy_check = AsyncMock()

        remote_machines = MagicMock()
        remote_machines.filter.return_value = {"10.0.0.1": free_machine}

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        clouds = MagicMock()
        clouds.mark_task_done = MagicMock()
        start_on_machine = AsyncMock(return_value=True)
        do_webhook = AsyncMock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            remote_machines=remote_machines,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            do_task_webhook=do_webhook,
        )

        assert result is True
        # machine filtered with correct params
        remote_machines.filter.assert_called_once_with(
            busy=False, platforms=("linux",), reverse_sort=True
        )
        # task started on machine
        start_on_machine.assert_called_once()
        _call_machine, _call_engine, _call_task = start_on_machine.call_args[0]
        assert _call_machine is free_machine
        assert _call_engine is engine
        assert _call_task.allocated_ip == "10.0.0.1"
        # occupancy check started
        free_machine.start_occupancy_check.assert_called_once_with(engine)
        # db updated via UoW
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.allocated_ip == "10.0.0.1"
        assert saved_task.status == TaskStatus.RUNNING
        uow.commit.assert_called_once()
        # webhook with RUNNING status
        do_webhook.assert_called_once_with(
            saved_task.task_id,
            saved_task.context.to_metadata(),
            TaskStatus.RUNNING,
        )
        # cloud marked done
        clouds.mark_task_done.assert_called_once_with(1)

    async def test_allocate_task_no_free_machine_requests_cloud(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """No free machine -> clouds.allocate called, return False."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        # empty remote machines
        remote_machines = MagicMock()
        remote_machines.filter.return_value = {}

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        clouds = MagicMock()
        clouds.allocate_with_tracking = AsyncMock(return_value=None)
        start_on_machine = AsyncMock()
        do_webhook = AsyncMock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            remote_machines=remote_machines,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            do_task_webhook=do_webhook,
        )

        assert result is False
        clouds.allocate_with_tracking.assert_called_once_with(
            on_task=1, platforms=["linux"], throttle=True
        )
        start_on_machine.assert_not_called()
        uow.tasks.save.assert_not_called()


# =============================================================================
# consume_task  (2 tests)
# =============================================================================


class TestConsumeTask:
    """consume_task — download outputs, mark DONE or ERROR."""

    @pytest.fixture
    def sftp_mock(self) -> AsyncMock:
        sftp = AsyncMock()
        sftp.get = AsyncMock(return_value=None)
        sftp.rmtree = AsyncMock(return_value=None)
        return sftp

    @pytest.fixture
    def machine_mock(self, sftp_mock: AsyncMock) -> MagicMock:
        async_sftp_cm = AsyncMock()
        async_sftp_cm.__aenter__.return_value = sftp_mock

        machine = MagicMock()
        machine.sftp = MagicMock(return_value=async_sftp_cm)
        # machine.path returns PurePosixPath class so machine.path(remote_folder)
        # constructs a PurePosixPath, matching the real behaviour.
        machine.path = PurePosixPath
        return machine

    async def _run_consume(
        self,
        machine: MagicMock,
        task: Task,
        uow_factory: Callable[[], AbstractUnitOfWork],
        engines: EngineRepository,
        local_tasks_dir: Path,
        clouds: MagicMock,
        do_webhook: AsyncMock,
    ) -> None:
        """Run consume_task with backoff and executor patched out."""
        # backoff.on_exception -> identity decorator (bypass retry logic)
        with patch(
            "yascheduler.application.consume_task.backoff.on_exception"
        ) as mock_bo:
            mock_bo.return_value = lambda f: f
            # asyncio.get_running_loop -> avoid real executor calls
            with patch(
                "yascheduler.application.consume_task.asyncio.get_running_loop"
            ) as mock_get_loop:
                mock_loop = MagicMock()
                mock_get_loop.return_value = mock_loop
                mock_loop.run_in_executor = AsyncMock(return_value=None)
                await consume_task(
                    task_id=task.task_id,
                    machine=machine,
                    engines=engines,
                    uow_factory=uow_factory,
                    local_tasks_dir=local_tasks_dir,
                    clouds=clouds,
                    do_task_webhook=do_webhook,
                )

    async def test_consume_task_download_success_marks_done(
        self,
        machine_mock: MagicMock,
        sftp_mock: AsyncMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """All output files downloaded -> save DONE + webhook(DONE)."""
        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=running_task)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        do_webhook = AsyncMock()
        clouds = MagicMock()
        clouds.mark_task_done = MagicMock()
        local_tasks_dir = MagicMock(spec=Path)

        await self._run_consume(
            machine=machine_mock,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            clouds=clouds,
            do_webhook=do_webhook,
        )

        # Exactly one output file downloaded
        sftp_mock.get.assert_called_once_with(
            "/remote/tasks/20250101_120000_42/OUTPUT",
            local_tasks_dir / "20250101_120000_42",
            preserve=True,
        )
        # Remote tree cleaned up
        sftp_mock.rmtree.assert_called_once()
        # DB saved with DONE status
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is None
        uow.commit.assert_called_once()
        # Webhook with DONE
        do_webhook.assert_called_once()
        _wh_id, _wh_meta, _wh_status = do_webhook.call_args[0]
        assert _wh_status == TaskStatus.DONE
        assert "error" not in _wh_meta
        # Cloud notified
        clouds.mark_task_done.assert_called_once_with(1)

    async def test_consume_task_download_failure_marks_error(
        self,
        machine_mock: MagicMock,
        sftp_mock: AsyncMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """Download raises OSError -> save DONE with error + webhook(DONE)."""
        sftp_mock.get = AsyncMock(side_effect=OSError("Connection refused"))

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=running_task)
        uow.tasks.save = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        do_webhook = AsyncMock()
        clouds = MagicMock()
        clouds.mark_task_done = MagicMock()
        local_tasks_dir = MagicMock(spec=Path)

        await self._run_consume(
            machine=machine_mock,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            clouds=clouds,
            do_webhook=do_webhook,
        )

        # save was called with DONE + error
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is not None
        # Webhook still fires with DONE status
        do_webhook.assert_called_once()
        _wh_status = do_webhook.call_args[0][2]
        assert _wh_status == TaskStatus.DONE
        # error info present in metadata passed to webhook
        _wh_meta = do_webhook.call_args[0][1]
        assert "error" in _wh_meta


# =============================================================================
# deallocate_nodes  (2 tests)
# =============================================================================


class TestDeallocateNodes:
    """deallocate_nodes — disable idle cloud nodes, return IPs for VM deletion."""

    async def test_deallocate_nodes_disables_idle_cloud_nodes(self) -> None:
        """Enabled cloud node idle beyond tolerance -> disable_node called, IP returned."""
        # An enabled Azure node
        az_node = Node(ip="10.0.0.1", ncpus=4, cloud="az")

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes = AsyncMock()
        uow.nodes.list_enabled = AsyncMock(return_value=[az_node])
        uow.nodes.list_disabled = AsyncMock(return_value=[az_node])
        uow.nodes.disable = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        config_clouds = [
            MagicMock(spec=ConfigCloudAzure, prefix="az", idle_tolerance=300)
        ]

        # free_since is well beyond tolerance so the node qualifies
        idle_machines = {"10.0.0.1": datetime(2020, 1, 1, 0, 0, 0)}

        result = await deallocate_nodes(
            uow_factory=uow_factory,
            config_clouds=config_clouds,
            idle_machines=idle_machines,
        )

        # First phase: node should be disabled
        uow.nodes.disable.assert_called_once_with("10.0.0.1")
        uow.commit.assert_called()

        # Second phase: disabled node qualifies (has cloud, valid ip) -> returned
        assert isinstance(result, list)
        assert "10.0.0.1" in result

    async def test_deallocate_nodes_skips_non_cloud_nodes(self) -> None:
        """Node with cloud=None -> NOT disabled, NOT in returned list."""
        # An enabled node without cloud
        local_node = Node(ip="10.0.0.1", ncpus=4, cloud=None)

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes = AsyncMock()
        uow.nodes.list_enabled = AsyncMock(return_value=[local_node])
        uow.nodes.list_disabled = AsyncMock(return_value=[local_node])
        uow.nodes.disable = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        config_clouds = [
            MagicMock(spec=ConfigCloudAzure, prefix="az", idle_tolerance=300)
        ]

        idle_machines = {"10.0.0.1": datetime(2020, 1, 1, 0, 0, 0)}

        result = await deallocate_nodes(
            uow_factory=uow_factory,
            config_clouds=config_clouds,
            idle_machines=idle_machines,
        )

        # In first phase: node.cloud=None != "az" prefix, so NOT disabled
        uow.nodes.disable.assert_not_called()
        # In second phase: node.cloud is None -> filtered out, not returned
        assert isinstance(result, list)
        assert "10.0.0.1" not in result

# FILE: tests/unit/test_application_use_cases.py
# VERSION: 1.0.0
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
#   LAST_CHANGE: v1.0.0 - Initial use case unit tests covering all 4 application functions.
# END_CHANGE_SUMMARY
#
"""Unit tests for application use cases.

Tests cover the 4 application use cases:
- submit_task    (yascheduler.application.submit_task)
- allocate_task  (yascheduler.application.allocate_task)
- consume_task   (yascheduler.application.consume_task)
- deallocate_nodes (yascheduler.application.deallocate_nodes)
"""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path, PurePath, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.application.allocate_task import allocate_task
from yascheduler.application.consume_task import consume_task
from yascheduler.application.deallocate_nodes import deallocate_nodes
from yascheduler.application.submit_task import submit_task
from yascheduler.clouds import CloudAPIManager
from yascheduler.config import Engine, EngineRepository
from yascheduler.config.cloud import ConfigCloudAzure
from yascheduler.db import DB, TaskModel
from yascheduler.db import TaskStatus as DbTaskStatus
from yascheduler.domain.exceptions import MissingInputFileError, UnsupportedEngineError
from yascheduler.domain.model import Task, TaskStatus
from yascheduler.remote_machine import RemoteMachine, RemoteMachineRepository

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
    uow = MagicMock()
    uow.tasks = MagicMock()
    uow.tasks.insert = AsyncMock()
    uow.tasks.save = AsyncMock()
    uow.tasks.get = AsyncMock()
    uow.commit = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=uow)


@pytest.fixture
def running_task_model() -> TaskModel:
    """A RUNNING TaskModel for use with consume_task."""
    return TaskModel(
        task_id=1,
        label="test",
        ip="10.0.0.1",
        status=DbTaskStatus.RUNNING,
        metadata={
            "engine": "test_engine",
            "remote_folder": "/remote/tasks/20250101_120000_42",
        },
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
    def db_mock(self) -> AsyncMock:
        db = AsyncMock(spec=DB)
        db.get_tasks_by_status.return_value = []
        db.set_task_error = AsyncMock()
        db.set_task_running = AsyncMock()
        db.commit = AsyncMock()
        return db

    @pytest.fixture
    def todo_task(self) -> TaskModel:
        return TaskModel(
            task_id=1,
            label="test",
            ip="",
            status=DbTaskStatus.TO_DO,
            metadata={"engine": "test_engine"},
        )

    async def test_allocate_task_unsupported_engine(
        self, db_mock: AsyncMock, todo_task: TaskModel
    ) -> None:
        """Engine name not in repo -> set_task_error, return False."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = None  # engine lookup fails

        do_webhook = AsyncMock()

        result = await allocate_task(
            task=todo_task,
            engines=engines,
            db=db_mock,
            remote_machines=MagicMock(spec=RemoteMachineRepository),
            clouds=MagicMock(spec=CloudAPIManager),
            start_task_on_machine=AsyncMock(),
            do_task_webhook=do_webhook,
        )

        assert result is False
        db_mock.set_task_error.assert_called_once_with(
            1, metadata=todo_task.metadata, error="unsupported engine"
        )
        do_webhook.assert_called_once_with(1, todo_task.metadata, DbTaskStatus.DONE)

    async def test_allocate_task_finds_free_machine(
        self,
        db_mock: AsyncMock,
        todo_task: TaskModel,
        engine: Engine,
    ) -> None:
        """Free compatible machine exists -> allocated, returns True."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        free_machine = MagicMock(spec=RemoteMachine)
        free_machine.start_occupancy_check = AsyncMock()

        remote_machines = MagicMock(spec=RemoteMachineRepository)
        remote_machines.filter.return_value = {"10.0.0.1": free_machine}

        clouds = MagicMock(spec=CloudAPIManager)
        start_on_machine = AsyncMock(return_value=True)
        do_webhook = AsyncMock()

        result = await allocate_task(
            task=todo_task,
            engines=engines,
            db=db_mock,
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
        assert _call_task.ip == "10.0.0.1"
        # occupancy check started
        free_machine.start_occupancy_check.assert_called_once_with(engine)
        # db updated
        db_mock.set_task_running.assert_called_once_with(1, "10.0.0.1")
        db_mock.commit.assert_called_once()
        # webhook with RUNNING status
        do_webhook.assert_called_once_with(1, todo_task.metadata, DbTaskStatus.RUNNING)
        # cloud marked done
        clouds.mark_task_done.assert_called_once_with(1)

    async def test_allocate_task_no_free_machine_requests_cloud(
        self,
        db_mock: AsyncMock,
        todo_task: TaskModel,
        engine: Engine,
    ) -> None:
        """No free machine -> clouds.allocate called, return False."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        # empty remote machines
        remote_machines = MagicMock(spec=RemoteMachineRepository)
        remote_machines.filter.return_value = {}

        clouds = MagicMock(spec=CloudAPIManager)
        clouds.allocate = AsyncMock(return_value=None)
        start_on_machine = AsyncMock()
        do_webhook = AsyncMock()

        result = await allocate_task(
            task=todo_task,
            engines=engines,
            db=db_mock,
            remote_machines=remote_machines,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            do_task_webhook=do_webhook,
        )

        assert result is False
        clouds.allocate.assert_called_once_with(
            1, want_platforms=("linux",), throttle=True
        )
        start_on_machine.assert_not_called()
        db_mock.set_task_running.assert_not_called()


# =============================================================================
# consume_task  (2 tests)
# =============================================================================


class TestConsumeTask:
    """consume_task — download outputs, mark DONE or ERROR."""

    @pytest.fixture
    def db_mock(self) -> AsyncMock:
        db = AsyncMock(spec=DB)
        db.set_task_done = AsyncMock()
        db.set_task_error = AsyncMock()
        db.commit = AsyncMock()
        return db

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

        machine = MagicMock(spec=RemoteMachine)
        machine.sftp = MagicMock(return_value=async_sftp_cm)
        # machine.path returns PurePosixPath class so machine.path(remote_folder)
        # constructs a PurePosixPath, matching the real behaviour.
        machine.path = PurePosixPath
        return machine

    async def _run_consume(
        self,
        machine: MagicMock,
        task: TaskModel,
        engines: EngineRepository,
        db: AsyncMock,
        local_tasks_dir: Path,
        clouds: CloudAPIManager,
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
                    machine=machine,
                    task=task,
                    engines=engines,
                    db=db,
                    local_tasks_dir=local_tasks_dir,
                    clouds=clouds,
                    do_task_webhook=do_webhook,
                )

    async def test_consume_task_download_success_marks_done(
        self,
        machine_mock: MagicMock,
        sftp_mock: AsyncMock,
        running_task_model: TaskModel,
        mock_engine_repo: MagicMock,
        db_mock: AsyncMock,
    ) -> None:
        """All output files downloaded -> set_task_done + webhook(DONE)."""
        do_webhook = AsyncMock()
        clouds = MagicMock(spec=CloudAPIManager)
        local_tasks_dir = MagicMock(spec=Path)

        await self._run_consume(
            machine=machine_mock,
            task=running_task_model,
            engines=mock_engine_repo,
            db=db_mock,
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
        # DB marked done (no error)
        db_mock.set_task_done.assert_called_once()
        db_mock.set_task_error.assert_not_called()
        # Webhook with DONE
        do_webhook.assert_called_once()
        _wh_id, _wh_meta, _wh_status = do_webhook.call_args[0]
        assert _wh_status == DbTaskStatus.DONE
        assert "error" not in _wh_meta
        # Cloud notified
        clouds.mark_task_done.assert_called_once_with(1)

    async def test_consume_task_download_failure_marks_error(
        self,
        machine_mock: MagicMock,
        sftp_mock: AsyncMock,
        running_task_model: TaskModel,
        mock_engine_repo: MagicMock,
        db_mock: AsyncMock,
    ) -> None:
        """Download raises OSError -> set_task_error + webhook(DONE)."""
        sftp_mock.get = AsyncMock(side_effect=OSError("Connection refused"))
        do_webhook = AsyncMock()
        clouds = MagicMock(spec=CloudAPIManager)
        local_tasks_dir = MagicMock(spec=Path)

        await self._run_consume(
            machine=machine_mock,
            task=running_task_model,
            engines=mock_engine_repo,
            db=db_mock,
            local_tasks_dir=local_tasks_dir,
            clouds=clouds,
            do_webhook=do_webhook,
        )

        # set_task_error was called (not set_task_done)
        db_mock.set_task_error.assert_called_once()
        db_mock.set_task_done.assert_not_called()
        # Webhook still fires with DONE status
        do_webhook.assert_called_once()
        _wh_status = do_webhook.call_args[0][2]
        assert _wh_status == DbTaskStatus.DONE
        # error info present in metadata passed to webhook
        _wh_meta = do_webhook.call_args[0][1]
        assert "error" in _wh_meta


# =============================================================================
# deallocate_nodes  (2 tests)
# =============================================================================


class TestDeallocateNodes:
    """deallocate_nodes — disable idle cloud nodes, deallocate cloud VMs."""

    @pytest.fixture
    def db_mock(self) -> AsyncMock:
        db = AsyncMock(spec=DB)
        db.get_tasks_by_status.return_value = []  # no running tasks
        db.get_enabled_nodes.return_value = []
        db.get_disabled_nodes.return_value = []
        db.disable_node = AsyncMock()
        db.commit = AsyncMock()
        return db

    async def test_deallocate_nodes_disables_idle_cloud_nodes(
        self, db_mock: AsyncMock
    ) -> None:
        """Enabled cloud node idle beyond tolerance -> disable_node called."""
        # An enabled Azure node
        az_node = MagicMock()
        az_node.ip = "10.0.0.1"
        az_node.cloud = "az"
        db_mock.get_enabled_nodes.return_value = [az_node]
        db_mock.get_disabled_nodes.return_value = []  # none already disabled

        # Remote machine filter returns the node as free
        idler_machine = MagicMock(spec=RemoteMachine)
        remote_machines = MagicMock(spec=RemoteMachineRepository)
        remote_machines.filter.return_value = {"10.0.0.1": idler_machine}

        clouds = MagicMock(spec=CloudAPIManager)
        clouds.deallocate = AsyncMock()

        config_clouds = [
            MagicMock(spec=ConfigCloudAzure, prefix="az", idle_tolerance=300)
        ]

        await deallocate_nodes(
            db=db_mock,
            remote_machines=remote_machines,
            clouds=clouds,
            config_clouds=config_clouds,
        )

        # First phase: node should be disabled
        db_mock.disable_node.assert_called_once_with("10.0.0.1")
        db_mock.commit.assert_called()

        # remote_machines.filter called with idle tolerance
        expected_td = timedelta(seconds=300)
        remote_machines.filter.assert_called_with(
            busy=False, reverse_sort=False, free_since_gt=expected_td
        )

    async def test_deallocate_nodes_skips_non_cloud_nodes(
        self, db_mock: AsyncMock
    ) -> None:
        """Node with cloud=None -> clouds.deallocate NOT called."""
        # An enabled node without cloud
        local_node = MagicMock()
        local_node.ip = "10.0.0.1"
        local_node.cloud = None

        # Disabled nodes include this node (non-cloud)
        disabled_node = MagicMock()
        disabled_node.ip = "10.0.0.1"
        disabled_node.cloud = None

        db_mock.get_enabled_nodes.return_value = [local_node]
        db_mock.get_disabled_nodes.return_value = [disabled_node]

        # Remote machine filter returns the node as free
        idler_machine = MagicMock(spec=RemoteMachine)
        remote_machines = MagicMock(spec=RemoteMachineRepository)
        # For "ip in remote_machines.keys()" check in phase 2
        remote_machines.keys.return_value = ["10.0.0.1"]
        remote_machines.filter.return_value = {"10.0.0.1": idler_machine}

        clouds = MagicMock(spec=CloudAPIManager)
        clouds.deallocate = AsyncMock()

        config_clouds = [
            MagicMock(spec=ConfigCloudAzure, prefix="az", idle_tolerance=300)
        ]

        await deallocate_nodes(
            db=db_mock,
            remote_machines=remote_machines,
            clouds=clouds,
            config_clouds=config_clouds,
        )

        # In first phase: node.cloud=None != "az" prefix, so NOT disabled
        db_mock.disable_node.assert_not_called()
        # In second phase: node.cloud is None -> continue -> deallocate NOT called
        clouds.deallocate.assert_not_called()

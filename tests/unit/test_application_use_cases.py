# FILE: tests/unit/test_application_use_cases.py
# VERSION: 4.2.0
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
#   TestAllocateTask - allocate_task: unsupported engine, free machine (tracker.discard), cloud-fallback happy path, failure cleanup, dedup, throttle, step1/step2-cleanup/step3 hardening
#   TestConsumeTask - consume_task: download success, download failure (tracker instead of clouds)
#   TestDeallocateNodes - deallocate_nodes: idle disable, non-cloud skip
#   TestDeallocateNodeBracketing - deallocate_node: disable+remove bracketing around cloud delete
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v4.2.0 - select_provider returns str; replace ProviderSelection(name="aws", username="root") with "aws" literal; add_tmp("aws") drops username arg (collapse-provider-selection).
#   PREVIOUS_CHANGE: v4.1.0 - Move allocate_task failure-mode hardening tests (step1 commit, step2 cleanup, step3 final persist) to test_allocate_task_failure_modes.py (file-size hard limit 1000).
# END_CHANGE_SUMMARY
#
"""Unit tests for application use cases.

Tests cover the 4 application use cases:
- submit_task    (yascheduler.application.submit_task)
- allocate_task  (yascheduler.application.allocate_task)
- consume_task   (yascheduler.application.consume_task)
- deallocate_nodes (yascheduler.application.deallocate_nodes)

Event recording tests (TaskCreated, TaskAllocated, TaskCompleted, TaskFailed)
are in test_application_events.py.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePath
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.allocate_task import allocate_task
from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.consume_task import consume_task
from yascheduler.application.deallocate_nodes import deallocate_node, deallocate_nodes
from yascheduler.application.submit_task import submit_task
from yascheduler.application.uow import AbstractUnitOfWork
from yascheduler.config import Engine, EngineRepository
from yascheduler.config.cloud import ConfigCloudAzure
from yascheduler.domain.exceptions import (
    CloudAllocateError,
    MissingInputFileError,
    UnsupportedEngineError,
)
from yascheduler.domain.model import (
    Node,
    Task,
    TaskContext,
    TaskStatus,
)
from yascheduler.domain.ports import CloudProvisioner

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
# allocate_task  (6 tests)
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

        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()

        tracker = MagicMock(spec=AllocationTracker)
        allocation_lock = asyncio.Lock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            gateway=MagicMock(),
            clouds=MagicMock(),
            start_task_on_machine=AsyncMock(),
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        assert result is False
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error == "unsupported engine"

    async def test_allocate_task_finds_free_machine(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """[11.6a] Free machine -> allocates, returns True, discards tracker slot. select_provider NOT called."""
        import time

        from yascheduler.domain.model import ConnectedMachine, MachineState

        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        free_machine = MagicMock(spec=ConnectedMachine)
        free_machine.ip = "10.0.0.1"
        free_machine.state = MachineState.FREE
        free_machine.free_since = time.monotonic()

        gateway = MagicMock()
        gateway.list_free = MagicMock(return_value=[free_machine])
        gateway.start_occupancy_check = MagicMock()

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

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            gateway=gateway,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        assert result is True
        gateway.list_free.assert_called_once_with(platforms=["linux"])
        start_on_machine.assert_called_once()
        _call_machine, _call_engine, _call_task = start_on_machine.call_args[0]
        assert _call_machine is free_machine
        assert _call_engine is engine
        assert _call_task.allocated_ip == "10.0.0.1"
        gateway.start_occupancy_check.assert_called_once_with("10.0.0.1", engine)
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.allocated_ip == "10.0.0.1"
        assert saved_task.status == TaskStatus.RUNNING
        uow.commit.assert_called_once()
        # tracker.discard called instead of clouds.mark_task_done
        tracker.discard.assert_called_once_with(todo_task.task_id)
        # cloud path NOT reached
        clouds.select_provider.assert_not_called()

    async def test_allocate_task_cloud_fallback_happy_path(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """[11.6b] No free machine -> select_provider, add_tmp, allocate, final persist."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        gateway = MagicMock()
        gateway.list_free = MagicMock(return_value=[])  # No free machines

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes = AsyncMock()
        uow.nodes.list_all = AsyncMock(return_value=[])
        uow.nodes.add_tmp = AsyncMock(return_value="tmp-10.0.0.100")
        uow.nodes.add = AsyncMock()
        uow.nodes.remove = AsyncMock()
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = True  # Not already tracked

        allocation_lock = asyncio.Lock()

        clouds = MagicMock(spec=CloudProvisioner)
        clouds.select_provider.return_value = "aws"
        cloud_node = Node(ip="10.0.0.100", ncpus=4, cloud="aws")
        clouds.allocate = AsyncMock(return_value=cloud_node)

        start_on_machine = AsyncMock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            gateway=gateway,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        assert result is False  # Cloud path returns False

        # tracker.add called
        tracker.add.assert_called_once_with(todo_task.task_id)

        # select_provider called with platforms and current counts
        clouds.select_provider.assert_called_once_with(["linux"], {})

        # tmp node inserted before cloud allocate
        uow.nodes.add_tmp.assert_called_once_with("aws")

        # cloud allocate called with provider name
        clouds.allocate.assert_called_once_with("aws")

        # final persist: add cloud node + remove tmp
        uow.nodes.add.assert_called_once_with(cloud_node)
        uow.nodes.remove.assert_called_once_with("tmp-10.0.0.100")

        # commit called at least twice (add_tmp + final persist)
        assert uow.commit.call_count >= 2

        # tracker.discard NOT called on happy cloud path (deferred to consume)
        tracker.discard.assert_not_called()

    async def test_allocate_task_cloud_fallback_failure_cleanup(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """[11.6c] Cloud allocate fails -> tmp-node removed, tracker discarded, error re-raised."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        gateway = MagicMock()
        gateway.list_free = MagicMock(return_value=[])

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes = AsyncMock()
        uow.nodes.list_all = AsyncMock(return_value=[])
        uow.nodes.add_tmp = AsyncMock(return_value="tmp-10.0.0.100")
        uow.nodes.add = AsyncMock()
        uow.nodes.remove = AsyncMock()
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.commit = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = True

        allocation_lock = asyncio.Lock()

        clouds = MagicMock(spec=CloudProvisioner)
        clouds.select_provider.return_value = "aws"
        clouds.allocate = AsyncMock(side_effect=CloudAllocateError("VM create failed"))

        start_on_machine = AsyncMock()

        with pytest.raises(CloudAllocateError):
            await allocate_task(
                task_id=todo_task.task_id,
                engines=engines,
                uow_factory=uow_factory,
                gateway=gateway,
                clouds=clouds,
                start_task_on_machine=start_on_machine,
                tracker=tracker,
                allocation_lock=allocation_lock,
            )

        # tmp-node was inserted
        uow.nodes.add_tmp.assert_called_once_with("aws")

        # tmp-node removed in cleanup UoW
        uow.nodes.remove.assert_called_once_with("tmp-10.0.0.100")

        # commit called for add_tmp and remove
        assert uow.commit.call_count >= 2

        # tracker.discard called after cleanup
        tracker.discard.assert_called_once_with(todo_task.task_id)

        # cloud node was NOT added (failed before final persist)
        uow.nodes.add.assert_not_called()

    async def test_allocate_task_dedup_returns_false(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """[11.6d] tracker.add returns False -> returns early, no cloud ops."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        gateway = MagicMock()
        gateway.list_free = MagicMock(return_value=[])

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = False  # Already in-flight

        allocation_lock = asyncio.Lock()
        clouds = MagicMock(spec=CloudProvisioner)
        start_on_machine = AsyncMock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            gateway=gateway,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        assert result is False

        # select_provider NOT called
        clouds.select_provider.assert_not_called()
        # allocate NOT called
        clouds.allocate.assert_not_called()
        # no DB writes
        uow.tasks.save.assert_not_called()
        uow.commit.assert_not_called()
        # tracker.discard NOT called (no slot was taken)
        tracker.discard.assert_not_called()

    async def test_allocate_task_throttle_returns_none(
        self,
        todo_task: Task,
        engine: Engine,
    ) -> None:
        """[11.6e] select_provider returns None -> tracker.discard, returns False, no tmp-node."""
        engines = MagicMock(spec=EngineRepository)
        engines.get.return_value = engine

        gateway = MagicMock()
        gateway.list_free = MagicMock(return_value=[])

        uow = AsyncMock()
        uow.tasks = AsyncMock()
        uow.tasks.get = AsyncMock(return_value=todo_task)
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes = AsyncMock()
        uow.nodes.list_all = AsyncMock(return_value=[])
        uow.collect_events = AsyncMock(return_value=[])
        uow.publish_events = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        tracker = MagicMock(spec=AllocationTracker)
        tracker.add.return_value = True

        allocation_lock = asyncio.Lock()
        clouds = MagicMock(spec=CloudProvisioner)
        clouds.select_provider.return_value = None  # Throttle/no capacity
        start_on_machine = AsyncMock()

        result = await allocate_task(
            task_id=todo_task.task_id,
            engines=engines,
            uow_factory=uow_factory,
            gateway=gateway,
            clouds=clouds,
            start_task_on_machine=start_on_machine,
            tracker=tracker,
            allocation_lock=allocation_lock,
        )

        assert result is False

        # select_provider was called
        clouds.select_provider.assert_called_once()
        # allocate NOT called
        clouds.allocate.assert_not_called()
        # NO tmp-node insertion
        uow.nodes.add_tmp.assert_not_called()
        # tracker.discard called (releases the slot since no provider)
        tracker.discard.assert_called_once_with(todo_task.task_id)


# =============================================================================
# consume_task  (2 tests)
# =============================================================================
# consume_task  (2 tests)
# =============================================================================


class TestConsumeTask:
    """consume_task — download outputs, mark DONE or ERROR."""

    @pytest.fixture
    def gateway_mock(self) -> MagicMock:
        gateway = MagicMock()
        gateway.download_outputs = AsyncMock(return_value=([], []))
        return gateway

    async def _run_consume(
        self,
        ip: str,
        gateway: MagicMock,
        task: Task,
        uow_factory: Callable[[], AbstractUnitOfWork],
        engines: EngineRepository,
        local_tasks_dir: Path,
        tracker: MagicMock,
    ) -> None:
        await consume_task(
            task_id=task.task_id,
            ip=ip,
            gateway=gateway,
            engines=engines,
            uow_factory=uow_factory,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

    async def test_consume_task_download_success_marks_done(
        self,
        gateway_mock: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """All output files downloaded -> save DONE + cloud notified."""
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
            gateway=gateway_mock,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # download_outputs called with correct params
        gateway_mock.download_outputs.assert_called_once()
        assert gateway_mock.download_outputs.call_args[1]["ip"] == "10.0.0.1"
        assert (
            gateway_mock.download_outputs.call_args[1]["remote_dir"]
            == "/remote/tasks/20250101_120000_42"
        )
        assert gateway_mock.download_outputs.call_args[1]["task_id"] == 1
        # DB saved with DONE status
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is None
        uow.commit.assert_called_once()
        # tracker.discard called instead of clouds.mark_task_done
        tracker.discard.assert_called_once_with(1)

    async def test_consume_task_download_failure_marks_error(
        self,
        gateway_mock: MagicMock,
        running_task: Task,
        mock_engine_repo: MagicMock,
    ) -> None:
        """Download returns errors -> save DONE with error."""
        gateway_mock.download_outputs = AsyncMock(
            return_value=([], [("/remote/file", OSError("Connection refused"))])
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
            gateway=gateway_mock,
            task=running_task,
            uow_factory=uow_factory,
            engines=mock_engine_repo,
            local_tasks_dir=local_tasks_dir,
            tracker=tracker,
        )

        # save was called with DONE + error
        uow.tasks.save.assert_called_once()
        saved_task: Task = uow.tasks.save.call_args[0][0]
        assert saved_task.status == TaskStatus.DONE
        assert saved_task.context.error is not None
        # tracker.discard called on failure path too
        tracker.discard.assert_called_once_with(1)


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

        # free_since (monotonic) is well beyond tolerance so the node qualifies
        idle_machines = {"10.0.0.1": time.monotonic() - 3600}

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

        idle_machines = {"10.0.0.1": time.monotonic() - 3600}

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


# =============================================================================
# deallocate_node bracketing (2 tests)
# =============================================================================


class TestDeallocateNodeBracketing:
    """deallocate_node — disable+remove bracketing around cloud delete."""

    async def test_bracketing_order_disable_cloud_delete_remove(self) -> None:
        """[12.4] disable+commit -> cloud deallocate -> remove+commit ordering."""
        node = Node(ip="10.0.0.1", ncpus=4, cloud="aws")
        gateway = MagicMock()
        gateway.contains.return_value = False  # Skip disconnect

        calls: list[str] = []

        uow = AsyncMock()
        uow.nodes.disable = AsyncMock(side_effect=lambda ip: calls.append("disable"))
        uow.nodes.remove = AsyncMock(side_effect=lambda ip: calls.append("remove"))
        uow.commit = AsyncMock(side_effect=lambda: calls.append("commit"))
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        clouds = MagicMock(spec=CloudProvisioner)
        clouds.deallocate = AsyncMock(
            side_effect=lambda c, ip: calls.append("deallocate")
        )

        await deallocate_node(
            node=node, gateway=gateway, clouds=clouds, uow_factory=uow_factory
        )

        assert calls == ["disable", "commit", "deallocate", "remove", "commit"]

    async def test_failure_in_cloud_delete_leaves_node_disabled(self) -> None:
        """[12.4] clouds.deallocate raises -> node stays disabled, remove NOT called."""
        node = Node(ip="10.0.0.1", ncpus=4, cloud="aws")
        gateway = MagicMock()
        gateway.contains.return_value = False

        calls: list[str] = []

        uow = AsyncMock()
        uow.nodes.disable = AsyncMock(side_effect=lambda ip: calls.append("disable"))
        uow.nodes.remove = AsyncMock(side_effect=lambda ip: calls.append("remove"))
        uow.commit = AsyncMock(side_effect=lambda: calls.append("commit"))
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        clouds = MagicMock(spec=CloudProvisioner)
        clouds.deallocate = AsyncMock(
            side_effect=CloudAllocateError("VM deletion failed")
        )

        with pytest.raises(CloudAllocateError):
            await deallocate_node(
                node=node,
                gateway=gateway,
                clouds=clouds,
                uow_factory=uow_factory,
            )

        # disable was called and committed
        assert "disable" in calls
        assert "commit" in calls
        # remove was NOT called (exception before it)
        assert "remove" not in calls
        assert calls == ["disable", "commit"]

    async def test_remove_failure_after_cloud_delete_is_logged_not_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """[review-hardening] remove UoW fails after clouds.deallocate succeeded -> exception swallowed, REMOVE_FAILED logged; cloud VM is gone so worker stays alive for reconciliation."""
        node = Node(ip="10.0.0.1", ncpus=4, cloud="aws")
        gateway = MagicMock()
        gateway.contains.return_value = False

        uow = AsyncMock()
        uow.nodes.disable = AsyncMock()
        uow.nodes.remove = AsyncMock()
        # First commit (disable) succeeds; second commit (remove) fails.
        uow.commit = AsyncMock(side_effect=[None, RuntimeError("remove db lost")])
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=False)

        def uow_factory() -> AbstractUnitOfWork:
            return uow

        clouds = MagicMock(spec=CloudProvisioner)
        clouds.deallocate = AsyncMock()

        with caplog.at_level(
            "ERROR", logger="yascheduler.application.deallocate_nodes"
        ):
            # Must not raise — the cloud VM is already gone.
            await deallocate_node(
                node=node,
                gateway=gateway,
                clouds=clouds,
                uow_factory=uow_factory,
            )

        # Cloud delete happened; disable happened; remove attempted.
        clouds.deallocate.assert_awaited_once_with("aws", "10.0.0.1")
        uow.nodes.disable.assert_awaited_once_with("10.0.0.1")
        uow.nodes.remove.assert_awaited_once_with("10.0.0.1")
        # Reconciliation marker logged.
        assert any(
            "REMOVE_FAILED" in r.message and "10.0.0.1" in r.message
            for r in caplog.records
        )

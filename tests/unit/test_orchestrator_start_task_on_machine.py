# FILE: tests/unit/test_orchestrator_start_task_on_machine.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for Orchestrator._start_task_on_machine ncpus resolution.
#   SCOPE: Explicit None-check ncpus resolution: static value, None fallback, absent node fallback.
#   DEPENDS: M-APPLICATION-ORCHESTRATOR
#   LINKS: M-APPLICATION-ORCHESTRATOR
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestStartTaskOnMachine - _start_task_on_machine ncpus resolution via explicit None-check
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - node-ncpus-as-config slice 5: extracted from test_application_orchestrator.py to stay under 1000-line limit.
# END_CHANGE_SUMMARY
#
"""Unit tests for Orchestrator._start_task_on_machine ncpus resolution.

Tests cover:
- Node.ncpus == 8 -> static value used, session.get_cpu_cores() NOT called
- Node.ncpus is None -> session.get_cpu_cores() called, result flows to deployer
- Node absent (get_by_id returns None) -> session.get_cpu_cores() called
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.application.allocation_tracker import AllocationTracker
from yascheduler.application.orchestrator import Orchestrator
from yascheduler.domain import Engine, EngineRepository, LocalSettings, RemoteDefaults
from yascheduler.domain.model import NodeId, Task, TaskId, TaskStatus
from yascheduler.entrypoints import Config
from yascheduler.infra.persistence import PostgresDbConfig

if TYPE_CHECKING:
    from yascheduler.application.uow import AbstractUnitOfWork


# =============================================================================
# Helpers
# =============================================================================


def _make_task(**overrides: Any) -> Task:  # noqa: ANN401
    """Build a Task with default typed fields; overrides win."""
    base: dict[str, Any] = dict(
        task_id=TaskId(1),
        engine="test_engine",
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
        label="test",
        local_folder=None,
        remote_folder=None,
        webhook_url=None,
        webhook_custom_params={},
        error=None,
        extra={},
        status=TaskStatus.TO_DO,
        allocated_node_id=None,
    )
    base.update(overrides)
    return Task(**base)  # type: ignore[arg-type]


def make_orchestrator() -> Orchestrator:
    """Create an Orchestrator with all dependencies mocked."""
    local = MagicMock(spec=LocalSettings)
    local.conn_machine_pending = 10
    local.allocate_pending = 5
    local.consume_pending = 3
    local.deallocate_pending = 2
    local.webhook_reqs_limit = 5
    local.conn_machine_limit = 1
    local.allocate_limit = 3
    local.consume_limit = 2
    local.deallocate_limit = 1

    remote = MagicMock(spec=RemoteDefaults)
    remote.tasks_dir = PurePosixPath("/tmp/tasks")
    remote.data_dir = PurePosixPath("/tmp/data")
    remote.engines_dir = PurePosixPath("/tmp/engines")
    remote.username = "root"

    config = MagicMock(spec=Config)
    config.local = local
    config.remote = remote
    config.clouds = []
    config.db = MagicMock(spec=PostgresDbConfig)

    mock_uow = AsyncMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)

    def uow_factory() -> AbstractUnitOfWork:
        return mock_uow

    clouds = AsyncMock()
    repository = MagicMock()
    repository.__len__ = MagicMock(return_value=1)
    repository.disconnect_all = AsyncMock()
    task_deployer = MagicMock()
    output_downloader = MagicMock()
    occupancy_checker = MagicMock()

    engine = MagicMock(spec=Engine, sleep_interval=0)
    engine.name = "test_engine"
    engines = MagicMock(spec=EngineRepository)
    engines.values.return_value = [engine]

    orch = Orchestrator(
        local_settings=config.local,
        remote_defaults=config.remote,
        uow_factory=uow_factory,
        clouds=clouds,
        repository=repository,
        task_deployer=task_deployer,
        output_downloader=output_downloader,
        occupancy_checker=occupancy_checker,
        engines=engines,
        config_clouds=[],
        local_tasks_dir=Path("/tmp"),
        allocation_tracker=AllocationTracker(),
        active_clouds=[],
        allocation_lock=MagicMock(),
        list_private_keys_fn=lambda _keys_dir: [],
    )
    return orch


# =============================================================================
# Tests
# =============================================================================


class TestStartTaskOnMachine:
    """_start_task_on_machine resolves ncpus via explicit None-check."""

    @pytest.mark.asyncio
    async def test_uses_static_ncpus_when_node_has_value(self) -> None:
        """Node.ncpus == 8 -> session.get_cpu_cores() NOT called, 8 flows to deployer."""
        from yascheduler.domain.model import Node

        orch = make_orchestrator()
        orch._task_deployer.start_task_on_machine = AsyncMock(return_value=True)  # type: ignore[method-assign]

        session = AsyncMock()
        session.get_cpu_cores = AsyncMock(return_value=4)

        engine = MagicMock()

        task = _make_task(
            task_id=TaskId(1),
            engine="test_engine",
            status=TaskStatus.TO_DO,
            allocated_node_id=NodeId(42),
        )

        node = Node(node_id=NodeId(42), hostname="test", ncpus=8)
        mock_uow = AsyncMock()
        mock_uow.nodes.get_by_id = AsyncMock(return_value=node)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        result = await orch._start_task_on_machine(session, engine, task)

        assert result is True
        session.get_cpu_cores.assert_not_called()
        orch._task_deployer.start_task_on_machine.assert_awaited_once_with(
            session, engine, task, 8, orch._remote_defaults.engines_dir
        )

    @pytest.mark.asyncio
    async def test_discovers_ncpus_when_node_has_none(self) -> None:
        """Node.ncpus is None -> session.get_cpu_cores() called, its return value flows to deployer."""
        from yascheduler.domain.model import Node

        orch = make_orchestrator()
        orch._task_deployer.start_task_on_machine = AsyncMock(return_value=True)  # type: ignore[method-assign]

        session = AsyncMock()
        session.get_cpu_cores = AsyncMock(return_value=4)

        engine = MagicMock()

        task = _make_task(
            task_id=TaskId(1),
            engine="test_engine",
            status=TaskStatus.TO_DO,
            allocated_node_id=NodeId(42),
        )

        node = Node(node_id=NodeId(42), hostname="test", ncpus=None)
        mock_uow = AsyncMock()
        mock_uow.nodes.get_by_id = AsyncMock(return_value=node)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        result = await orch._start_task_on_machine(session, engine, task)

        assert result is True
        session.get_cpu_cores.assert_awaited_once()
        orch._task_deployer.start_task_on_machine.assert_awaited_once_with(
            session, engine, task, 4, orch._remote_defaults.engines_dir
        )

    @pytest.mark.asyncio
    async def test_discovers_ncpus_when_node_absent(self) -> None:
        """Node is absent (get_by_id returns None) -> session.get_cpu_cores() called."""
        orch = make_orchestrator()
        orch._task_deployer.start_task_on_machine = AsyncMock(return_value=True)  # type: ignore[method-assign]

        session = AsyncMock()
        session.get_cpu_cores = AsyncMock(return_value=4)

        engine = MagicMock()

        task = _make_task(
            task_id=TaskId(1),
            engine="test_engine",
            status=TaskStatus.TO_DO,
            allocated_node_id=NodeId(42),
        )

        mock_uow = AsyncMock()
        mock_uow.nodes.get_by_id = AsyncMock(return_value=None)
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock(return_value=False)
        orch._uow_factory = lambda: mock_uow  # type: ignore[method-assign]

        result = await orch._start_task_on_machine(session, engine, task)

        assert result is True
        session.get_cpu_cores.assert_awaited_once()
        orch._task_deployer.start_task_on_machine.assert_awaited_once_with(
            session, engine, task, 4, orch._remote_defaults.engines_dir
        )

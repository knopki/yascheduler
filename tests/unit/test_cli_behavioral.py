"""Behavioral CLI test helpers — shared mock factories.

Shared mock factories for Config/CLIDeps/UoW/Task. Each behavioral test subject
(check_status, show_nodes, submit, manage_node) has graduated to a dedicated test file.
"""
# region MODULE_CONTRACT
# PURPOSE: Behavioral CLI test helpers — shared mock factories for Config/CLIDeps/UoW/Task.
# SCOPE: Shared mock factories for Config/CLIDeps/UoW/Task retained for behavioral CLI tests.
# KEYWORDS: mock factories, Config, CLIDeps, UoW, CLI behavioral tests
# endregion MODULE_CONTRACT

from __future__ import annotations

from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock

from yascheduler.domain import Engine, EngineRepository
from yascheduler.domain.model import NodeId, Task, TaskId, TaskStatus
from yascheduler.entrypoints.di import CLIDeps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_config() -> MagicMock:
    """Return a MagicMock Config with all expected attributes."""
    engine = Engine(
        name="g09",
        spawn="run.sh",
        input_files=("input",),
        output_files=("OUTPUT",),
        platforms=("linux",),
        check_cmd="echo",
        check_pname=None,
    )

    engines = MagicMock(spec=EngineRepository)
    engines.get = MagicMock(return_value=engine)

    config = MagicMock()
    config.engines = engines
    config.clouds = []
    config.remote.username = "root"
    config.remote.engines_dir = "/opt/engines"
    config.remote.tasks_dir = PurePosixPath("/tmp/tasks")
    config.local.webhook_url = None
    config.local.data_dir = "/tmp"
    config.db = MagicMock()
    return config


def make_mock_uow() -> AsyncMock:
    """Return an AsyncMock UoW with .tasks and .nodes sub-mocks."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.tasks = AsyncMock()
    uow.nodes = AsyncMock()
    uow.commit = AsyncMock()
    return uow


def make_mock_deps(config: MagicMock, uow: AsyncMock) -> MagicMock:
    """Return a MagicMock CLIDeps wired to the given uow."""
    deps = MagicMock(spec=CLIDeps)
    deps.uow_factory = MagicMock(return_value=uow)
    deps.submit = AsyncMock(return_value=42)
    deps.engines = config.engines
    return deps


def make_task(
    task_id: int = 1,
    status: TaskStatus = TaskStatus.RUNNING,
    label: str = "test",
    allocated_node_id: NodeId | None = None,
) -> Task:
    """Return a Task domain object with sensible defaults."""
    from datetime import datetime

    return Task(
        task_id=TaskId(task_id),
        label=label,
        engine="g09",
        remote_folder="/tmp/remote",
        local_folder="/tmp/local",
        webhook_url=None,
        webhook_custom_params={},
        error=None,
        extra={},
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
        status=status,
        allocated_node_id=allocated_node_id,
    )

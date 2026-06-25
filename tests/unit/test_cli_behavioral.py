# FILE: tests/unit/test_cli_behavioral.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Behavioral CLI test helpers — shared mock factories for Config/CLIDeps/UoW/Task.
#   SCOPE: Mock helpers retained for behavioral CLI tests. check_status moved to
#          entrypoints/cli/check_status.py in relocate-check-status-command and is covered by
#          tests/unit/test_cli_check_status.py. show_nodes, submit, and manage_node likewise
#          graduated to tests/unit/test_cli_show_nodes.py, test_cli_submit.py, and
#          test_cli_manage_node.py. No behavioral test class remains in this file.
#   DEPENDS: M-CLI-COMMANDS, M-DI, M-DOMAIN-MODEL
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   make_mock_config - MagicMock Config with all expected attributes
#   make_mock_uow - AsyncMock UoW with .tasks and .nodes sub-mocks
#   make_mock_deps - MagicMock CLIDeps wired to the given uow
#   make_task - Task domain object with sensible defaults
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Drop TestCheckStatus (check_status moved to entrypoints/cli/check_status.py in relocate-check-status-command; covered by tests/unit/test_cli_check_status.py). Shared mock helpers retained.
#   PREVIOUS_CHANGE: v1.5.0 - Drop TestManageNode (manage_node moved to entrypoints/cli/manage_node.py in relocate-manage-node-change; covered by tests/unit/test_cli_manage_node.py).
# END_CHANGE_SUMMARY

"""Behavioral CLI test helpers — shared mock factories.

Shared mock factories for Config/CLIDeps/UoW/Task. Each behavioral test subject
(check_status, show_nodes, submit, manage_node) has graduated to a dedicated test file.
"""

from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock

from yascheduler.config import Engine, EngineRepository
from yascheduler.di import CLIDeps
from yascheduler.domain.model import Task, TaskContext, TaskStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_config() -> MagicMock:
    """Return a MagicMock Config with all expected attributes."""
    engine = MagicMock(spec=Engine)
    engine.name = "g09"
    engine.spawn = "run.sh"
    engine.input_files = ("input",)
    engine.output_files = ("OUTPUT",)
    engine.platforms = ("linux",)
    engine.check_cmd = "echo"
    engine.check_pname = None

    engines = MagicMock(spec=EngineRepository)
    engines.get = MagicMock(return_value=engine)

    config = MagicMock()
    config.engines = engines
    config.clouds = []
    config.remote.username = "root"
    config.remote.engines_dir = "/opt/engines"
    config.remote.tasks_dir = PurePosixPath("/tmp/tasks")
    config.local.get_private_keys = MagicMock(return_value=[])
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
    deps.remote_tasks_dir = PurePosixPath("/tmp/tasks")
    return deps


def make_task(
    task_id: int = 1,
    status: TaskStatus = TaskStatus.RUNNING,
    label: str = "test",
    ip: str = "10.0.0.1",
) -> Task:
    """Return a Task domain object with sensible defaults."""
    return Task(
        task_id=task_id,
        label=label,
        context=TaskContext(
            engine="g09",
            remote_folder="/tmp/remote",
            local_folder="/tmp/local",
        ),
        status=status,
        allocated_ip=ip,
    )

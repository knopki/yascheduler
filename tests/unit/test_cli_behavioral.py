# FILE: tests/unit/test_cli_behavioral.py
# VERSION: 1.5.0
# START_MODULE_CONTRACT
#   PURPOSE: Behavioral CLI tests — exercise CLI function bodies with mocked DI stack.
#   SCOPE: check_status function body tests with mocked Config/CLIDeps/UoW (show_nodes moved to entrypoints/cli/show_nodes.py in relocate-show-nodes-command and is covered by tests/unit/test_cli_show_nodes.py; submit moved to entrypoints/cli/submit.py in relocate-submit-command and is covered by tests/unit/test_cli_submit.py; manage_node moved to entrypoints/cli/manage_node.py in relocate-manage-node-command and is covered by tests/unit/test_cli_manage_node.py).
#   DEPENDS: M-CLI-COMMANDS, M-DI, M-DOMAIN-MODEL
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCheckStatus - Behavioral tests for check_status CLI command
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.5.0 - Drop TestManageNode (manage_node moved to entrypoints/cli/manage_node.py in relocate-manage-node-command; covered by tests/unit/test_cli_manage_node.py).
#   PREVIOUS_CHANGE: v1.4.0 - Drop TestSubmit (submit moved to entrypoints/cli/submit.py in relocate-submit-command; covered by tests/unit/test_cli_submit.py).
# END_CHANGE_SUMMARY

"""Behavioral CLI tests — exercise CLI function bodies with mocked DI stack.

Calls each CLI command function with patched sys.argv, Config, make_cli_deps,
and UoW to verify output and mock call assertions without real DB/SSH.
"""

import importlib
from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.config import Engine, EngineRepository
from yascheduler.di import CLIDeps
from yascheduler.domain.model import Task, TaskContext, TaskStatus

check_status_mod = importlib.import_module("yascheduler.infra.cli.check_status")

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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckStatus:
    """Behavioral tests for the ``check_status`` CLI command."""

    def test_check_status_default_listing(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Default mode prints task_id and status name for RUNNING and TO_DO tasks."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, label="job_a"),
                make_task(task_id=2, status=TaskStatus.TO_DO, label="job_b"),
            ]
        )
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yastatus"]),
            patch.object(
                check_status_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(check_status_mod, "make_cli_deps", return_value=deps),
        ):
            check_status_mod.check_status()

        out, _ = capsys.readouterr()
        assert "1   RUNNING" in out
        assert "2   TO_DO" in out

    def test_check_status_info_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Info mode (-i) prints tab-separated task details."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(
                    task_id=1, status=TaskStatus.RUNNING, label="job_a", ip="10.0.0.1"
                ),
            ]
        )
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yastatus", "-i"]),
            patch.object(
                check_status_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(check_status_mod, "make_cli_deps", return_value=deps),
        ):
            check_status_mod.check_status()

        out, _ = capsys.readouterr()
        assert "task_id=1" in out
        assert "status=RUNNING" in out
        assert "label=job_a" in out
        assert "ip=10.0.0.1" in out
        # Verify tab-separated format
        assert "\t" in out

    def test_check_status_job_filter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Job filter (-j) calls list_by_jobs and prints results."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.tasks.list_by_jobs = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, label="specific_job"),
            ]
        )
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yastatus", "-j", "1", "2"]),
            patch.object(
                check_status_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(check_status_mod, "make_cli_deps", return_value=deps),
        ):
            check_status_mod.check_status()

        uow.tasks.list_by_jobs.assert_called_once_with(job_ids=["1", "2"])
        out, _ = capsys.readouterr()
        assert "1   RUNNING" in out

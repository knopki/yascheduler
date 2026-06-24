# FILE: tests/unit/test_cli_behavioral.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Behavioral CLI tests — exercise CLI function bodies with mocked DI stack.
#   SCOPE: submit, check_status, manage_node function body tests with mocked Config/CLIDeps/UoW (show_nodes moved to entrypoints/cli/show_nodes.py in relocate-show-nodes-command and is covered by tests/unit/test_cli_show_nodes.py).
#   DEPENDS: M-CLI-COMMANDS, M-DI, M-DOMAIN-MODEL
#   LINKS: M-CLI-COMMANDS, M-DI
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestSubmit - Behavioral tests for submit CLI command
#   TestCheckStatus - Behavioral tests for check_status CLI command
#   TestManageNode - Behavioral tests for manage_node CLI command
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Drop TestShowNodes (show_nodes moved to entrypoints/cli/show_nodes.py in relocate-show-nodes-command; covered by tests/unit/test_cli_show_nodes.py).
#   PREVIOUS_CHANGE: v1.2.0 - Switch patch calls to patch.object with explicit module refs (fixes mock resolution on Python 3.9-3.12 where cli.__init__ re-export shadows submodules).
# END_CHANGE_SUMMARY

"""Behavioral CLI tests — exercise CLI function bodies with mocked DI stack.

Calls each CLI command function with patched sys.argv, Config, make_cli_deps,
and UoW to verify output and mock call assertions without real DB/SSH.
"""

import importlib
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.config import Engine, EngineRepository
from yascheduler.di import CLIDeps
from yascheduler.domain.model import Node, Task, TaskContext, TaskStatus

submit_mod = importlib.import_module("yascheduler.infra.cli.submit")
check_status_mod = importlib.import_module("yascheduler.infra.cli.check_status")
manage_node_mod = importlib.import_module("yascheduler.infra.cli.manage_node")

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


class TestSubmit:
    """Behavioral tests for the ``submit`` CLI command."""

    def test_submit_happy_path(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Submit a valid script: prints task ID, calls deps.submit with correct args."""
        script = tmp_path / "test.in"
        script.write_text("LABEL = Test job\nENGINE = g09\n")

        # engine.input_files = ("input",) — create it so submit can read it
        (tmp_path / "input").write_text("dummy input")
        monkeypatch.chdir(tmp_path)

        config = make_mock_config()
        uow = make_mock_uow()
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yasubmit", str(script)]),
            patch.object(submit_mod.Config, "from_config_parser", return_value=config),
            patch.object(submit_mod, "make_cli_deps", return_value=deps),
        ):
            submit_mod.submit()

        out, _ = capsys.readouterr()
        assert "42" in out.strip()

        deps.submit.assert_called_once()
        call_args = deps.submit.call_args
        assert call_args[0][0] == "Test job"  # label
        assert call_args[0][2] == "g09"  # engine_name
        assert "local_folder" in call_args[0][1]  # metadata

    def test_submit_missing_script(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Non-existent script raises ValueError with 'not a file'."""
        config = make_mock_config()
        uow = make_mock_uow()
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yasubmit", "/nonexistent/script.in"]),
            patch.object(submit_mod.Config, "from_config_parser", return_value=config),
            patch.object(submit_mod, "make_cli_deps", return_value=deps),
        ):
            with pytest.raises(ValueError, match="not a file"):
                submit_mod.submit()

    def test_submit_no_engine_key(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Script without ENGINE= line raises ValueError."""
        script = tmp_path / "test.in"
        script.write_text("LABEL = Test job\nSOMETHING = else\n")

        config = make_mock_config()
        uow = make_mock_uow()
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yasubmit", str(script)]),
            patch.object(submit_mod.Config, "from_config_parser", return_value=config),
            patch.object(submit_mod, "make_cli_deps", return_value=deps),
        ):
            with pytest.raises(ValueError, match="not defined an engine"):
                submit_mod.submit()

    def test_submit_unsupported_engine(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Script with unknown ENGINE= raises ValueError 'not supported'."""
        script = tmp_path / "test.in"
        script.write_text("LABEL = Test\nENGINE = unknown\n")

        config = make_mock_config()
        config.engines.get = MagicMock(return_value=None)  # engine not found

        uow = make_mock_uow()
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yasubmit", str(script)]),
            patch.object(submit_mod.Config, "from_config_parser", return_value=config),
            patch.object(submit_mod, "make_cli_deps", return_value=deps),
        ):
            with pytest.raises(ValueError, match="not supported"):
                submit_mod.submit()


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


class TestManageNode:
    """Behavioral tests for the ``manage_node`` CLI command."""

    def test_manage_node_add_new(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Add a new host: calls SSHMachineGateway, adds node, prints 'Added host'."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(return_value=None)  # not in DB yet
        deps = make_mock_deps(config, uow)

        mock_gateway = AsyncMock()
        mock_gateway.connect = AsyncMock()
        mock_gateway.setup_node = AsyncMock()
        mock_gateway.disconnect = AsyncMock()

        with (
            patch("sys.argv", ["yanodes", "10.0.0.1"]),
            patch.object(
                manage_node_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(manage_node_mod, "make_cli_deps", return_value=deps),
            patch.object(
                manage_node_mod, "SSHMachineGateway", return_value=mock_gateway
            ),
        ):
            result = manage_node_mod.manage_node()

        # manage_node "add" path has no explicit return — implicit None
        assert result is None
        out, _ = capsys.readouterr()
        assert "Added host" in out

        uow.nodes.add.assert_called_once()
        added_node = uow.nodes.add.call_args[0][0]
        assert added_node.ip == "10.0.0.1"
        assert added_node.port == 22
        assert added_node.ncpus == 0

    def test_manage_node_add_existing(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Add a host already in DB: prints 'already in DB', returns False."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yanodes", "10.0.0.1"]),
            patch.object(
                manage_node_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(manage_node_mod, "make_cli_deps", return_value=deps),
        ):
            result = manage_node_mod.manage_node()

        assert result is False
        out, _ = capsys.readouterr()
        assert "already in DB" in out

    def test_manage_node_remove_hard(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Hard remove: marks running tasks DONE, removes node."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[1, 2])
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yanodes", "10.0.0.1", "--remove-hard"]),
            patch.object(
                manage_node_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(manage_node_mod, "make_cli_deps", return_value=deps),
        ):
            result = manage_node_mod.manage_node()

        assert result is True
        out, _ = capsys.readouterr()
        assert "now marked done" in out
        assert "Removed host" in out

        # Both running tasks marked DONE
        assert uow.tasks.update_status.call_count == 2
        uow.tasks.update_status.assert_any_call(1, TaskStatus.DONE)
        uow.tasks.update_status.assert_any_call(2, TaskStatus.DONE)
        uow.nodes.remove.assert_called_once_with("10.0.0.1")
        uow.commit.assert_called_once()

    def test_manage_node_remove_soft_with_tasks(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Soft remove with running tasks: disables node (not remove)."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[1])
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yanodes", "10.0.0.1", "--remove-soft"]),
            patch.object(
                manage_node_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(manage_node_mod, "make_cli_deps", return_value=deps),
        ):
            result = manage_node_mod.manage_node()

        assert result is True
        out, _ = capsys.readouterr()
        assert "prevent from assigning" in out
        assert "Prevented from assigning" in out

        uow.nodes.disable.assert_called_once_with("10.0.0.1")
        uow.nodes.remove.assert_not_called()
        uow.commit.assert_called_once()

    def test_manage_node_remove_soft_no_tasks(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Soft remove with no running tasks: removes node immediately."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[])
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yanodes", "10.0.0.1", "--remove-soft"]),
            patch.object(
                manage_node_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(manage_node_mod, "make_cli_deps", return_value=deps),
        ):
            result = manage_node_mod.manage_node()

        assert result is True
        out, _ = capsys.readouterr()
        assert "No tasks associated" in out
        assert "Removed host" in out

        uow.nodes.remove.assert_called_once_with("10.0.0.1")
        uow.nodes.disable.assert_not_called()
        uow.commit.assert_called_once()

    def test_manage_node_remove_nonexistent(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Remove a host not in DB: prints 'NOT in DB', returns False."""
        config = make_mock_config()
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(return_value=None)
        deps = make_mock_deps(config, uow)

        with (
            patch("sys.argv", ["yanodes", "nonexistent.host", "--remove-hard"]),
            patch.object(
                manage_node_mod.Config, "from_config_parser", return_value=config
            ),
            patch.object(manage_node_mod, "make_cli_deps", return_value=deps),
        ):
            result = manage_node_mod.manage_node()

        assert result is False
        out, _ = capsys.readouterr()
        assert "NOT in DB" in out

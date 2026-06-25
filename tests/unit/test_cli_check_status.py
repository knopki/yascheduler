# FILE: tests/unit/test_cli_check_status.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yastatus check_status() flag parsing, renderers, exit codes, and connection-params resolver.
#   SCOPE: check_status() and private helpers (_parse_status_args, _query_tasks, _render_default, _render_info,
#          _render_json, _resolve_conn_params, _render_view) with mocked Config/CLIDeps/UoW/SSHMachineGateway.
#   DEPENDS: M-ENTRYPOINTS-CLI-CHECK-STATUS
#   LINKS: M-ENTRYPOINTS-CLI-CHECK-STATUS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestCheckStatusParsing - --help, --bogus, -v/-i/--json mutex, -o requires -v
#   TestCheckStatusAiiDAContract - golden regression: default output parses via the AiiDA plugin's exact logic
#   TestCheckStatusDefault - default listing (RUNNING+TO_DO, DONE excluded) and -j filter
#   TestCheckStatusInfo - -i tab-separated renderer
#   TestCheckStatusJson - --json 9 raw-value fields, null placement for TO_DO, empty list, -j composition
#   TestCheckStatusExitCodes - exit 0 success, exit 1 on DB/config/unexpected errors
#   TestCheckStatusArgvInjection - argv parameter threads through to argparse (no sys.argv patch)
#   TestResolveConnParams - matching cloud jump host, static node fallback, node username/port passthrough
#   TestCheckStatusViewHappyPath - -v SSH tail path + lazy nodes lookup invariant for default/-i
#   TestCheckStatusQueryRenderSeparation - UoW closed before any SSH operation
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - consolidate-daemon-entrypoints: added --config/--log-level scenarios (--help lists them; --config /nonexistent exits 2; --log-level WARN exits 2; --log-level DEBUG sets root to DEBUG; --config /custom.conf passed to Config.from_config_parser; defaults CONFIG_FILE/WARNING).
#   PREVIOUS_CHANGE: v1.0.0 - Initial unit tests for relocated yastatus (entrypoints/cli/check_status.py) in relocate-check-status-command.
# END_CHANGE_SUMMARY

from __future__ import annotations

import importlib
import json as _json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.config import Engine, EngineRepository
from yascheduler.domain.model import Node, Task, TaskContext, TaskStatus
from yascheduler.entrypoints.di import CLIDeps

check_status_mod = importlib.import_module("yascheduler.entrypoints.cli.check_status")

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers (mirror tests/unit/test_cli_behavioral.py / test_cli_show_nodes.py)
# ---------------------------------------------------------------------------


def make_cloud(
    prefix: str,
    username: str = "root",
    jump_host: str | None = None,
    jump_username: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        prefix=prefix,
        username=username,
        jump_host=jump_host,
        jump_username=jump_username,
    )


def make_mock_config(
    clouds: list[SimpleNamespace] | None = None,
    remote_username: str = "root",
    remote_jump_host: str | None = None,
    remote_jump_username: str | None = None,
) -> MagicMock:
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
    config.clouds = clouds if clouds is not None else []
    config.remote.username = remote_username
    config.remote.jump_host = remote_jump_host
    config.remote.jump_username = remote_jump_username
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
    ip: str | None = "10.0.0.1",
    engine: str = "g09",
) -> Task:
    """Return a Task domain object with sensible defaults."""
    return Task(
        task_id=task_id,
        label=label,
        context=TaskContext(
            engine=engine,
            remote_folder="/tmp/remote",
            local_folder="/tmp/local",
        ),
        status=status,
        allocated_ip=ip,
    )


def make_mock_gateway(stdout: str = "remote output", returncode: int = 0) -> MagicMock:
    """Return a MagicMock SSHMachineGateway with async connect/disconnect/run_full."""
    gateway = MagicMock()
    gateway.connect = AsyncMock()
    gateway.disconnect = AsyncMock()
    state = MagicMock()
    gateway._get_machine_state = MagicMock(return_value=state)
    gateway.run_full = AsyncMock(
        return_value=MagicMock(returncode=returncode, stdout=stdout)
    )
    gateway.get_path = MagicMock(return_value=lambda folder: PurePosixPath(folder))
    gateway.get_quote = MagicMock(return_value=lambda s: s)
    return gateway


@pytest.fixture
def stub_config_deps(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, AsyncMock, MagicMock]:
    """Patch Config.from_config_parser and make_cli_deps for the module under test.

    Returns (config, uow, deps) so each test can wire its own node/task data.
    """
    config = make_mock_config()
    uow = make_mock_uow()
    deps = make_mock_deps(config, uow)
    monkeypatch.setattr(
        check_status_mod.Config, "from_config_parser", MagicMock(return_value=config)
    )
    monkeypatch.setattr(check_status_mod, "make_cli_deps", MagicMock(return_value=deps))
    return config, uow, deps


def _run(argv: list[str]) -> None:
    """Invoke check_status_mod.check_status(argv)."""
    check_status_mod.check_status(argv)


# ---------------------------------------------------------------------------
# Parsing / exit codes (task 9.4)
# ---------------------------------------------------------------------------


class TestCheckStatusParsing:
    """Flag parsing and argparse exit codes."""

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "usage: yastatus" in out
        assert "-j" in out and "--jobs" in out
        assert "-v" in out and "--view" in out
        assert "-i" in out and "--info" in out
        assert "-o" in out and "--convergence" in out
        assert "--json" in out

    def test_bogus_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--bogus"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_view_info_mutex_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["-v", "-i"])
        assert exc.value.code == 2

    def test_json_view_mutex_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--json", "-v"])
        assert exc.value.code == 2

    def test_json_info_mutex_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--json", "-i"])
        assert exc.value.code == 2

    def test_convergence_without_view_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["-o"])
        assert exc.value.code == 2

    def test_convergence_with_view_is_valid(self) -> None:
        # Does NOT raise; returns a Namespace with both flags set.
        args = check_status_mod._parse_status_args(["-o", "-v"])
        assert args.view is True
        assert args.convergence is True


# ---------------------------------------------------------------------------
# AiiDA-contract golden regression (task 9.5, design D9)
# ---------------------------------------------------------------------------


class TestCheckStatusAiiDAContract:
    """The default renderer's output must parse via the AiiDA plugin's exact logic."""

    def test_default_output_parses_like_aiida_plugin(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tasks = [
            make_task(task_id=1, status=TaskStatus.TO_DO),
            make_task(task_id=2, status=TaskStatus.RUNNING),
            make_task(task_id=3, status=TaskStatus.DONE),
        ]
        check_status_mod._render_default(tasks)
        out, _ = capsys.readouterr()

        # The AiiDA plugin's exact parse logic:
        job_list = [job.split() for job in out.split("\n") if job]
        parsed: dict[str, str] = {}
        for job_id, status in job_list:  # exactly 2 elements per line
            parsed[job_id] = status

        assert set(parsed.values()) <= {"TO_DO", "RUNNING", "DONE"}
        assert parsed == {"1": "TO_DO", "2": "RUNNING", "3": "DONE"}


# ---------------------------------------------------------------------------
# Default renderer + -j filter (task 9.6)
# ---------------------------------------------------------------------------


class TestCheckStatusDefault:
    """Default invocation: list_by_status({RUNNING, TO_DO}); -j calls list_by_jobs."""

    def test_default_lists_running_and_todo(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, label="job_a"),
                make_task(task_id=2, status=TaskStatus.TO_DO, label="job_b"),
            ]
        )

        _run([])  # no SystemExit on success

        uow.tasks.list_by_status.assert_called_once_with(
            statuses={TaskStatus.RUNNING, TaskStatus.TO_DO}
        )
        out, _ = capsys.readouterr()
        assert "1   RUNNING" in out
        assert "2   TO_DO" in out

    def test_default_excludes_done(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[make_task(task_id=1, status=TaskStatus.RUNNING)]
        )

        _run([])

        out, _ = capsys.readouterr()
        assert "DONE" not in out

    def test_jobs_filter_calls_list_by_jobs(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_jobs = AsyncMock(
            return_value=[make_task(task_id=1, status=TaskStatus.RUNNING, label="x")]
        )

        _run(["-j", "1", "2"])

        uow.tasks.list_by_jobs.assert_called_once_with(job_ids=["1", "2"])
        out, _ = capsys.readouterr()
        assert "1   RUNNING" in out


# ---------------------------------------------------------------------------
# Info renderer (task 9.7)
# ---------------------------------------------------------------------------


class TestCheckStatusInfo:
    """-i prints tab-separated task_id/status/label/ip."""

    def test_info_tab_separated(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(
                    task_id=1, status=TaskStatus.RUNNING, label="job_a", ip="10.0.0.1"
                ),
            ]
        )

        _run(["-i"])

        out, _ = capsys.readouterr()
        assert "task_id=1" in out
        assert "status=RUNNING" in out
        assert "label=job_a" in out
        assert "ip=10.0.0.1" in out
        assert "\t" in out


# ---------------------------------------------------------------------------
# JSON renderer (task 9.8)
# ---------------------------------------------------------------------------


class TestCheckStatusJson:
    """--json emits a list of 9-field objects with raw domain values."""

    def test_json_emits_list_with_nine_fields(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        node = Node(ip="10.0.0.1", ncpus=4, enabled=True, port=22, cloud="hetzner")
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )
        uow.nodes.get_by_ips = AsyncMock(return_value={"10.0.0.1": node})

        _run(["--json"])

        out, _ = capsys.readouterr()
        data = _json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 1
        obj = data[0]
        assert set(obj.keys()) == {
            "task_id",
            "status",
            "label",
            "allocated_ip",
            "port",
            "cloud",
            "engine",
            "local_folder",
            "remote_folder",
        }
        # Raw values: status name not int, port=22 not "-" or null, cloud string.
        assert obj["status"] == "RUNNING"
        assert obj["port"] == 22
        assert obj["cloud"] == "hetzner"
        assert obj["engine"] == "g09"
        assert obj["local_folder"] == "/tmp/local"
        assert obj["remote_folder"] == "/tmp/remote"
        # --json triggers the conditional nodes lookup (lazy-lookup invariant).
        uow.nodes.get_by_ips.assert_called_once()

    def test_json_fetches_nodes_by_ip(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )
        uow.nodes.get_by_ips = AsyncMock(
            return_value={"10.0.0.1": Node(ip="10.0.0.1", ncpus=4, port=22)}
        )

        _run(["--json"])

        uow.nodes.get_by_ips.assert_called_once()

    def test_json_todo_task_has_null_placement(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[make_task(task_id=5, status=TaskStatus.TO_DO, ip=None)]
        )
        uow.nodes.get_by_ips = AsyncMock(return_value={})

        _run(["--json"])

        out, _ = capsys.readouterr()
        data = _json.loads(out)
        obj = data[0]
        assert obj["allocated_ip"] is None
        assert obj["port"] is None
        assert obj["cloud"] is None
        # engine is always present (required field).
        assert obj["engine"] == "g09"

    def test_json_empty_result_is_empty_list(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])

        _run(["--json"])

        out, _ = capsys.readouterr()
        assert _json.loads(out) == []

    def test_json_composes_with_jobs(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_jobs = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )
        uow.nodes.get_by_ips = AsyncMock(
            return_value={"10.0.0.1": Node(ip="10.0.0.1", ncpus=4, port=22)}
        )

        _run(["--json", "-j", "1"])

        uow.tasks.list_by_jobs.assert_called_once_with(job_ids=["1"])
        out, _ = capsys.readouterr()
        assert _json.loads(out)  # non-empty JSON list


# ---------------------------------------------------------------------------
# Exit codes (task 9.9)
# ---------------------------------------------------------------------------


class TestCheckStatusExitCodes:
    """0/1/2 exit-code contract."""

    def test_exit_zero_on_success(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        # No SystemExit raised on success.
        _run([])

    def test_exit_one_on_db_error(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(side_effect=RuntimeError("db down"))
        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_exit_one_on_config_error(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            check_status_mod.Config,
            "from_config_parser",
            MagicMock(side_effect=RuntimeError("bad config")),
        )
        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_exit_one_on_unexpected_exception(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            check_status_mod,
            "make_cli_deps",
            MagicMock(side_effect=ValueError("unexpected")),
        )
        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err


# ---------------------------------------------------------------------------
# argv injection (task 9.10)
# ---------------------------------------------------------------------------


class TestCheckStatusArgvInjection:
    """The argv parameter is threaded through to argparse (no patch sys.argv)."""

    def test_argv_threaded_to_argparse(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])

        # sys.argv is NOT patched; the runner's sys.argv would not parse as valid
        # yastatus flags. Passing ["--json"] explicitly yields JSON output, proving
        # argv injection (otherwise argparse would read sys.argv and likely error).
        _run(["--json"])

        out, _ = capsys.readouterr()
        assert _json.loads(out) == []


# ---------------------------------------------------------------------------
# _resolve_conn_params (task 9.11)
# ---------------------------------------------------------------------------


class TestResolveConnParams:
    """Connection-params resolution mirrors orchestrator._connect_machine_consumer."""

    def test_matching_cloud_uses_cloud_jump_host(self) -> None:
        config = make_mock_config(
            clouds=[
                make_cloud(
                    "hetzner", jump_host="jump.example.com", jump_username="jumper"
                ),
            ],
            remote_jump_host="fallback.example.com",
            remote_jump_username="fallback",
        )
        node = Node(
            ip="10.0.0.1", ncpus=4, cloud="hetzner", username="yascheduler", port=2222
        )

        params = check_status_mod._resolve_conn_params(node, config)

        assert params.jump_host == "jump.example.com"
        assert params.jump_username == "jumper"

    def test_static_node_falls_back_to_config_remote(self) -> None:
        config = make_mock_config(
            clouds=[
                make_cloud(
                    "hetzner", jump_host="jump.example.com", jump_username="jumper"
                )
            ],
            remote_jump_host="fallback.example.com",
            remote_jump_username="fallback",
        )
        node = Node(ip="10.0.0.1", ncpus=4, cloud=None)

        params = check_status_mod._resolve_conn_params(node, config)

        assert params.jump_host == "fallback.example.com"
        assert params.jump_username == "fallback"

    def test_returns_node_username_not_cloud_username(self) -> None:
        config = make_mock_config(
            clouds=[make_cloud("hetzner", username="hcloud-user")],
        )
        node = Node(
            ip="10.0.0.1", ncpus=4, cloud="hetzner", username="yascheduler", port=22
        )

        params = check_status_mod._resolve_conn_params(node, config)

        assert params.username == "yascheduler"

    def test_returns_node_port(self) -> None:
        config = make_mock_config()
        node = Node(ip="10.0.0.1", ncpus=4, port=2222)

        params = check_status_mod._resolve_conn_params(node, config)

        assert params.port == 2222


# ---------------------------------------------------------------------------
# View mode happy path + lazy nodes lookup (task 9.12)
# ---------------------------------------------------------------------------


class TestCheckStatusViewHappyPath:
    """-v SSH tail path; default/-i do NOT fetch nodes (lazy lookup invariant)."""

    def test_view_connects_with_resolved_params_and_disconnects(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config, uow, _deps = stub_config_deps
        config.clouds = [
            make_cloud("hetzner", jump_host="jump.example.com", jump_username="jumper")
        ]
        node = Node(
            ip="10.0.0.1",
            ncpus=4,
            cloud="hetzner",
            username="yascheduler",
            port=2222,
        )
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )
        uow.nodes.get_by_ips = AsyncMock(return_value={"10.0.0.1": node})

        gateway = make_mock_gateway(stdout="OUTPUT TAIL")
        monkeypatch.setattr(
            check_status_mod, "SSHMachineGateway", MagicMock(return_value=gateway)
        )
        resolve_spy = MagicMock(wraps=check_status_mod._resolve_conn_params)
        monkeypatch.setattr(check_status_mod, "_resolve_conn_params", resolve_spy)

        _run(["-v"])

        # _resolve_conn_params called with the task's node.
        resolve_spy.assert_called_once()
        assert resolve_spy.call_args.args[0].ip == "10.0.0.1"
        # gateway.connect called with node username/port + cloud jump host.
        gateway.connect.assert_called_once()
        kwargs = gateway.connect.call_args.kwargs
        assert kwargs["username"] == "yascheduler"
        assert kwargs["port"] == 2222
        assert kwargs["jump_host"] == "jump.example.com"
        assert kwargs["jump_username"] == "jumper"
        # tails OUTPUT (run_full invoked) and disconnects.
        assert gateway.run_full.await_count == 1
        gateway.disconnect.assert_awaited()
        out, _ = capsys.readouterr()
        assert "OUTPUT TAIL" in out

    def test_view_fetches_nodes_by_ip(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )
        uow.nodes.get_by_ips = AsyncMock(
            return_value={"10.0.0.1": Node(ip="10.0.0.1", ncpus=4)}
        )
        monkeypatch.setattr(
            check_status_mod,
            "SSHMachineGateway",
            MagicMock(return_value=make_mock_gateway()),
        )

        _run(["-v"])

        uow.nodes.get_by_ips.assert_called_once()

    def test_default_does_not_fetch_nodes(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )

        _run([])

        uow.nodes.get_by_ips.assert_not_called()

    def test_info_does_not_fetch_nodes(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )

        _run(["-i"])

        uow.nodes.get_by_ips.assert_not_called()


# ---------------------------------------------------------------------------
# Query/render separation (task 9.13)
# ---------------------------------------------------------------------------


class TestCheckStatusQueryRenderSeparation:
    """The query-phase UoW is closed before any SSH operation begins."""

    def test_uow_closed_before_ssh_connect(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(
            return_value=[
                make_task(task_id=1, status=TaskStatus.RUNNING, ip="10.0.0.1")
            ]
        )
        uow.nodes.get_by_ips = AsyncMock(
            return_value={"10.0.0.1": Node(ip="10.0.0.1", ncpus=4)}
        )

        gateway = make_mock_gateway()
        monkeypatch.setattr(
            check_status_mod, "SSHMachineGateway", MagicMock(return_value=gateway)
        )

        # Attach both mocks to a single manager BEFORE running so their call order
        # is recorded in one unified list.
        manager = MagicMock()
        manager.attach_mock(uow.__aexit__, "uow_aexit")
        manager.attach_mock(gateway.connect, "gw_connect")

        _run(["-v"])

        names = [call[0] for call in manager.mock_calls]
        # Both must have been called, and the UoW exit must precede the SSH connect.
        assert "uow_aexit" in names
        assert "gw_connect" in names
        assert names.index("uow_aexit") < names.index("gw_connect")


# ---------------------------------------------------------------------------
# --config / --log-level scenarios (consolidate-daemon-entrypoints)
# ---------------------------------------------------------------------------


class TestCheckStatusConfigLogLevel:
    """--config and --log-level argparse + behavior scenarios (defaults WARNING)."""

    def test_help_lists_config_and_log_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "--config" in out
        assert "--log-level" in out

    def test_config_nonexistent_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--config", "/nonexistent.conf"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert "not a file" in err
        assert "/nonexistent.conf" in err

    def test_log_level_warn_rejected_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            check_status_mod._parse_status_args(["--log-level", "WARN"])
        assert exc.value.code == 2

    def test_log_level_debug_sets_root_to_debug(
        self,
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import logging

        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        root = logging.getLogger()
        original_level = root.level
        try:
            _run(["--log-level", "DEBUG"])
            assert root.level == logging.DEBUG
        finally:
            root.setLevel(original_level)

    def test_config_custom_passed_to_from_config_parser(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        custom_conf = tmp_path / "custom.conf"
        custom_conf.write_text("[local]")
        from_config_spy = MagicMock(return_value=make_mock_config())
        monkeypatch.setattr(
            check_status_mod.Config, "from_config_parser", from_config_spy
        )
        uow = make_mock_uow()
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        monkeypatch.setattr(
            check_status_mod,
            "make_cli_deps",
            MagicMock(return_value=make_mock_deps(make_mock_config(), uow)),
        )
        _run(["--config", str(custom_conf)])
        from_config_spy.assert_called_once_with(custom_conf)

    def test_default_config_is_config_file(
        self,
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yascheduler import CONFIG_FILE

        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        from_config_spy = MagicMock(return_value=make_mock_config())
        monkeypatch.setattr(
            check_status_mod.Config, "from_config_parser", from_config_spy
        )
        _run([])
        assert str(from_config_spy.call_args.args[0]) == str(CONFIG_FILE)

    def test_default_log_level_is_warning(
        self,
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import logging

        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        root = logging.getLogger()
        original_level = root.level
        try:
            _run([])
            assert root.level == logging.WARNING
        finally:
            root.setLevel(original_level)

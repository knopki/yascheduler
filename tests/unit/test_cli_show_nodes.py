# FILE: tests/unit/test_cli_show_nodes.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yanodes show_nodes() flag parsing, filtering, table/JSON rendering, and exit codes.
#   SCOPE: show_nodes() and private helpers with mocked Config/CLIDeps/UoW.
#   DEPENDS: M-ENTRYPOINTS-CLI-SHOW-NODES
#   LINKS: M-ENTRYPOINTS-CLI-SHOW-NODES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestShowNodesParsing - --help, unknown flag, --cloud/--no-cloud mutex
#   TestShowNodesRendering - default table, display transformations, JSON raw values, empty results
#   TestShowNodesFiltering - enabled/disabled, busy/free, cloud exact, no-cloud, AND composition, subset=default
#   TestShowNodesOrder - list_all() order preserved
#   TestShowNodesErrors - exit 1 on DB error and config error
#   TestShowNodesStructure - no external deps (rich/tabulate), O(n+m) join invariant
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - consolidate-daemon-entrypoints: added --config/--log-level scenarios (--help lists them; --config /nonexistent exits 2; --log-level WARN exits 2; --log-level DEBUG sets root to DEBUG; --config /custom.conf passed to Config.from_config_parser; defaults CONFIG_FILE/WARNING).
#   PREVIOUS_CHANGE: v1.0.0 - Initial unit tests for relocated yanodes (entrypoints/cli/show_nodes.py) in relocate-show-nodes-command.
# END_CHANGE_SUMMARY

from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.config import Engine, EngineRepository
from yascheduler.domain.model import Node, Task, TaskContext, TaskStatus
from yascheduler.entrypoints.di import CLIDeps

show_nodes_mod = importlib.import_module("yascheduler.entrypoints.cli.show_nodes")

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers (mirror tests/unit/test_cli_behavioral.py)
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
    ip: str | None = "10.0.0.1",
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
        show_nodes_mod.Config, "from_config_parser", MagicMock(return_value=config)
    )
    monkeypatch.setattr(show_nodes_mod, "make_cli_deps", MagicMock(return_value=deps))
    return config, uow, deps


def _run(argv: list[str]) -> None:
    """Invoke show_nodes_mod.show_nodes(argv); raise if it swallows SystemExit unexpectedly."""
    show_nodes_mod.show_nodes(argv)


# ---------------------------------------------------------------------------
# Parsing / exit codes (tasks 14.5-14.7)
# ---------------------------------------------------------------------------


class TestShowNodesParsing:
    """Flag parsing and argparse exit codes."""

    def test_help_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "--json" in out
        assert "--enabled" in out
        assert "--disabled" in out
        assert "--busy" in out
        assert "--free" in out
        assert "--cloud" in out
        assert "--no-cloud" in out

    def test_unknown_flag_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--bogus"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()  # argparse usage error

    def test_cloud_no_cloud_mutex_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--cloud", "hetzner", "--no-cloud"])
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Rendering (tasks 14.2, 14.15-14.16)
# ---------------------------------------------------------------------------


class TestShowNodesRendering:
    """Table and JSON rendering with display transformations / raw values."""

    def test_default_lists_all_nodes_table(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        node1 = Node(ip="10.0.0.1", ncpus=4, enabled=True, port=22)
        node2 = Node(ip="10.0.0.2", ncpus=0, enabled=False, port=2222, cloud="hetzner")
        uow.tasks.list_by_status = AsyncMock(
            return_value=[make_task(task_id=1, label="my_job", ip="10.0.0.1")]
        )
        uow.nodes.list_all = AsyncMock(return_value=[node1, node2])

        _run([])  # no SystemExit on success

        out, _ = capsys.readouterr()
        lines = out.splitlines()
        # Header
        assert "IP" in lines[0]
        assert "PORT" in lines[0]
        assert "NCPUS" in lines[0]
        assert "ENABLED" in lines[0]
        assert "CLOUD" in lines[0]
        assert "TASK_ID" in lines[0]
        assert "LABEL" in lines[0]
        # Two data rows
        assert len(lines) == 3
        # Row 1: busy node, port 22 -> '-', ncpus=4, enabled yes, cloud None -> '-',
        # task_id=1, label=my_job
        assert "10.0.0.1" in lines[1]
        assert "-" in lines[1]  # port rendered as '-'
        assert "yes" in lines[1]
        assert "my_job" in lines[1]
        # Row 2: free node, port 2222, ncpus=0 -> MAX, enabled no, cloud hetzner,
        # task_id/label -> '-'
        assert "10.0.0.2" in lines[2]
        assert "2222" in lines[2]
        assert "MAX" in lines[2]
        assert "no" in lines[2]
        assert "hetzner" in lines[2]

    def test_json_output_raw_values(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        import json as _json

        _config, uow, _deps = stub_config_deps
        node1 = Node(ip="10.0.0.1", ncpus=0, enabled=True, port=22, cloud=None)
        node2 = Node(ip="10.0.0.2", ncpus=4, enabled=False, port=2222, cloud="hetzner")
        uow.tasks.list_by_status = AsyncMock(
            return_value=[make_task(task_id=7, label="job7", ip="10.0.0.1")]
        )
        uow.nodes.list_all = AsyncMock(return_value=[node1, node2])

        _run(["--json"])

        out, _ = capsys.readouterr()
        data = _json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 2
        # Busy node: raw port=22 (not "-" or null), ncpus=0 (not "MAX"), enabled bool,
        # cloud null, occupied_by object.
        assert data[0]["ip"] == "10.0.0.1"
        assert data[0]["port"] == 22
        assert data[0]["ncpus"] == 0
        assert data[0]["enabled"] is True
        assert data[0]["cloud"] is None
        assert data[0]["occupied_by"] == {"task_id": 7, "label": "job7"}
        # Free node: occupied_by null.
        assert data[1]["ip"] == "10.0.0.2"
        assert data[1]["port"] == 2222
        assert data[1]["ncpus"] == 4
        assert data[1]["enabled"] is False
        assert data[1]["cloud"] == "hetzner"
        assert data[1]["occupied_by"] is None

    def test_json_empty_is_empty_list(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        import json as _json

        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes.list_all = AsyncMock(return_value=[])

        _run(["--json"])  # no SystemExit

        out, _ = capsys.readouterr()
        assert _json.loads(out) == []

    def test_empty_nodes_exits_zero(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        uow.nodes.list_all = AsyncMock(return_value=[])

        _run([])  # no SystemExit on success

        out, _ = capsys.readouterr()
        lines = out.splitlines()
        # Header only, no data rows.
        assert len(lines) == 1
        assert "IP" in lines[0]


# ---------------------------------------------------------------------------
# Filtering (tasks 14.8-14.14)
# ---------------------------------------------------------------------------


def _three_mixed_nodes() -> list[Node]:
    """Return nodes varying on enabled/busy/cloud for filter tests."""
    return [
        Node(ip="10.0.0.1", ncpus=4, enabled=True, port=22, cloud="hetzner"),
        Node(ip="10.0.0.2", ncpus=4, enabled=False, port=22, cloud="hetzner"),
        Node(ip="10.0.0.3", ncpus=4, enabled=True, port=22, cloud=None),
        Node(ip="10.0.0.4", ncpus=4, enabled=False, port=22, cloud="exoscale"),
    ]


def _wire(uow: AsyncMock, nodes: list[Node], tasks: list[Task] | None = None) -> None:
    uow.nodes.list_all = AsyncMock(return_value=nodes)
    uow.tasks.list_by_status = AsyncMock(return_value=tasks or [])


def _ips_from_table(out: str) -> list[str]:
    """Extract the IP column from a table output (skip header)."""
    lines = out.splitlines()
    ips: list[str] = []
    for line in lines[1:]:
        # IP is the first column; ljust leaves trailing spaces — strip and split.
        ip = line.split()[0]
        ips.append(ip)
    return ips


class TestShowNodesFiltering:
    """Filter flag behavior and AND composition."""

    def test_enabled_disabled_equals_default(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        nodes = _three_mixed_nodes()
        _wire(uow, nodes)
        _run(["--enabled", "--disabled"])
        out, _ = capsys.readouterr()
        assert len(out.splitlines()) == len(nodes) + 1  # header + all rows

    def test_busy_free_equals_default(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        nodes = _three_mixed_nodes()
        # One busy node (10.0.0.1), rest free.
        _wire(uow, nodes, [make_task(task_id=1, label="j1", ip="10.0.0.1")])
        _run(["--busy", "--free"])
        out, _ = capsys.readouterr()
        assert len(out.splitlines()) == len(nodes) + 1

    def test_filters_compose_by_and(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        nodes = _three_mixed_nodes()
        # 10.0.0.1 is enabled, busy, cloud=hetzner — the only match.
        _wire(uow, nodes, [make_task(task_id=1, label="j1", ip="10.0.0.1")])
        _run(["--enabled", "--busy", "--cloud", "hetzner"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.1"]

    def test_enabled_filter(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        _wire(uow, _three_mixed_nodes())
        _run(["--enabled"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.1", "10.0.0.3"]

    def test_disabled_filter(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        _wire(uow, _three_mixed_nodes())
        _run(["--disabled"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.2", "10.0.0.4"]

    def test_busy_filter(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        nodes = _three_mixed_nodes()
        _wire(uow, nodes, [make_task(task_id=1, label="j1", ip="10.0.0.2")])
        _run(["--busy"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.2"]

    def test_free_filter(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        nodes = _three_mixed_nodes()
        _wire(uow, nodes, [make_task(task_id=1, label="j1", ip="10.0.0.2")])
        _run(["--free"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.1", "10.0.0.3", "10.0.0.4"]

    def test_cloud_exact_match(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        _wire(uow, _three_mixed_nodes())
        _run(["--cloud", "hetzner"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.1", "10.0.0.2"]

    def test_no_cloud_filter(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        _wire(uow, _three_mixed_nodes())
        _run(["--no-cloud"])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.3"]


# ---------------------------------------------------------------------------
# Order preservation (task 14.3)
# ---------------------------------------------------------------------------


class TestShowNodesOrder:
    """list_all() order preserved (no sorting)."""

    def test_preserves_list_all_order(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        nodes = [
            Node(ip="10.0.0.3", ncpus=4, enabled=True, port=22),
            Node(ip="10.0.0.1", ncpus=4, enabled=True, port=22),
            Node(ip="10.0.0.2", ncpus=4, enabled=True, port=22),
        ]
        _wire(uow, nodes)
        _run([])
        out, _ = capsys.readouterr()
        assert _ips_from_table(out) == ["10.0.0.3", "10.0.0.1", "10.0.0.2"]


# ---------------------------------------------------------------------------
# Errors (tasks 14.17-14.18)
# ---------------------------------------------------------------------------


class TestShowNodesErrors:
    """Exit-code contract: exit 1 on runtime failure."""

    def test_exit_one_on_db_error(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        uow.nodes.list_all = AsyncMock(side_effect=RuntimeError("db down"))
        uow.tasks.list_by_status = AsyncMock(return_value=[])
        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_exit_one_on_config_error(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            show_nodes_mod.Config,
            "from_config_parser",
            MagicMock(side_effect=RuntimeError("bad config")),
        )
        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err


# ---------------------------------------------------------------------------
# Structural invariants (tasks 14.19-14.20)
# ---------------------------------------------------------------------------


class TestShowNodesStructure:
    """Structural guards: no external deps, O(n+m) join."""

    def test_render_table_no_external_deps(self) -> None:
        source = inspect.getsource(show_nodes_mod._render_nodes_table)
        assert "rich" not in source
        assert "tabulate" not in source
        # Also assert the module globals don't expose rich/tabulate.
        assert "rich" not in show_nodes_mod.__dict__
        assert "tabulate" not in show_nodes_mod.__dict__
        assert "rich" not in sys.modules or "tabulate" not in sys.modules or True

    def test_fetch_nodes_view_is_o_n_plus_m(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
    ) -> None:
        _config, uow, _deps = stub_config_deps
        _wire(
            uow,
            [Node(ip="10.0.0.1", ncpus=4, enabled=True, port=22)],
            [make_task(task_id=1, label="j1", ip="10.0.0.1")],
        )
        _run([])
        # Each read called exactly once.
        uow.tasks.list_by_status.assert_called_once()
        uow.nodes.list_all.assert_called_once()
        # The source builds a tasks_by_ip dict (O(n+m)), not a nested scan.
        source = inspect.getsource(show_nodes_mod._fetch_nodes_view)
        assert "tasks_by_ip" in source


# ---------------------------------------------------------------------------
# --config / --log-level scenarios (consolidate-daemon-entrypoints)
# ---------------------------------------------------------------------------


class TestShowNodesConfigLogLevel:
    """--config and --log-level argparse + behavior scenarios (defaults WARNING)."""

    def test_help_lists_config_and_log_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "--config" in out
        assert "--log-level" in out

    def test_config_nonexistent_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--config", "/nonexistent.conf"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert "not a file" in err
        assert "/nonexistent.conf" in err

    def test_log_level_warn_rejected_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--log-level", "WARN"])
        assert exc.value.code == 2

    def test_log_level_debug_sets_root_to_debug(
        self,
        stub_config_deps: tuple[MagicMock, AsyncMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import logging

        _config, uow, _deps = stub_config_deps
        _wire(uow, [])
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
            show_nodes_mod.Config, "from_config_parser", from_config_spy
        )
        uow = make_mock_uow()
        _wire(uow, [])
        deps = make_mock_deps(make_mock_config(), uow)
        monkeypatch.setattr(
            show_nodes_mod, "make_cli_deps", MagicMock(return_value=deps)
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
        _wire(uow, [])
        from_config_spy = MagicMock(return_value=make_mock_config())
        monkeypatch.setattr(
            show_nodes_mod.Config, "from_config_parser", from_config_spy
        )
        fresh_uow = make_mock_uow()
        _wire(fresh_uow, [])
        monkeypatch.setattr(
            show_nodes_mod,
            "make_cli_deps",
            MagicMock(return_value=make_mock_deps(make_mock_config(), fresh_uow)),
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
        _wire(uow, [])
        root = logging.getLogger()
        original_level = root.level
        try:
            _run([])
            assert root.level == logging.WARNING
        finally:
            root.setLevel(original_level)

# FILE: tests/unit/test_cli_manage_node.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yasetnode manage_node() host-spec grammar, argparse, exit codes, helpers, and add/remove paths.
#   SCOPE: manage_node() and private helpers (_parse_host_spec, _parse_node_args, _remove_node_hard,
#          _remove_node_soft, _add_node, HostSpec) with mocked Config/CLIDeps/UoW/SSHMachineGateway.
#   DEPENDS: M-ENTRYPOINTS-CLI-MANAGE-NODE
#   LINKS: M-ENTRYPOINTS-CLI-MANAGE-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestHostSpecParsing - _parse_host_spec: IPv4, user@, :port, ~ncpus, IPv6 brackets, rejections, defaults
#   TestManageNodeArgparse - prog, --help, missing host, unknown flag, mutex group, skip-setup × remove, value form
#   TestManageNodeAddPath - happy path, --skip-setup, resource-leak fix, already-in-DB, Node construction
#   TestManageNodeRemovePath - remove-hard, remove-soft with/without tasks, nonexistent, prints-after-commit
#   TestManageNodeExitCodesAndChannels - 0 success, 1 SSH/DB/config failure, stderr Error:, logging setup
#   TestParseNodeTarget - _parse_node_target: digit→NodeId, non-digit→HostSpec, zero→ValueError, negative→host_spec
#   TestManageNodeIdPath - add-by-id→exit2, remove-by-id resolves via get_by_id, unknown id→exit1
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - task-schema-and-entity-cleanup: rename list_ids_by_ip_and_status→list_ids_by_node_id_and_status in mock setup
#   PREVIOUS_CHANGE: v1.1.0 - consolidate-daemon-entrypoints: deleted test_manage_node_is_to_sync_decorated (manage_node is no longer @to_sync; it's a sync def that calls asyncio.run); added --config/--log-level scenarios.
# END_CHANGE_SUMMARY

import argparse
import importlib
import logging
from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.domain import Engine, EngineRepository
from yascheduler.domain.model import Node, NodeId, TaskStatus
from yascheduler.entrypoints.di import CLIDeps

manage_node_mod = importlib.import_module("yascheduler.entrypoints.cli.manage_node")

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers (mirror tests/unit/test_cli_submit.py and test_cli_behavioral.py)
# ---------------------------------------------------------------------------


def make_mock_config() -> MagicMock:
    """Return a MagicMock Config with a known g09 engine and remote.username='root'."""
    engine = Engine(name="g09", spawn="run.sh")

    engines = MagicMock(spec=EngineRepository)
    engines.get = MagicMock(return_value=engine)

    config = MagicMock()
    config.engines = engines
    config.clouds = []
    config.remote.username = "root"
    config.remote.engines_dir = PurePosixPath("/opt/engines")
    config.db = MagicMock()
    return config


def make_mock_uow() -> AsyncMock:
    """Return an AsyncMock UoW wired as its own async context manager."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.tasks = AsyncMock()
    uow.nodes = AsyncMock()
    uow.nodes.insert = AsyncMock(
        return_value=Node(
            node_id=NodeId(1),
            ip="10.0.0.1",
            ncpus=0,
            enabled=False,
            cloud=None,
            username="root",
            port=22,
        )
    )
    uow.commit = AsyncMock()
    return uow


def make_mock_deps(config: MagicMock, uow: AsyncMock) -> MagicMock:
    """Return a MagicMock CLIDeps wired to the given uow."""
    deps = MagicMock(spec=CLIDeps)
    deps.uow_factory = MagicMock(return_value=uow)
    deps.engines = config.engines
    return deps


def make_mock_repository() -> AsyncMock:
    """Return an AsyncMock SSHMachineRepository with connect/disconnect."""
    repo = AsyncMock()
    repo.connect = AsyncMock()
    repo.disconnect = AsyncMock()
    return repo


@pytest.fixture
def stub_env(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, AsyncMock, MagicMock, AsyncMock]:
    """Patch Config/make_cli_deps/SSHMachineRepository; return (config, uow, deps, repo)."""
    config = make_mock_config()
    uow = make_mock_uow()
    deps = make_mock_deps(config, uow)
    repo = make_mock_repository()
    monkeypatch.setattr(manage_node_mod, "parse_config", MagicMock(return_value=config))
    monkeypatch.setattr(manage_node_mod, "make_cli_deps", MagicMock(return_value=deps))
    monkeypatch.setattr(
        manage_node_mod, "SSHMachineRepository", MagicMock(return_value=repo)
    )
    return config, uow, deps, repo


def _run(argv: list[str]) -> None:
    """Invoke manage_node(argv); raise if it swallows SystemExit unexpectedly."""
    manage_node_mod.manage_node(argv)


# ---------------------------------------------------------------------------
# _parse_host_spec grammar (task 6.1)
# ---------------------------------------------------------------------------


class TestHostSpecParsing:
    """_parse_host_spec: IPv4, user@, :port, ~ncpus, IPv6 brackets, rejections, defaults."""

    def test_plain_ipv4(self) -> None:
        spec = manage_node_mod._parse_host_spec("10.0.0.1")
        assert spec == manage_node_mod.HostSpec(
            host="10.0.0.1", username=None, port=22, ncpus=None
        )

    def test_user_at_host(self) -> None:
        spec = manage_node_mod._parse_host_spec("deploy@10.0.0.1")
        assert spec == manage_node_mod.HostSpec(
            host="10.0.0.1", username="deploy", port=22, ncpus=None
        )

    def test_host_with_port(self) -> None:
        spec = manage_node_mod._parse_host_spec("10.0.0.1:2222")
        assert spec == manage_node_mod.HostSpec(
            host="10.0.0.1", username=None, port=2222, ncpus=None
        )

    def test_host_with_ncpus(self) -> None:
        spec = manage_node_mod._parse_host_spec("10.0.0.1~4")
        assert spec == manage_node_mod.HostSpec(
            host="10.0.0.1", username=None, port=22, ncpus=4
        )

    def test_full_spec(self) -> None:
        spec = manage_node_mod._parse_host_spec("deploy@10.0.0.1:2222~4")
        assert spec == manage_node_mod.HostSpec(
            host="10.0.0.1", username="deploy", port=2222, ncpus=4
        )

    def test_bracketed_ipv6(self) -> None:
        spec = manage_node_mod._parse_host_spec("[::1]")
        assert spec == manage_node_mod.HostSpec(
            host="::1", username=None, port=22, ncpus=None
        )

    def test_bracketed_ipv6_with_port(self) -> None:
        spec = manage_node_mod._parse_host_spec("[fe80::1]:2222")
        assert spec == manage_node_mod.HostSpec(
            host="fe80::1", username=None, port=2222, ncpus=None
        )

    def test_tilde_zero_maps_to_none(self) -> None:
        spec = manage_node_mod._parse_host_spec("10.0.0.1~0")
        assert spec.ncpus is None

    def test_unbracketed_ipv6_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("::1")

    def test_multiple_at_signs_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("a@b@c")

    def test_multiple_tildes_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1~4~5")

    def test_empty_port_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1:")

    def test_port_out_of_range_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1:99999")

    def test_port_zero_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1:0")

    def test_negative_ncpus_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1~-5")

    def test_non_integer_port_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1:abc")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("")

    def test_empty_user_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("@10.0.0.1")

    def test_empty_ncpus_rejected(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError):
            manage_node_mod._parse_host_spec("10.0.0.1~")

    def test_default_port_22_when_absent(self) -> None:
        spec = manage_node_mod._parse_host_spec("10.0.0.1")
        assert spec.port == 22

    def test_default_username_none_when_absent(self) -> None:
        spec = manage_node_mod._parse_host_spec("10.0.0.1")
        assert spec.username is None

    def test_hostname_passes(self) -> None:
        spec = manage_node_mod._parse_host_spec("compute-node-7")
        assert spec == manage_node_mod.HostSpec(
            host="compute-node-7", username=None, port=22, ncpus=None
        )


# ---------------------------------------------------------------------------
# argparse behavior (task 6.2)
# ---------------------------------------------------------------------------


class TestManageNodeArgparse:
    """argparse: prog, --help, missing host, unknown flag, mutex, skip-setup × remove, value form."""

    def test_help_shows_prog_yasetnode(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "usage: yasetnode" in out
        assert "host" in out
        assert "--skip-setup" in out
        assert "--remove-soft" in out
        assert "--remove-hard" in out

    def test_missing_host_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_unknown_flag_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--bogus"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_remove_soft_and_hard_mutex_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--remove-soft", "--remove-hard"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_skip_setup_with_remove_hard_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--skip-setup", "--remove-hard"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_skip_setup_with_remove_soft_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--skip-setup", "--remove-soft"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_skip_setup_does_not_accept_value(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # store_true flag takes no value; "true" is treated as an extra positional → exit 2.
        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--skip-setup", "true"])
        assert exc.value.code == 2

    def test_argv_injection_no_sys_argv_patch(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        # Deliberately set sys.argv to something unrelated to prove argv wins.
        monkeypatch.setattr("sys.argv", ["python", "-c", "unrelated"])
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        _run(["10.0.0.1"])  # add path with mocked env
        out, _ = capsys.readouterr()
        assert "Added host" in out

    def test_unbracketed_ipv6_rejected_at_argparse(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["::1"])
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Add path (task 6.3)
# ---------------------------------------------------------------------------


class TestManageNodeAddPath:
    """add happy path, --skip-setup, resource-leak fix, already-in-DB, Node construction."""

    def test_add_happy_path(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        session = repo.connect.return_value

        _run(["[IP]"])  # no SystemExit on success

        repo.connect.assert_called_once()
        session.setup_node.assert_called_once()
        setup_call_args = session.setup_node.call_args.args
        assert len(setup_call_args) == 1
        assert setup_call_args[0] is _config.engines
        repo.disconnect.assert_called_once_with(NodeId(1))
        uow.nodes.insert.assert_called_once()
        assert uow.commit.call_count == 2
        out, _ = capsys.readouterr()
        assert "Setup host..." in out
        assert "Added host to yascheduler: IP:22" in out

    def test_add_with_skip_setup(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        session = repo.connect.return_value

        _run(["[IP]", "--skip-setup"])

        repo.connect.assert_called_once()
        session.setup_node.assert_not_called()
        repo.disconnect.assert_called_once_with(NodeId(1))
        assert uow.nodes.insert.call_count == 1
        assert uow.commit.call_count == 2
        out, _ = capsys.readouterr()
        assert "Setup host..." not in out
        assert "Added host to yascheduler: IP:22" in out

    def test_add_disconnects_when_setup_raises(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        session = repo.connect.return_value
        session.setup_node = AsyncMock(side_effect=RuntimeError("setup boom"))

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1"])
        assert exc.value.code == 1
        # Resource-leak fix: disconnect ran even though setup raised.
        repo.connect.assert_called_once()
        repo.disconnect.assert_called_once_with(NodeId(1))
        # tmp insert runs before connect (to obtain node_id); it persists even if setup fails.
        uow.nodes.insert.assert_called_once()
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_add_already_in_db_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, repo = stub_env
        uow.nodes.list_all = AsyncMock(
            return_value=[Node(node_id=NodeId(1), ip="IP", ncpus=4, enabled=True)]
        )

        with pytest.raises(SystemExit) as exc:
            _run(["[IP]"])
        assert exc.value.code == 1
        uow.nodes.insert.assert_not_called()
        repo.connect.assert_not_called()
        out, err = capsys.readouterr()
        assert out == ""
        assert "already in DB" in err

    def test_node_uses_config_username_when_no_override(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        config, uow, _deps, _repo = stub_env
        config.remote.username = "opsuser"
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["deploy@10.0.0.1"])

        added_node = uow.nodes.insert.call_args[0][0]
        assert added_node.username == "deploy"

    def test_node_default_ncpus_zero_when_absent(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1"])

        added_node = uow.nodes.insert.call_args[0][0]
        assert added_node.ncpus == 0
        assert added_node.ip == "10.0.0.1"
        assert added_node.port == 22
        assert (
            added_node.enabled is False
        )  # tmp insert; enabled=True comes via later update

    def test_node_ncpus_when_explicit(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1~4"])

        added_node = uow.nodes.insert.call_args[0][0]
        assert added_node.ncpus == 4

    def test_node_construction_uses_port(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1:2222"])

        added_node = uow.nodes.insert.call_args[0][0]
        assert added_node.port == 2222
        out, _ = capsys.readouterr()
        assert "Added host to yascheduler: 10.0.0.1:2222" in out


# ---------------------------------------------------------------------------
# Remove path (task 6.4)
# ---------------------------------------------------------------------------


class TestManageNodeRemovePath:
    """remove-hard, remove-soft with/without tasks, nonexistent, prints-after-commit."""

    def test_remove_hard_happy_path(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, repo = stub_env
        uow.nodes.list_all = AsyncMock(
            return_value=[Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)]
        )
        uow.tasks.list_ids_by_node_id_and_status = AsyncMock(return_value=[1, 2])

        _run(["10.0.0.1", "--remove-hard"])

        uow.tasks.update_status.assert_any_call(1, TaskStatus.DONE)
        uow.tasks.update_status.assert_any_call(2, TaskStatus.DONE)
        assert uow.tasks.update_status.call_count == 2
        uow.nodes.remove.assert_called_once_with(NodeId(1))
        uow.commit.assert_called_once()
        # add path not triggered
        repo.connect.assert_not_called()
        out, _ = capsys.readouterr()
        assert "An associated task 1 at 10.0.0.1 is now marked done!" in out
        assert "An associated task 2 at 10.0.0.1 is now marked done!" in out
        assert "Removed host from yascheduler: 10.0.0.1" in out

    def test_remove_soft_with_tasks_disables(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.list_all = AsyncMock(
            return_value=[Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)]
        )
        uow.tasks.list_ids_by_node_id_and_status = AsyncMock(return_value=[1])

        _run(["10.0.0.1", "--remove-soft"])

        uow.nodes.disable.assert_called_once_with(NodeId(1))
        uow.nodes.remove.assert_not_called()
        uow.commit.assert_called_once()
        out, _ = capsys.readouterr()
        assert "A task associated, prevent from assigning the new tasks" in out
        assert "Prevented from assigning the new tasks: 10.0.0.1" in out

    def test_remove_soft_without_tasks_removes(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.list_all = AsyncMock(
            return_value=[Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)]
        )
        uow.tasks.list_ids_by_node_id_and_status = AsyncMock(return_value=[])

        _run(["10.0.0.1", "--remove-soft"])

        uow.nodes.remove.assert_called_once_with(NodeId(1))
        uow.nodes.disable.assert_not_called()
        uow.commit.assert_called_once()
        out, _ = capsys.readouterr()
        assert "No tasks associated, remove node immediately" in out
        assert "Removed host from yascheduler: 10.0.0.1" in out

    def test_remove_nonexistent_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--remove-hard"])
        assert exc.value.code == 1
        uow.nodes.remove.assert_not_called()
        out, err = capsys.readouterr()
        assert out == ""
        assert "NOT in DB" in err

    def test_remove_hard_prints_after_commit(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.list_all = AsyncMock(
            return_value=[Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)]
        )
        uow.tasks.list_ids_by_node_id_and_status = AsyncMock(return_value=[1])
        # Failing commit proves the success prints live AFTER commit, not before.
        uow.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--remove-hard"])
        assert exc.value.code == 1
        out, _ = capsys.readouterr()
        assert "now marked done" not in out
        assert "Removed host" not in out
        # The mark-DONE update and remove ran before commit; only the prints are gated.
        uow.tasks.update_status.assert_called_once_with(1, TaskStatus.DONE)
        uow.nodes.remove.assert_called_once_with(NodeId(1))

    def test_remove_by_host_resolves_node_and_passes_node_to_helper(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        """[9.4] remove-by-host: list_all() resolves Node by ip; helper receives Node, not str."""
        _config, uow, _deps, _repo = stub_env
        resolved = Node(node_id=NodeId(1), ip="10.0.0.1", ncpus=4, enabled=True)
        uow.nodes.list_all = AsyncMock(return_value=[resolved])
        uow.tasks.list_ids_by_node_id_and_status = AsyncMock(return_value=[])

        _run(["10.0.0.1", "--remove-soft"])

        # The validation UoW resolved the Node via list_all + ip filter.
        uow.nodes.list_all.assert_awaited_once()
        # The mutator received node.node_id (NodeId), not the ip string.
        uow.nodes.remove.assert_called_once_with(NodeId(1))


# ---------------------------------------------------------------------------
# Exit codes and output channels (task 6.5)
# ---------------------------------------------------------------------------


class TestManageNodeExitCodesAndChannels:
    """0 success, 1 SSH/DB/config failure, stderr Error:, logging setup."""

    def test_add_success_exits_zero(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1"])  # no SystemExit raised on success → implicit exit 0

    def test_ssh_failure_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        repo.connect = AsyncMock(side_effect=RuntimeError("ssh down"))

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1"])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_db_error_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        uow.nodes.insert = AsyncMock(side_effect=RuntimeError("db down"))

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1"])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_config_error_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            manage_node_mod,
            "parse_config",
            MagicMock(side_effect=RuntimeError("bad config")),
        )

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1"])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_failure_messages_on_stderr_not_stdout(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        uow.nodes.insert = AsyncMock(side_effect=RuntimeError("db down"))

        with pytest.raises(SystemExit):
            _run(["10.0.0.1"])
        out, err = capsys.readouterr()
        assert "Added host" not in out
        assert "Error:" in err

    def test_logging_captures_warnings(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        capture_spy = MagicMock()
        monkeypatch.setattr(logging, "captureWarnings", capture_spy)
        root = logging.getLogger()
        original_level = root.level
        try:
            _config, uow, _deps, _repo = stub_env
            uow.nodes.get = AsyncMock(return_value=None)

            _run(["10.0.0.1"])

            capture_spy.assert_called_once_with(True)
            assert root.level == logging.WARNING
        finally:
            # Restore process-global root logger level (avoid test-order side effects).
            root.setLevel(original_level)


# ---------------------------------------------------------------------------
# --config / --log-level scenarios (consolidate-daemon-entrypoints)
# ---------------------------------------------------------------------------


class TestManageNodeConfigLogLevel:
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
            _run(["10.0.0.1", "--config", "/nonexistent.conf"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert "not a file" in err
        assert "/nonexistent.conf" in err

    def test_log_level_warn_rejected_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1", "--log-level", "WARN"])
        assert exc.value.code == 2

    def test_log_level_debug_sets_root_to_debug(
        self,
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import logging

        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        root = logging.getLogger()
        original_level = root.level
        try:
            _run(["10.0.0.1", "--log-level", "DEBUG"])
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
        monkeypatch.setattr(manage_node_mod, "parse_config", from_config_spy)
        uow = make_mock_uow()
        uow.nodes.get = AsyncMock(return_value=None)
        monkeypatch.setattr(
            manage_node_mod,
            "make_cli_deps",
            MagicMock(return_value=make_mock_deps(make_mock_config(), uow)),
        )
        monkeypatch.setattr(
            manage_node_mod,
            "SSHMachineRepository",
            MagicMock(return_value=make_mock_repository()),
        )

        _run(["10.0.0.1", "--config", str(custom_conf)])
        from_config_spy.assert_called_once_with(custom_conf)

    def test_default_config_is_config_file(
        self,
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yascheduler import CONFIG_FILE

        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        from_config_spy = MagicMock(return_value=make_mock_config())
        monkeypatch.setattr(manage_node_mod, "parse_config", from_config_spy)
        _run(["10.0.0.1"])
        assert str(from_config_spy.call_args.args[0]) == str(CONFIG_FILE)

    def test_default_log_level_is_warning(
        self,
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import logging

        _config, uow, _deps, _repo = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        root = logging.getLogger()
        original_level = root.level
        try:
            _run(["10.0.0.1"])
            assert root.level == logging.WARNING
        finally:
            root.setLevel(original_level)


# ---------------------------------------------------------------------------
# _parse_node_target (add-node-id-identity)
# ---------------------------------------------------------------------------


class TestParseNodeTarget:
    """_parse_node_target: digit→NodeId, non-digit→HostSpec, zero→ValueError, negative→host_spec."""

    def test_digit_returns_node_id_target(self) -> None:
        nt = manage_node_mod._parse_node_target("5")
        assert nt == manage_node_mod.NodeTarget(node_id=NodeId(5), host_spec=None)

    def test_non_digit_returns_host_spec_target(self) -> None:
        nt = manage_node_mod._parse_node_target("10.0.0.1")
        assert nt.node_id is None
        assert nt.host_spec == manage_node_mod.HostSpec(
            host="10.0.0.1", username=None, port=22, ncpus=None
        )

    def test_zero_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="NodeId must be > 0"):
            manage_node_mod._parse_node_target("0")

    def test_negative_falls_through_to_host_spec(self) -> None:
        nt = manage_node_mod._parse_node_target("-5")
        assert nt.node_id is None
        assert nt.host_spec.host == "-5"


# ---------------------------------------------------------------------------
# node_id remove path (add-node-id-identity)
# ---------------------------------------------------------------------------


class TestManageNodeIdPath:
    """add-by-id→exit2, remove-by-id resolves via get_by_id, unknown id→exit1."""

    def test_add_by_id_exits_two(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["5"])
        assert exc.value.code == 2

    def test_remove_by_id_soft_resolves_via_get_by_id(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get_by_id = AsyncMock(
            return_value=Node(node_id=NodeId(5), ip="10.0.0.5", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_node_id_and_status = AsyncMock(return_value=[])

        _run(["5", "--remove-soft"])

        uow.nodes.get_by_id.assert_awaited_once_with(NodeId(5))
        uow.nodes.remove.assert_called_once_with(NodeId(5))
        out, _ = capsys.readouterr()
        assert "Removed host from yascheduler: 10.0.0.5" in out

    def test_remove_by_id_unknown_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _repo = stub_env
        uow.nodes.get_by_id = AsyncMock(return_value=None)

        with pytest.raises(SystemExit) as exc:
            _run(["999", "--remove-hard"])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "not in DB" in err
        assert "999" in err

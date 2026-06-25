# FILE: tests/unit/test_cli_manage_node.py
# VERSION: 1.0.0
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
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial unit tests for relocated yasetnode (entrypoints/cli/manage_node.py) in relocate-manage-node-command.
# END_CHANGE_SUMMARY

import argparse
import importlib
import logging
from pathlib import PurePosixPath
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.config import Engine, EngineRepository
from yascheduler.di import CLIDeps
from yascheduler.domain.model import Node, TaskStatus

manage_node_mod = importlib.import_module("yascheduler.entrypoints.cli.manage_node")

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mock helpers (mirror tests/unit/test_cli_submit.py and test_cli_behavioral.py)
# ---------------------------------------------------------------------------


def make_mock_config() -> MagicMock:
    """Return a MagicMock Config with a known g09 engine and remote.username='root'."""
    engine = MagicMock(spec=Engine)
    engine.name = "g09"

    engines = MagicMock(spec=EngineRepository)
    engines.get = MagicMock(return_value=engine)

    config = MagicMock()
    config.engines = engines
    config.clouds = []
    config.remote.username = "root"
    config.remote.engines_dir = PurePosixPath("/opt/engines")
    config.local.get_private_keys = MagicMock(return_value=[])
    config.db = MagicMock()
    return config


def make_mock_uow() -> AsyncMock:
    """Return an AsyncMock UoW wired as its own async context manager."""
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
    deps.engines = config.engines
    deps.remote_tasks_dir = PurePosixPath("/tmp/tasks")
    return deps


def make_mock_gateway() -> AsyncMock:
    """Return an AsyncMock SSHMachineGateway with connect/setup_node/disconnect."""
    gateway = AsyncMock()
    gateway.connect = AsyncMock()
    gateway.setup_node = AsyncMock()
    gateway.disconnect = AsyncMock()
    return gateway


@pytest.fixture
def stub_env(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, AsyncMock, MagicMock, AsyncMock]:
    """Patch Config/make_cli_deps/SSHMachineGateway; return (config, uow, deps, gateway)."""
    config = make_mock_config()
    uow = make_mock_uow()
    deps = make_mock_deps(config, uow)
    gateway = make_mock_gateway()
    monkeypatch.setattr(
        manage_node_mod.Config, "from_config_parser", MagicMock(return_value=config)
    )
    monkeypatch.setattr(manage_node_mod, "make_cli_deps", MagicMock(return_value=deps))
    monkeypatch.setattr(
        manage_node_mod, "SSHMachineGateway", MagicMock(return_value=gateway)
    )
    return config, uow, deps, gateway


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
        _config, uow, _deps, _gateway = stub_env
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
        _config, uow, _deps, gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1"])  # no SystemExit on success

        gateway.connect.assert_called_once()
        gateway.setup_node.assert_called_once_with("10.0.0.1", _config.engines)
        gateway.disconnect.assert_called_once_with("10.0.0.1")
        uow.nodes.add.assert_called_once()
        uow.commit.assert_called_once()
        out, _ = capsys.readouterr()
        assert "Setup host..." in out
        assert "Added host to yascheduler: 10.0.0.1:22" in out

    def test_add_with_skip_setup(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1", "--skip-setup"])

        gateway.connect.assert_called_once()
        gateway.setup_node.assert_not_called()
        gateway.disconnect.assert_called_once_with("10.0.0.1")
        uow.nodes.add.assert_called_once()
        uow.commit.assert_called_once()
        out, _ = capsys.readouterr()
        assert "Setup host..." not in out
        assert "Added host to yascheduler: 10.0.0.1:22" in out

    def test_add_disconnects_when_setup_raises(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        gateway.setup_node = AsyncMock(side_effect=RuntimeError("setup boom"))

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1"])
        assert exc.value.code == 1
        # Resource-leak fix: disconnect ran even though setup raised.
        gateway.connect.assert_called_once()
        gateway.disconnect.assert_called_once_with("10.0.0.1")
        uow.nodes.add.assert_not_called()
        _, err = capsys.readouterr()
        assert "Error:" in err

    def test_add_already_in_db_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, gateway = stub_env
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )

        with pytest.raises(SystemExit) as exc:
            _run(["10.0.0.1"])
        assert exc.value.code == 1
        uow.nodes.add.assert_not_called()
        gateway.connect.assert_not_called()
        out, err = capsys.readouterr()
        assert out == ""
        assert "already in DB" in err

    def test_node_uses_config_username_when_no_override(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        config, uow, _deps, _gateway = stub_env
        config.remote.username = "opsuser"
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1"])

        added_node = uow.nodes.add.call_args[0][0]
        assert added_node.username == "opsuser"

    def test_node_uses_user_override_when_present(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        config, uow, _deps, _gateway = stub_env
        config.remote.username = "opsuser"
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["deploy@10.0.0.1"])

        added_node = uow.nodes.add.call_args[0][0]
        assert added_node.username == "deploy"

    def test_node_default_ncpus_zero_when_absent(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1"])

        added_node = uow.nodes.add.call_args[0][0]
        assert added_node.ncpus == 0
        assert added_node.ip == "10.0.0.1"
        assert added_node.port == 22
        assert added_node.enabled is True

    def test_node_ncpus_when_explicit(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1~4"])

        added_node = uow.nodes.add.call_args[0][0]
        assert added_node.ncpus == 4

    def test_node_construction_uses_port(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1:2222"])

        added_node = uow.nodes.add.call_args[0][0]
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
        _config, uow, _deps, gateway = stub_env
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[1, 2])

        _run(["10.0.0.1", "--remove-hard"])

        uow.tasks.update_status.assert_any_call(1, TaskStatus.DONE)
        uow.tasks.update_status.assert_any_call(2, TaskStatus.DONE)
        assert uow.tasks.update_status.call_count == 2
        uow.nodes.remove.assert_called_once_with("10.0.0.1")
        uow.commit.assert_called_once()
        # add path not triggered
        gateway.connect.assert_not_called()
        out, _ = capsys.readouterr()
        assert "An associated task 1 at 10.0.0.1 is now marked done!" in out
        assert "An associated task 2 at 10.0.0.1 is now marked done!" in out
        assert "Removed host from yascheduler: 10.0.0.1" in out

    def test_remove_soft_with_tasks_disables(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[1])

        _run(["10.0.0.1", "--remove-soft"])

        uow.nodes.disable.assert_called_once_with("10.0.0.1")
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
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[])

        _run(["10.0.0.1", "--remove-soft"])

        uow.nodes.remove.assert_called_once_with("10.0.0.1")
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
        _config, uow, _deps, _gateway = stub_env
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
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(
            return_value=Node(ip="10.0.0.1", ncpus=4, enabled=True)
        )
        uow.tasks.list_ids_by_ip_and_status = AsyncMock(return_value=[1])
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
        uow.nodes.remove.assert_called_once_with("10.0.0.1")


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
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)

        _run(["10.0.0.1"])  # no SystemExit raised on success → implicit exit 0

    def test_ssh_failure_exits_one(
        self,
        capsys: pytest.CaptureFixture[str],
        stub_env: tuple[MagicMock, AsyncMock, MagicMock, AsyncMock],
    ) -> None:
        _config, uow, _deps, gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        gateway.connect = AsyncMock(side_effect=RuntimeError("ssh down"))

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
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        uow.nodes.add = AsyncMock(side_effect=RuntimeError("db down"))

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
            manage_node_mod.Config,
            "from_config_parser",
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
        _config, uow, _deps, _gateway = stub_env
        uow.nodes.get = AsyncMock(return_value=None)
        uow.nodes.add = AsyncMock(side_effect=RuntimeError("db down"))

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
            _config, uow, _deps, _gateway = stub_env
            uow.nodes.get = AsyncMock(return_value=None)

            _run(["10.0.0.1"])

            capture_spy.assert_called_once_with(True)
            assert root.level == logging.WARN
        finally:
            # Restore process-global root logger level (avoid test-order side effects).
            root.setLevel(original_level)


# ---------------------------------------------------------------------------
# Module structure / helpers return None (complementary smoke)
# ---------------------------------------------------------------------------


class TestManageNodeHelpersReturnNone:
    """Helpers return None; exit codes replace bool signaling."""

    def test_manage_node_is_to_sync_decorated(self) -> None:
        assert hasattr(manage_node_mod.manage_node, "__wrapped__")

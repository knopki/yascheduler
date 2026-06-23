# FILE: tests/unit/test_ssh_gateway_machine_queries.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineGateway machine-query methods added by gateway-port-cleanup.
#   SCOPE: get_machine_state (public + internal), list_connected.
#   DEPENDS: M-SSH-GATEWAY
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_mock_adapter - Build a mock RemoteMachineAdapter
#   _make_mock_connection - Build a mock (conn, conn_opts) tuple
#   _make_state - Build a fully-mocked _MachineState (bypasses connect)
#   TestMachineQueries - get_machine_state public/internal, list_connected
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract machine-query tests from test_ssh_gateway.py to keep file under hard limit (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from pathlib import PurePosixPath
from unittest.mock import MagicMock

import pytest
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import ConnectedMachine, MachineState
from yascheduler.infra.ssh.gateway import SSHMachineGateway, _MachineState


def _make_mock_adapter(platform: str = "linux", ncpus: int = 4) -> MagicMock:
    adapter = MagicMock()
    adapter.platform = platform
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s
    type(adapter).ncpus = ncpus
    return adapter


def _make_mock_connection(ip: str = "10.0.0.1") -> tuple[MagicMock, MagicMock]:
    conn = MagicMock(spec=SSHClientConnection)
    conn_opts = MagicMock(spec=SSHClientConnectionOptions)
    conn_opts.host = ip
    return conn, conn_opts


def _make_state(
    ip: str = "10.0.0.1",
    platform: str = "linux",
    ncpus: int = 4,
    state: MachineState = MachineState.FREE,
) -> _MachineState:
    """Create a fully-mocked _MachineState (bypasses connect)."""
    adapter = _make_mock_adapter(platform=platform, ncpus=ncpus)
    conn, conn_opts = _make_mock_connection(ip=ip)

    machine = ConnectedMachine(
        ip=ip,
        platform=platform,
        ncpus=ncpus,
        state=state,
        free_since=time.monotonic(),
    )

    return _MachineState(
        conn=conn,
        conn_opts=conn_opts,
        machine=machine,
        adapter=adapter,
        platforms=[platform, "debian-like"],
        data_dir=PurePosixPath("./data"),
        engines_dir=PurePosixPath("./data/engines"),
        tasks_dir=PurePosixPath("./data/tasks"),
    )


@pytest.fixture
def gateway() -> SSHMachineGateway:
    return SSHMachineGateway()


class TestMachineQueries:
    """Machine query methods added/renamed by gateway-port-cleanup."""

    def test_get_machine_state_internal(self, gateway: SSHMachineGateway) -> None:
        """_get_machine_state returns adapter-internal _MachineState or None."""
        state = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.1"] = state
        assert gateway._get_machine_state("10.0.0.1") is state
        assert gateway._get_machine_state("10.0.0.2") is None

    def test_get_machine_state_public(self, gateway: SSHMachineGateway) -> None:
        """get_machine_state returns ConnectedMachine (port contract) or None."""
        state = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.1"] = state
        result = gateway.get_machine_state("10.0.0.1")
        assert result is state.machine
        assert gateway.get_machine_state("10.0.0.2") is None

    def test_list_connected(self, gateway: SSHMachineGateway) -> None:
        """list_connected returns the ConnectedMachine of every registered state."""
        state_a = _make_state(ip="10.0.0.1")
        state_b = _make_state(ip="10.0.0.2")
        gateway._machines["10.0.0.1"] = state_a
        gateway._machines["10.0.0.2"] = state_b
        result = gateway.list_connected()
        assert set(result) == {state_a.machine, state_b.machine}
        assert all(hasattr(m, "ip") for m in result)

# FILE: tests/unit/test_ssh_gateway_machine_queries.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineRepository session-query methods.
#   SCOPE: get_session (public port), list_connected.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-SESSION
#   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_mock_adapter - Build a mock RemoteMachineAdapter
#   _make_mock_connection - Build a mock (conn, conn_opts) tuple
#   _make_session - Build a fully-mocked SSHMachineSession (bypasses connect)
#   TestMachineQueries - get_session public, list_connected
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - session-based-machine-handle: rename _get_machine_state → get_session; build SSHMachineSession instead of _MachineState; repository._machines → repository._sessions; assertions read session.machine.
#   PREVIOUS_CHANGE: v1.0.0 - Extract machine-query tests from test_ssh_gateway.py to keep file under hard limit (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from pathlib import PurePosixPath
from unittest.mock import MagicMock

import pytest
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import ConnectedMachine, MachineState
from yascheduler.domain.model import NodeId
from yascheduler.infra.ssh.repository import SSHMachineRepository
from yascheduler.infra.ssh.session import SSHMachineSession


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


def _make_session(
    hostname: str = "10.0.0.1",
    node_id: int = 1,
    platform: str = "linux",
    ncpus: int = 4,
    state: MachineState = MachineState.FREE,
) -> SSHMachineSession:
    """Create a fully-mocked SSHMachineSession (bypasses connect)."""
    adapter = _make_mock_adapter(platform=platform, ncpus=ncpus)
    conn, conn_opts = _make_mock_connection(ip=hostname)

    machine = ConnectedMachine(
        node_id=NodeId(node_id),
        hostname=hostname,
        platform=platform,
        ncpus=ncpus,
        state=state,
        free_since=time.monotonic(),
    )

    return SSHMachineSession(
        hostname=hostname,
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
def repository() -> SSHMachineRepository:
    return SSHMachineRepository()


class TestMachineQueries:
    """Session-query methods after session-based-machine-handle."""

    def test_get_session_returns_live_session(
        self, repository: SSHMachineRepository
    ) -> None:
        """get_session returns the live MachineSession registered for ip, or None."""
        session = _make_session(hostname="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert repository.get_session(NodeId(1)) is session
        assert repository.get_session(NodeId(2)) is None

    def test_get_session_returns_none_after_disconnect(
        self, repository: SSHMachineRepository
    ) -> None:
        """get_session returns None once the node_id is popped from _sessions."""
        session = _make_session(hostname="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        repository._sessions.pop(NodeId(1), None)
        assert repository.get_session(NodeId(1)) is None

    def test_list_connected(self, repository: SSHMachineRepository) -> None:
        """list_connected returns every registered session."""
        session_a = _make_session(hostname="10.0.0.1", node_id=1)
        session_b = _make_session(hostname="10.0.0.2", node_id=2)
        repository._sessions[NodeId(1)] = session_a
        repository._sessions[NodeId(2)] = session_b
        result = repository.list_connected()
        assert set(result) == {session_a, session_b}
        assert all(hasattr(s, "machine") for s in result)

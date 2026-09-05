# region MODULE_CONTRACT
# PURPOSE: Unit tests for SSHMachineRepository session-query methods.
# SCOPE: get_session (public port), list_connected.
# KEYWORDS: get_session, list_connected, session query
# endregion MODULE_CONTRACT

from __future__ import annotations

import time
from pathlib import PurePosixPath
from unittest.mock import MagicMock

import pytest
from asyncssh.connection import SSHClientConnection

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


def _make_mock_connection(ip: str = "10.0.0.1") -> MagicMock:
    return MagicMock(spec=SSHClientConnection)


def _make_session(
    hostname: str = "10.0.0.1",
    node_id: int = 1,
    platform: str = "linux",
    ncpus: int = 4,
    state: MachineState = MachineState.FREE,
) -> SSHMachineSession:
    """Create a fully-mocked SSHMachineSession (bypasses connect)."""
    adapter = _make_mock_adapter(platform=platform, ncpus=ncpus)
    conn = _make_mock_connection(ip=hostname)

    machine = ConnectedMachine(
        node_id=NodeId(node_id),
        platforms=(platform,),
        state=state,
        free_since=time.monotonic(),
    )

    return SSHMachineSession(
        hostname=hostname,
        conn=conn,
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
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """get_session returns the live MachineSession registered for ip, or None."""
        session = _make_session(hostname="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert repository.get_session(NodeId(1)) is session
        assert repository.get_session(NodeId(2)) is None

    def test_get_session_returns_none_after_disconnect(
        self,
        repository: SSHMachineRepository,
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

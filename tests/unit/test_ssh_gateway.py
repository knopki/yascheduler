# FILE: tests/unit/test_ssh_gateway.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineRepository + SSHMachineSession — connection lifecycle, command execution via session, SFTP via session, machine state via session, repository collection semantics.
#   SCOPE: SSHMachineRepository + SSHMachineSession with asyncssh fully mocked. No real SSH, SFTP, or platform detection.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-SESSION, M-DOMAIN-MODEL, M-PLATFORM-PROTOCOL
#   LINKS: M-SSH-REPOSITORY, M-SSH-SESSION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _AsyncIter - Simple async iterator from a list (avoids aclose warnings)
#   _make_mock_adapter - Build a mock RemoteMachineAdapter with async stubs
#   _make_mock_connection - Build a mock (conn, conn_opts) tuple with SFTP ctx
#   _make_state - Build a fully-mocked SSHMachineSession (bypasses connect); name kept for import-compat with sibling test modules
#   TestConnectionLifecycle - connect / disconnect / disconnect_all
#   TestListFree - list_free filtering by state and platform (returns sessions)
#   TestCommandExecution - run / run_full / run_bg via the operations facade taking a session
#   TestSessionFileTransfer - session.upload / session.open_sftp
#   TestRepositoryCollection - contains, len, get_session
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - simplify-cloud-connect-node-args: test_connect_returns_session drops the `username="root"` kwarg from connect; added test_connect_reads_username_and_port_from_node.
#   PREVIOUS_CHANGE: v1.1.0 - session-based-machine-handle: _make_state builds an SSHMachineSession; repository._machines → _sessions.
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.domain import Engine
from yascheduler.domain.model import (
    ConnectedMachine,
    MachineState,
    Node,
    NodeId,
    ProcessResult,
)
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.platform.protocol import ProcessInfo
from yascheduler.infra.ssh.repository import SSHMachineRepository
from yascheduler.infra.ssh.session import SSHMachineSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# =============================================================================
# Helpers
# =============================================================================


class _AsyncIter:
    """Simple async iterator from a list — avoids aclose() warnings from async generators."""

    def __init__(self, items: list) -> None:
        self._it = iter(items)

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self) -> Any:  # noqa: ANN401
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _make_mock_adapter(platform: str = "linux", ncpus: int = 4) -> MagicMock:
    """Create a mock adapter with async stubs for all platform methods."""
    adapter = MagicMock()
    adapter.platform = platform
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s

    async def _run(*args: object, **kwargs: Any) -> MagicMock:  # noqa: ANN401
        result = MagicMock()
        result.returncode = 0
        result.stdout = "stdout"
        result.stderr = ""
        return result

    adapter.run = _run

    async def _run_bg(*args: object, **kwargs: Any) -> MagicMock:  # noqa: ANN401
        return MagicMock()

    adapter.run_bg = _run_bg

    async def _get_cpu_cores(run_fn: object) -> int:
        return ncpus

    adapter.get_cpu_cores = _get_cpu_cores

    def _pgrep(*args: object, **kwargs: Any) -> _AsyncIter:  # noqa: ANN401
        proc = MagicMock(spec=ProcessInfo)
        proc.pid = 1234
        proc.name = "testproc"
        proc.command = "/usr/bin/testproc"
        return _AsyncIter([proc])

    adapter.pgrep = _pgrep

    def _list_processes(*args: object, **kwargs: Any) -> _AsyncIter:  # noqa: ANN401
        proc = MagicMock(spec=ProcessInfo)
        proc.pid = 1
        proc.name = "init"
        proc.command = "/sbin/init"
        return _AsyncIter([proc])

    adapter.list_processes = _list_processes

    adapter.setup_node = AsyncMock()

    return adapter


def _make_mock_connection(ip: str = "10.0.0.1") -> tuple[MagicMock, MagicMock]:
    """Create a mock connection with SFTP client context manager."""
    conn = MagicMock()
    conn._transport = MagicMock()
    conn._transport.is_closing.return_value = False
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()

    # SFTP client context manager
    sftp_client = AsyncMock()
    sftp_client.put = AsyncMock()
    sftp_client.get = AsyncMock()

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
        yield sftp_client

    conn.start_sftp_client = _sftp_ctx

    # -- connection options --
    conn_opts = MagicMock()
    conn_opts.host = ip
    conn_opts.port = 22
    conn_opts.username = "root"

    return conn, conn_opts


def _make_state(
    ip: str = "10.0.0.1",
    node_id: int = 1,
    platform: str = "linux",
    ncpus: int = 4,
    state: MachineState = MachineState.FREE,
) -> SSHMachineSession:
    """Create a fully-mocked SSHMachineSession (bypasses connect).

    Name kept as ``_make_state`` for import-compat with sibling test modules
    that ``from tests.unit.test_ssh_gateway import _make_state``.
    """
    adapter = _make_mock_adapter(platform=platform, ncpus=ncpus)
    conn, conn_opts = _make_mock_connection(ip=ip)

    machine = ConnectedMachine(
        node_id=NodeId(node_id),
        ip=ip,
        platform=platform,
        ncpus=ncpus,
        state=state,
        free_since=time.monotonic(),
    )

    return SSHMachineSession(
        ip=ip,
        conn=conn,
        conn_opts=conn_opts,
        machine=machine,
        adapter=adapter,
        platforms=[platform, "debian-like"],
        data_dir=PurePosixPath("./data"),
        engines_dir=PurePosixPath("./data/engines"),
        tasks_dir=PurePosixPath("./data/tasks"),
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def repository() -> SSHMachineRepository:
    return SSHMachineRepository()


@pytest.fixture
def operations(repository: SSHMachineRepository) -> SSHMachineOperations:
    return SSHMachineOperations(repository=repository)


@pytest.fixture
def mock_conn() -> MagicMock:
    """Mock SSHClientConnection with all async methods stubbed."""
    conn = MagicMock()
    conn._transport = MagicMock()
    conn._transport.is_closing.return_value = False
    conn.run = AsyncMock(return_value=MagicMock())
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()

    sftp_client = AsyncMock()
    sftp_client.put = AsyncMock()
    sftp_client.get = AsyncMock()

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
        yield sftp_client

    conn.start_sftp_client = _sftp_ctx
    return conn


@pytest.fixture
def mock_adapter() -> MagicMock:
    """Mock RemoteMachineAdapter with callable stubs."""
    adapter = MagicMock()
    adapter.platform = "linux"
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s
    adapter.run = AsyncMock()
    adapter.run_bg = AsyncMock()
    adapter.get_cpu_cores = AsyncMock(return_value=4)
    adapter.list_processes = MagicMock()
    adapter.pgrep = MagicMock()
    adapter.setup_node = AsyncMock()
    return adapter


@pytest.fixture
def mock_pengine() -> MagicMock:
    """Mock Engine for occupancy checks."""
    engine = MagicMock(spec=Engine)
    engine.name = "test_engine"
    engine.check_pname = None
    engine.check_cmd = None
    engine.check_cmd_code = 0
    engine.sleep_interval = 0.01
    return engine


# =============================================================================
# Connection Lifecycle
# =============================================================================


class TestConnectionLifecycle:
    """Connect, disconnect, disconnect_all."""

    @pytest.mark.asyncio
    async def test_connect_returns_session(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """connect() stores an SSHMachineSession in _sessions and returns it."""
        with (
            patch(
                "yascheduler.infra.ssh.repository.asyncssh.connection.connect",
                AsyncMock(return_value=mock_conn),
            ),
            patch(
                "yascheduler.infra.ssh.repository._detect_platform",
                AsyncMock(return_value=(mock_adapter, ["linux", "debian-like"])),
            ),
            patch(
                "yascheduler.infra.ssh.repository._init_paths",
                return_value=(
                    PurePosixPath("./data"),
                    PurePosixPath("./data/engines"),
                    PurePosixPath("./data/tasks"),
                ),
            ),
        ):
            node = Node(
                node_id=NodeId(1), ip="10.0.0.1", ncpus=4, username="root", port=22
            )
            session = await repository.connect(
                node=node,
                client_keys=[],
            )

        assert NodeId(1) in repository
        stored = repository._sessions[NodeId(1)]
        assert stored is session
        assert isinstance(session, SSHMachineSession)
        assert session.ip == "10.0.0.1"
        assert session.machine.state == MachineState.FREE
        assert session.is_closed is False

    @pytest.mark.asyncio
    async def test_connect_reads_username_and_port_from_node(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """connect() forwards node.username and node.port into _open_connection.

        connect takes no username/port parameters; the login user and port are
        read from the Node. A node with a non-default username/port reaches
        _open_connection with those exact values.
        """
        with (
            patch(
                "yascheduler.infra.ssh.repository._detect_platform",
                AsyncMock(return_value=(mock_adapter, ["linux", "debian-like"])),
            ),
            patch(
                "yascheduler.infra.ssh.repository._init_paths",
                return_value=(
                    PurePosixPath("./data"),
                    PurePosixPath("./data/engines"),
                    PurePosixPath("./data/tasks"),
                ),
            ),
            patch.object(
                repository,
                "_open_connection",
                new=AsyncMock(return_value=(mock_conn, MagicMock())),
            ) as open_conn,
        ):
            node = Node(
                node_id=NodeId(7),
                ip="10.0.0.7",
                ncpus=4,
                username="yascheduler",
                port=2222,
            )
            await repository.connect(node, client_keys=[])

        open_conn.assert_awaited_once()
        call_args, call_kwargs = open_conn.call_args
        # _open_connection signature: (ip, username, client_keys, *, port, ...)
        assert call_args[0] == "10.0.0.7"
        assert call_args[1] == "yascheduler"
        assert call_kwargs["port"] == 2222

    @pytest.mark.asyncio
    async def test_disconnect_removes_session(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect() removes the session from the repository."""
        session = _make_state()
        repository._sessions[NodeId(1)] = session
        await repository.disconnect(NodeId(1))
        assert NodeId(1) not in repository

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect() delegates teardown to session._close() (which closes conn)."""
        session = _make_state()
        repository._sessions[NodeId(1)] = session
        await repository.disconnect(NodeId(1))
        session._conn.close.assert_called_once()  # type: ignore[attr-defined]
        session._conn.wait_closed.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_disconnect_all_removes_all(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect_all() clears all sessions."""
        s1 = _make_state(ip="10.0.0.1", node_id=1)
        s2 = _make_state(ip="10.0.0.2", node_id=2)
        repository._sessions[NodeId(1)] = s1
        repository._sessions[NodeId(2)] = s2
        await repository.disconnect_all()
        assert len(repository) == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ip_does_nothing(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect() with no session does not raise."""
        await repository.disconnect(NodeId(99))  # should not raise


# =============================================================================
# List Free
# =============================================================================


class TestListFree:
    """list_free filtering by state and platform — returns sessions."""

    def test_list_free_returns_free_sessions(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free returns only FREE sessions."""
        s_free = _make_state(ip="10.0.0.1", node_id=1, state=MachineState.FREE)
        s_busy = _make_state(ip="10.0.0.2", node_id=2, state=MachineState.BUSY)
        repository._sessions[NodeId(1)] = s_free
        repository._sessions[NodeId(2)] = s_busy

        result = repository.list_free(platforms=None)
        assert len(result) == 1
        assert result[0].machine.ip == "10.0.0.1"

    def test_list_free_filters_by_platform(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free filters sessions by platform."""
        s_linux = _make_state(
            ip="10.0.0.1", node_id=1, platform="linux", state=MachineState.FREE
        )
        s_win = _make_state(
            ip="10.0.0.2", node_id=2, platform="windows", state=MachineState.FREE
        )
        repository._sessions[NodeId(1)] = s_linux
        repository._sessions[NodeId(2)] = s_win

        result = repository.list_free(platforms=["linux"])
        assert len(result) == 1
        assert result[0].machine.ip == "10.0.0.1"

    def test_list_free_empty_when_no_match(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free returns empty list when no sessions match."""
        s_linux = _make_state(
            ip="10.0.0.1", node_id=1, platform="linux", state=MachineState.FREE
        )
        repository._sessions[NodeId(1)] = s_linux

        result = repository.list_free(platforms=["windows"])
        assert len(result) == 0

    def test_list_free_skips_busy_session_matching_platform(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free excludes BUSY sessions even when platform matches."""
        s = _make_state(
            ip="10.0.0.1", node_id=1, platform="linux", state=MachineState.BUSY
        )
        repository._sessions[NodeId(1)] = s
        result = repository.list_free(platforms=["linux"])
        assert len(result) == 0

    def test_list_free_returns_oldest_first(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free sorts by session.machine.free_since ascending (oldest first)."""
        older = time.monotonic() - 100
        newer = time.monotonic() - 10
        s1 = _make_state(ip="10.0.0.1", node_id=1, state=MachineState.FREE)
        s2 = _make_state(ip="10.0.0.2", node_id=2, state=MachineState.FREE)
        # Override free_since for ordering via session.update
        s1.update(
            ConnectedMachine(
                node_id=NodeId(1),
                ip="10.0.0.1",
                platform="linux",
                ncpus=4,
                state=MachineState.FREE,
                free_since=older,
            )
        )
        s2.update(
            ConnectedMachine(
                node_id=NodeId(2),
                ip="10.0.0.2",
                platform="linux",
                ncpus=4,
                state=MachineState.FREE,
                free_since=newer,
            )
        )
        repository._sessions[NodeId(1)] = s1
        repository._sessions[NodeId(2)] = s2

        result = repository.list_free(platforms=None)
        assert result[0].machine.ip == "10.0.0.1"  # older free_since first


# =============================================================================
# Command Execution (via operations facade taking a session)
# =============================================================================


class TestCommandExecution:
    """run, run_full, run_bg via the operations facade (session-typed)."""

    @pytest.mark.asyncio
    async def test_run_returns_process_result(
        self, operations: SSHMachineOperations
    ) -> None:
        """run(session, cmd) returns a ProcessResult from the adapter output."""
        session = _make_state()
        result = await operations.run(session, "echo hello")
        assert isinstance(result, ProcessResult)
        assert result.exit_code == 0
        assert result.stdout == "stdout"
        assert result.stderr == ""

    @pytest.mark.asyncio
    async def test_run_delegates_to_session_run(
        self, operations: SSHMachineOperations
    ) -> None:
        """operations.run(session, cmd) delegates to session.run(cmd)."""
        session = _make_state()
        with patch.object(session, "run", AsyncMock()) as mock_run:
            mock_run.return_value = ProcessResult(exit_code=0, stdout="out", stderr="")
            result = await operations.run(session, "echo hello")
            mock_run.assert_awaited_once_with("echo hello")
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_full_returns_ssh_completed_process(
        self, operations: SSHMachineOperations
    ) -> None:
        """run_full(session, cmd) returns the raw adapter.run result."""
        session = _make_state()
        proc = await operations.run_full(session, "echo hello")
        assert proc.returncode == 0
        assert proc.stdout == "stdout"

    @pytest.mark.asyncio
    async def test_run_bg_starts_background_process(
        self, operations: SSHMachineOperations
    ) -> None:
        """run_bg(session, cmd, cwd=...) delegates to session.run_bg (returns None)."""
        session = _make_state()
        await operations.run_bg(session, "long_running", cwd="/tmp")


# =============================================================================
# File Transfer (on the session — facade no longer exposes upload/get_sftp)
# =============================================================================


class TestSessionFileTransfer:
    """session.upload / session.open_sftp."""

    @pytest.mark.asyncio
    async def test_session_upload_uses_sftp(self) -> None:
        """session.upload pushes file via SFTP put."""
        session = _make_state()
        local = Path("/tmp/local.txt")
        remote = "/remote/path/file.txt"

        await session.upload(local, remote)

        # Enter the sftp context to access the same singleton sftp mock
        async with session._conn.start_sftp_client() as sf:  # noqa: SLF001
            sf.put.assert_awaited_once_with(str(local), remote)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_session_open_sftp_context_manager(self) -> None:
        """session.open_sftp yields an SFTP client via async context manager."""
        session = _make_state()

        async with session.open_sftp() as sftp:
            assert sftp is not None
            assert hasattr(sftp, "put")
            assert hasattr(sftp, "get")


# =============================================================================
# Repository collection semantics
# =============================================================================


class TestRepositoryCollection:
    """contains, len, get_session."""

    def test_contains(self, repository: SSHMachineRepository) -> None:
        """__contains__ checks by NodeId."""
        session = _make_state(ip="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert NodeId(1) in repository
        assert NodeId(2) not in repository

    def test_len(self, repository: SSHMachineRepository) -> None:
        """__len__ returns session count."""
        repository._sessions[NodeId(1)] = _make_state(ip="10.0.0.1", node_id=1)
        repository._sessions[NodeId(2)] = _make_state(ip="10.0.0.2", node_id=2)
        assert len(repository) == 2

    def test_contains_method(self, repository: SSHMachineRepository) -> None:
        """contains() checks by NodeId (explicit method)."""
        session = _make_state(ip="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert repository.contains(NodeId(1)) is True
        assert repository.contains(NodeId(2)) is False

    def test_get_session_returns_live_or_none(
        self, repository: SSHMachineRepository
    ) -> None:
        """get_session(node_id) returns the registered session or None."""
        session = _make_state(ip="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert repository.get_session(NodeId(1)) is session
        assert repository.get_session(NodeId(2)) is None


# =============================================================================
# Session state transitions (occupy/release/update)
# =============================================================================


class TestSessionStateTransitions:
    """session.occupy / session.release / session.update."""

    def test_occupy_transitions_to_busy(self) -> None:
        """session.occupy() transitions snapshot to BUSY."""
        session = _make_state(state=MachineState.FREE)
        session.occupy()
        assert session.machine.state == MachineState.BUSY

    def test_release_transitions_to_free(self) -> None:
        """session.release() transitions snapshot to FREE with free_since set."""
        session = _make_state(state=MachineState.BUSY)
        before = time.monotonic()
        session.release()
        assert session.machine.state == MachineState.FREE
        assert session.machine.free_since is not None
        assert session.machine.free_since >= before

    def test_update_replaces_snapshot(self) -> None:
        """session.update(machine) replaces the internal snapshot."""
        session = _make_state(state=MachineState.FREE)
        busy = session.machine.occupy()
        session.update(busy)
        assert session.machine.state == MachineState.BUSY

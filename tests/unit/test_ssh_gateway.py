# region MODULE_CONTRACT
# PURPOSE: Unit tests for SSHMachineRepository + SSHMachineSession — connection lifecycle, command execution via session, SFTP via session, machine state via session, repository collection semantics.
# SCOPE: SSHMachineRepository + SSHMachineSession with asyncssh fully mocked. No real SSH, SFTP, or platform detection.
# KEYWORDS: SSHMachineRepository, SSHMachineSession, asyncssh mock
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.log_assertions import extra_fields
from yascheduler.domain import Engine
from yascheduler.domain.model import (
    ConnectedMachine,
    MachineState,
    Node,
    NodeId,
)
from yascheduler.infra.ssh.platform.types import ProcessInfo
from yascheduler.infra.ssh.repository import (
    DEFAULT_CONN_OPTS,
    SSHMachineRepository,
    _build_tunnel_options,
)
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

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


def _make_mock_adapter(platform: str = "linux", ncpus: int = 4) -> MagicMock:
    """Create a mock adapter with async stubs for all platform methods."""
    adapter = MagicMock()
    adapter.platform = platform
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s

    async def _run(*args: object, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.returncode = 0
        result.stdout = "stdout"
        result.stderr = ""
        return result

    adapter.run = _run

    async def _run_bg(*args: object, **kwargs: Any) -> MagicMock:
        proc = MagicMock()
        # run_bg best-effort early-exit detection awaits proc.wait(timeout=...).
        # Default mock: process keeps running past the grace window (timeout).
        proc.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        # On timeout, run_bg redirects stderr to DEVNULL — async.
        proc.redirect_stderr = AsyncMock()
        return proc

    adapter.run_bg = _run_bg

    adapter.get_cpu_cores = AsyncMock(return_value=ncpus)

    def _pgrep(*args: object, **kwargs: Any) -> _AsyncIter:
        proc = MagicMock(spec=ProcessInfo)
        proc.pid = 1234
        proc.name = "testproc"
        proc.command = "/usr/bin/testproc"
        return _AsyncIter([proc])

    adapter.pgrep = _pgrep

    def _list_processes(*args: object, **kwargs: Any) -> _AsyncIter:
        proc = MagicMock(spec=ProcessInfo)
        proc.pid = 1
        proc.name = "init"
        proc.command = "/sbin/init"
        return _AsyncIter([proc])

    adapter.list_processes = _list_processes

    adapter.setup_node = AsyncMock()

    return adapter


def _make_mock_connection(ip: str = "10.0.0.1") -> MagicMock:
    """Create a mock connection with SFTP client context manager."""
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
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

    return conn


def _make_state(
    hostname: str = "10.0.0.1",
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


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def repository() -> SSHMachineRepository:
    return SSHMachineRepository()


@pytest.fixture
def mock_conn() -> MagicMock:
    """Mock SSHClientConnection with all async methods stubbed."""
    conn = MagicMock()
    conn.is_closed = MagicMock(return_value=False)
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
# _build_tunnel_options
# =============================================================================


class TestBuildTunnelOptions:
    """_build_tunnel_options — builds SSHClientConnectionOptions or None."""

    def test_returns_none_when_no_jump_host(self) -> None:
        """Returns None when node.jump_host is None."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            jump_host=None,
        )
        result = _build_tunnel_options(node, client_keys=None, connect_timeout=None)
        assert result is None

    def test_returns_options_with_jump_host(self) -> None:
        """Returns SSHClientConnectionOptions with jump fields from node."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            jump_host="bastion.example.com",
            jump_port=2222,
            jump_username="jumper",
        )
        result = _build_tunnel_options(node, client_keys=None, connect_timeout=30)
        assert result is not None
        assert result.host == "bastion.example.com"
        assert result.port == 2222
        assert result.username == "jumper"
        assert result.known_hosts is None
        assert result.connect_timeout == 30

    def test_tunnel_options_inherits_destination_defaults(self) -> None:
        """Tunnel options inherit DEFAULT_CONN_OPTS (keepalive/compression)."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            jump_host="bastion.example.com",
        )
        result = _build_tunnel_options(node, client_keys=None, connect_timeout=None)
        assert result is not None
        assert result.keepalive_interval == DEFAULT_CONN_OPTS.keepalive_interval
        assert result.compression_algs == DEFAULT_CONN_OPTS.compression_algs
        assert result.known_hosts is None

    def test_tunnel_options_forwards_client_keys(self) -> None:
        """Tunnel leg receives the same client_keys passed to _build_tunnel_options."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            jump_host="bastion.example.com",
        )
        test_keys = [Path("/etc/yascheduler/keys/id_rsa")]
        with patch(
            "yascheduler.infra.ssh.repository.SSHClientConnectionOptions",
        ) as mock_cls:
            mock_cls.side_effect = lambda *args, **kwargs: MagicMock()
            _build_tunnel_options(node, client_keys=test_keys, connect_timeout=10)

        mock_cls.assert_called_once()
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs.get("client_keys") == test_keys

    def test_tunnel_options_forwards_empty_client_keys(self) -> None:
        """Tunnel leg receives () when client_keys is empty list."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            jump_host="bastion.example.com",
        )
        with patch(
            "yascheduler.infra.ssh.repository.SSHClientConnectionOptions",
        ) as mock_cls:
            mock_cls.side_effect = lambda *args, **kwargs: MagicMock()
            _build_tunnel_options(node, client_keys=[], connect_timeout=None)

        mock_cls.assert_called_once()
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs.get("client_keys") == ()

    def test_tunnel_options_forwards_none_client_keys(self) -> None:
        """Tunnel leg receives () when client_keys is None."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            jump_host="bastion.example.com",
        )
        with patch(
            "yascheduler.infra.ssh.repository.SSHClientConnectionOptions",
        ) as mock_cls:
            mock_cls.side_effect = lambda *args, **kwargs: MagicMock()
            _build_tunnel_options(node, client_keys=None, connect_timeout=None)

        mock_cls.assert_called_once()
        _, call_kwargs = mock_cls.call_args
        assert call_kwargs.get("client_keys") == ()


# =============================================================================
# Acceptance: connect reads jump identity from Node
# =============================================================================


class TestConnectJumpIdentity:
    """connect reads jump_host/jump_port/jump_username from Node."""

    @pytest.mark.asyncio
    async def test_connect_omits_tunnel_when_no_jump_host(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """Connect passes tunnel=None when node.jump_host is None."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            username="root",
            port=22,
            jump_host=None,
        )
        with (
            patch(
                "yascheduler.infra.ssh.repository.asyncssh.connection.connect",
                AsyncMock(return_value=mock_conn),
            ) as mock_connect,
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
            await repository.connect(node=node, client_keys=[])

        mock_connect.assert_awaited_once()
        _call_args, call_kwargs = mock_connect.call_args
        assert call_kwargs.get("tunnel") is None

    @pytest.mark.asyncio
    async def test_connect_reads_jump_identity_from_node(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """Connect builds tunnel from node.jump_host/jump_port/jump_username."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            username="root",
            port=22,
            jump_host="bastion.example.com",
            jump_port=2222,
            jump_username="jumper",
        )
        with (
            patch(
                "yascheduler.infra.ssh.repository.asyncssh.connection.connect",
                AsyncMock(return_value=mock_conn),
            ) as mock_connect,
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
            await repository.connect(node=node, client_keys=[])

        mock_connect.assert_awaited_once()
        _call_args, call_kwargs = mock_connect.call_args
        tunnel = call_kwargs.get("tunnel")
        assert tunnel is not None
        assert tunnel.host == "bastion.example.com"
        assert tunnel.port == 2222
        assert tunnel.username == "jumper"

    @pytest.mark.asyncio
    async def test_tunnel_leg_reuses_destination_options(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """Tunnel leg inherits known_hosts=None and connect_timeout from destination."""
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            username="root",
            port=22,
            jump_host="bastion.example.com",
            jump_port=2222,
            jump_username="jumper",
        )
        with (
            patch(
                "yascheduler.infra.ssh.repository.asyncssh.connection.connect",
                AsyncMock(return_value=mock_conn),
            ) as mock_connect,
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
            await repository.connect(node=node, client_keys=[], connect_timeout=10)

        mock_connect.assert_awaited_once()
        _call_args, call_kwargs = mock_connect.call_args
        tunnel = call_kwargs.get("tunnel")
        assert tunnel is not None
        assert tunnel.known_hosts is None
        assert tunnel.connect_timeout == 10

    @pytest.mark.asyncio
    async def test_tunnel_leg_forwards_client_keys(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """Tunnel leg SSHClientConnectionOptions receives same client_keys as destination leg."""
        test_keys = [Path("/etc/yascheduler/keys/id_rsa")]
        node = Node(
            node_id=NodeId(1),
            hostname="10.0.0.1",
            ncpus=4,
            username="root",
            port=22,
            jump_host="bastion.example.com",
            jump_port=2222,
            jump_username="jumper",
        )
        with (
            patch(
                "yascheduler.infra.ssh.repository.SSHClientConnectionOptions",
            ) as mock_opts_cls,
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
            mock_opts_cls.side_effect = lambda *args, **kwargs: MagicMock()
            await repository.connect(
                node=node,
                client_keys=test_keys,
                connect_timeout=10,
            )

        # Call 0: tunnel (_build_tunnel_options), Call 1: destination (_open_connection)
        assert mock_opts_cls.call_count == 2
        tunnel_kwargs = mock_opts_cls.call_args_list[0].kwargs
        dest_kwargs = mock_opts_cls.call_args_list[1].kwargs
        assert tunnel_kwargs.get("client_keys") == test_keys
        assert tunnel_kwargs.get("client_keys") == dest_kwargs.get("client_keys")


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
                node_id=NodeId(1),
                hostname="10.0.0.1",
                ncpus=4,
                username="root",
                port=22,
            )
            session = await repository.connect(
                node=node,
                client_keys=[],
            )

        assert NodeId(1) in repository
        stored = repository._sessions[NodeId(1)]
        assert stored is session
        assert isinstance(session, SSHMachineSession)
        assert session.hostname == "10.0.0.1"
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
                hostname="10.0.0.7",
                ncpus=4,
                username="yascheduler",
                port=2222,
            )
            await repository.connect(node, client_keys=[])

        open_conn.assert_awaited_once()
        call_args, call_kwargs = open_conn.call_args
        # _open_connection signature: (hostname, username, client_keys, *, port, ...)
        assert call_args[0] == "10.0.0.7"
        assert call_args[1] == "yascheduler"
        assert call_kwargs["port"] == 2222

    @pytest.mark.asyncio
    async def test_connect_logs_cpu_count_at_discovery_site(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """CPU-count log emitted from SSHMachineRepository.connect, NOT from setup_node."""
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
                node_id=NodeId(1),
                hostname="10.0.0.1",
                ncpus=4,
                username="root",
                port=22,
            )
            with caplog.at_level(
                logging.DEBUG,
                logger="yascheduler.infra.ssh.repository",
            ):
                await repository.connect(node=node, client_keys=[])

        # (a) CPU-count log emitted from connect path as a trace record
        cpu_trace = [r for r in caplog.records if r.getMessage() == "CPUS"]
        assert len(cpu_trace) == 1
        cpu_fields = extra_fields(cpu_trace[0])
        assert cpu_fields.get("hostname") == "10.0.0.1"
        assert cpu_fields.get("ncpus") == 4

        # (b) setup_node does NOT emit a CPU-count log (the old "CPUs count:" format is absent)
        assert not any("CPUs count" in r.getMessage() for r in caplog.records), (
            "setup_node should not emit CPU-count log"
        )

    @pytest.mark.asyncio
    async def test_disconnect_removes_session(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """disconnect() removes the session from the repository."""
        session = _make_state()
        repository._sessions[NodeId(1)] = session
        await repository.disconnect(NodeId(1))
        assert NodeId(1) not in repository

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """disconnect() delegates teardown to session._close() (which closes conn)."""
        session = _make_state()
        repository._sessions[NodeId(1)] = session
        await repository.disconnect(NodeId(1))
        session._conn.close.assert_called_once()  # type: ignore[attr-defined]
        session._conn.wait_closed.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_disconnect_all_removes_all(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """disconnect_all() clears all sessions."""
        s1 = _make_state(hostname="10.0.0.1", node_id=1)
        s2 = _make_state(hostname="10.0.0.2", node_id=2)
        repository._sessions[NodeId(1)] = s1
        repository._sessions[NodeId(2)] = s2
        await repository.disconnect_all()
        assert len(repository) == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ip_does_nothing(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """disconnect() with no session does not raise."""
        await repository.disconnect(NodeId(99))  # should not raise


# =============================================================================
# List Free
# =============================================================================


class TestListFree:
    """list_free filtering by state and platform — returns sessions."""

    def test_list_free_returns_free_sessions(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """list_free returns only FREE sessions."""
        s_free = _make_state(hostname="10.0.0.1", node_id=1, state=MachineState.FREE)
        s_busy = _make_state(hostname="10.0.0.2", node_id=2, state=MachineState.BUSY)
        repository._sessions[NodeId(1)] = s_free
        repository._sessions[NodeId(2)] = s_busy

        result = repository.list_free(platforms=None)
        assert len(result) == 1
        assert result[0].hostname == "10.0.0.1"

    def test_list_free_filters_by_platform(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """list_free filters sessions by platform."""
        s_linux = _make_state(
            hostname="10.0.0.1",
            node_id=1,
            platform="linux",
            state=MachineState.FREE,
        )
        s_win = _make_state(
            hostname="10.0.0.2",
            node_id=2,
            platform="windows",
            state=MachineState.FREE,
        )
        repository._sessions[NodeId(1)] = s_linux
        repository._sessions[NodeId(2)] = s_win

        result = repository.list_free(platforms=["linux"])
        assert len(result) == 1
        assert result[0].hostname == "10.0.0.1"

    def test_list_free_empty_when_no_match(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """list_free returns empty list when no sessions match."""
        s_linux = _make_state(
            hostname="10.0.0.1",
            node_id=1,
            platform="linux",
            state=MachineState.FREE,
        )
        repository._sessions[NodeId(1)] = s_linux

        result = repository.list_free(platforms=["windows"])
        assert len(result) == 0

    def test_list_free_skips_busy_session_matching_platform(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """list_free excludes BUSY sessions even when platform matches."""
        s = _make_state(
            hostname="10.0.0.1",
            node_id=1,
            platform="linux",
            state=MachineState.BUSY,
        )
        repository._sessions[NodeId(1)] = s
        result = repository.list_free(platforms=["linux"])
        assert len(result) == 0

    def test_list_free_returns_oldest_first(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """list_free sorts by session.machine.free_since ascending (oldest first)."""
        older = time.monotonic() - 100
        newer = time.monotonic() - 10
        s1 = _make_state(hostname="10.0.0.1", node_id=1, state=MachineState.FREE)
        s2 = _make_state(hostname="10.0.0.2", node_id=2, state=MachineState.FREE)
        # Override free_since for ordering via session.update
        s1.update(
            ConnectedMachine(
                node_id=NodeId(1),
                platforms=("linux",),
                state=MachineState.FREE,
                free_since=older,
            ),
        )
        s2.update(
            ConnectedMachine(
                node_id=NodeId(2),
                platforms=("linux",),
                state=MachineState.FREE,
                free_since=newer,
            ),
        )
        repository._sessions[NodeId(1)] = s1
        repository._sessions[NodeId(2)] = s2

        result = repository.list_free(platforms=None)
        assert result[0].hostname == "10.0.0.1"  # older free_since first


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
        async with session._conn.start_sftp_client() as sf:
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
    """contains, len, get_session, init."""

    def test_init_owns_sessions_dict(self) -> None:
        """Repository init creates only _sessions dict (no _machines or _monitors)."""
        repo = SSHMachineRepository()
        assert hasattr(repo, "_sessions")
        assert not hasattr(repo, "_machines")
        assert not hasattr(repo, "_monitors")

    def test_contains(self, repository: SSHMachineRepository) -> None:
        """__contains__ checks by NodeId."""
        session = _make_state(hostname="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert NodeId(1) in repository
        assert NodeId(2) not in repository

    def test_len(self, repository: SSHMachineRepository) -> None:
        """__len__ returns session count."""
        repository._sessions[NodeId(1)] = _make_state(hostname="10.0.0.1", node_id=1)
        repository._sessions[NodeId(2)] = _make_state(hostname="10.0.0.2", node_id=2)
        assert len(repository) == 2

    def test_contains_method(self, repository: SSHMachineRepository) -> None:
        """contains() checks by NodeId (explicit method)."""
        session = _make_state(hostname="10.0.0.1", node_id=1)
        repository._sessions[NodeId(1)] = session
        assert repository.contains(NodeId(1)) is True
        assert repository.contains(NodeId(2)) is False

    def test_get_session_returns_live_or_none(
        self,
        repository: SSHMachineRepository,
    ) -> None:
        """get_session(node_id) returns the registered session or None."""
        session = _make_state(hostname="10.0.0.1", node_id=1)
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


# =============================================================================
# Session CPU cache
# =============================================================================


class TestSessionCpuCache:
    """SSHMachineSession.get_cpu_cores memoizes per session."""

    @pytest.mark.asyncio
    async def test_first_call_invokes_adapter_and_second_call_returns_cache(
        self,
    ) -> None:
        """First call invokes adapter; second call returns cached value."""
        session = _make_state()
        adapter_mock = session._adapter.get_cpu_cores  # type: ignore[attr-defined]
        assert await session.get_cpu_cores() == 4
        adapter_mock.assert_awaited_once()  # type: ignore[attr-defined]
        assert await session.get_cpu_cores() == 4
        adapter_mock.assert_awaited_once()  # still once  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_cache_miss_retries_and_cache_hit_skips_retry(self) -> None:
        """Cache miss retries on adapter failure; cache hit returns without retry."""
        # Cache hit — adapter would fail but is not called
        session = _make_state()
        session._cached_ncpus = 4  # prime the cache
        adapter_mock = session._adapter.get_cpu_cores  # type: ignore[attr-defined]
        adapter_mock.side_effect = OSError("should not be called")  # type: ignore[attr-defined]
        assert await session.get_cpu_cores() == 4
        adapter_mock.assert_not_awaited()  # type: ignore[attr-defined]
        # Cache miss — retries on SSH failure
        fresh = _make_state()
        fresh._cached_ncpus = None
        fresh_mock = fresh._adapter.get_cpu_cores  # type: ignore[attr-defined]
        fresh_mock.side_effect = [OSError("ssh failed"), 4]  # type: ignore[attr-defined]
        result = await fresh.get_cpu_cores()
        assert result == 4
        assert fresh_mock.await_count == 2  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_reconnected_session_rediscovers(self) -> None:
        """Reconnected session starts with empty cache and re-discovers."""
        session = _make_state()
        session._prime_ncpus_cache(4)
        fresh_session = _make_state()  # Simulates reconnect — fresh cache
        adapter_mock = fresh_session._adapter.get_cpu_cores  # type: ignore[attr-defined]
        assert await fresh_session.get_cpu_cores() == 4
        adapter_mock.assert_awaited_once()  # type: ignore[attr-defined]

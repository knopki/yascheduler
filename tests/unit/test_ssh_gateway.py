# FILE: tests/unit/test_ssh_gateway.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineGateway — connection lifecycle, command execution, SFTP, occupancy monitoring.
#   SCOPE: SSHMachineGateway with asyncssh fully mocked. No real SSH, SFTP, or platform detection.
#   DEPENDS: M-SSH-GATEWAY, M-DOMAIN-MODEL, M-PLATFORM-PROTOCOL
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestConnectionLifecycle - connect / disconnect / disconnect_all
#   TestListFree - list_free filtering by state and platform
#   TestCommandExecution - run / run_full / run_bg
#   TestFileTransfer - upload / download / get_sftp context manager
#   TestMachineState - update_machine, contains, len, keys, items, register_machine
#   TestPropertyHelpers - get_adapter, get_platforms, get_hostname, get_path, get_quote
#   TestOccupancy - occupancy_check via pgrep and check_cmd, start_occupancy_check background task
#   TestAdvancedOperations - setup_node, get_cpu_cores, pgrep generator, list_processes generator
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Split _make_state into _make_mock_adapter + _make_mock_connection + _make_state for GRACE func-size compliance.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.adapters.ssh.gateway import SSHMachineGateway, _MachineState
from yascheduler.adapters.ssh.platform.protocol import (
    ChannelOpenError,
    PEngine,
    PEngineRepository,
    PProcessInfo,
)
from yascheduler.domain.model import ConnectedMachine, MachineState, ProcessResult

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
            raise StopAsyncIteration


def _make_mock_adapter(platform: str = "linux", ncpus: int = 4) -> MagicMock:
    """Create a mock adapter with async stubs for all platform methods."""
    from unittest.mock import MagicMock as _MM

    adapter = _MM()
    adapter.platform = platform
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s

    async def _run(*args: object, **kwargs: Any) -> _MM:
        result = _MM()
        result.returncode = 0
        result.stdout = "stdout"
        result.stderr = ""
        return result

    adapter.run = _run

    async def _run_bg(*args: object, **kwargs: Any) -> _MM:
        return _MM()

    adapter.run_bg = _run_bg

    async def _get_cpu_cores(run_fn: object) -> int:
        return ncpus

    adapter.get_cpu_cores = _get_cpu_cores

    def _pgrep(*args: object, **kwargs: Any) -> _AsyncIter:
        proc = _MM(spec=PProcessInfo)
        proc.pid = 1234
        proc.name = "testproc"
        proc.command = "/usr/bin/testproc"
        return _AsyncIter([proc])

    adapter.pgrep = _pgrep

    def _list_processes(*args: object, **kwargs: Any) -> _AsyncIter:
        proc = _MM(spec=PProcessInfo)
        proc.pid = 1
        proc.name = "init"
        proc.command = "/sbin/init"
        return _AsyncIter([proc])

    adapter.list_processes = _list_processes

    adapter.setup_node = AsyncMock()

    return adapter


def _make_mock_connection(ip: str = "10.0.0.1") -> tuple[MagicMock, MagicMock]:
    """Create a mock connection with SFTP client context manager."""
    from unittest.mock import MagicMock as _MM

    conn = _MM()
    conn._transport = _MM()
    conn._transport.is_closing.return_value = False
    conn.close = _MM()
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
    conn_opts = _MM()
    conn_opts.host = ip
    conn_opts.port = 22
    conn_opts.username = "root"

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


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def gateway() -> SSHMachineGateway:
    return SSHMachineGateway()


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
    """Mock PEngine for occupancy checks."""
    engine = MagicMock(spec=PEngine)
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
    async def test_connect_stores_machine(
        self, gateway: SSHMachineGateway, mock_conn: MagicMock, mock_adapter: MagicMock
    ) -> None:
        """connect() stores a _MachineState in _machines."""
        with (
            patch(
                "yascheduler.adapters.ssh.gateway.asyncssh.connection.connect",
                AsyncMock(return_value=mock_conn),
            ),
            patch(
                "yascheduler.adapters.ssh.gateway._detect_platform",
                AsyncMock(return_value=(mock_adapter, ["linux", "debian-like"])),
            ),
            patch(
                "yascheduler.adapters.ssh.gateway._init_paths",
                return_value=(
                    PurePosixPath("./data"),
                    PurePosixPath("./data/engines"),
                    PurePosixPath("./data/tasks"),
                ),
            ),
        ):
            machine = await gateway.connect(
                ip="10.0.0.1",
                username="root",
                client_keys=[],
            )

        assert "10.0.0.1" in gateway
        assert gateway._machines["10.0.0.1"].machine is machine
        assert gateway._machines["10.0.0.1"].machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_connect_returns_connected_machine(
        self, gateway: SSHMachineGateway, mock_conn: MagicMock, mock_adapter: MagicMock
    ) -> None:
        """connect() returns a ConnectedMachine with correct IP and platform."""
        with (
            patch(
                "yascheduler.adapters.ssh.gateway.asyncssh.connection.connect",
                AsyncMock(return_value=mock_conn),
            ),
            patch(
                "yascheduler.adapters.ssh.gateway._detect_platform",
                AsyncMock(return_value=(mock_adapter, ["linux", "debian-like"])),
            ),
            patch(
                "yascheduler.adapters.ssh.gateway._init_paths",
                return_value=(
                    PurePosixPath("./data"),
                    PurePosixPath("./data/engines"),
                    PurePosixPath("./data/tasks"),
                ),
            ),
        ):
            machine = await gateway.connect(
                ip="10.0.0.1",
                username="root",
                client_keys=[],
            )

        assert isinstance(machine, ConnectedMachine)
        assert machine.ip == "10.0.0.1"
        assert machine.platform == "linux"
        assert machine.ncpus == 4
        assert machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_disconnect_removes_machine(self, gateway: SSHMachineGateway) -> None:
        """disconnect() removes the machine from the registry."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        await gateway.disconnect("10.0.0.1")
        assert "10.0.0.1" not in gateway

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(
        self, gateway: SSHMachineGateway
    ) -> None:
        """disconnect() calls conn.close() and conn.wait_closed()."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        await gateway.disconnect("10.0.0.1")
        state.conn.close.assert_called_once()  # type: ignore[attr-defined]
        state.conn.wait_closed.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_disconnect_all_removes_all(self, gateway: SSHMachineGateway) -> None:
        """disconnect_all() clears all machines."""
        s1 = _make_state(ip="10.0.0.1")
        s2 = _make_state(ip="10.0.0.2")
        gateway._machines["10.0.0.1"] = s1
        gateway._machines["10.0.0.2"] = s2
        await gateway.disconnect_all()
        assert len(gateway) == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ip_does_nothing(
        self, gateway: SSHMachineGateway
    ) -> None:
        """disconnect() with no state does not raise."""
        await gateway.disconnect("10.0.0.99")  # should not raise


# =============================================================================
# List Free
# =============================================================================


class TestListFree:
    """list_free filtering by state and platform."""

    def test_list_free_returns_free_machines(self, gateway: SSHMachineGateway) -> None:
        """list_free returns only FREE machines."""
        s_free = _make_state(ip="10.0.0.1", state=MachineState.FREE)
        s_busy = _make_state(ip="10.0.0.2", state=MachineState.BUSY)
        gateway._machines["10.0.0.1"] = s_free
        gateway._machines["10.0.0.2"] = s_busy

        result = gateway.list_free(platforms=None)
        assert len(result) == 1
        assert result[0].ip == "10.0.0.1"

    def test_list_free_filters_by_platform(self, gateway: SSHMachineGateway) -> None:
        """list_free filters machines by platform."""
        s_linux = _make_state(ip="10.0.0.1", platform="linux", state=MachineState.FREE)
        s_win = _make_state(ip="10.0.0.2", platform="windows", state=MachineState.FREE)
        gateway._machines["10.0.0.1"] = s_linux
        gateway._machines["10.0.0.2"] = s_win

        result = gateway.list_free(platforms=["linux"])
        assert len(result) == 1
        assert result[0].ip == "10.0.0.1"

    def test_list_free_empty_when_no_match(self, gateway: SSHMachineGateway) -> None:
        """list_free returns empty list when no machines match."""
        s_linux = _make_state(ip="10.0.0.1", platform="linux", state=MachineState.FREE)
        gateway._machines["10.0.0.1"] = s_linux

        result = gateway.list_free(platforms=["windows"])
        assert len(result) == 0

    def test_list_free_skips_busy_machine_matching_platform(
        self, gateway: SSHMachineGateway
    ) -> None:
        """list_free excludes BUSY machines even when platform matches."""
        s = _make_state(ip="10.0.0.1", platform="linux", state=MachineState.BUSY)
        gateway._machines["10.0.0.1"] = s
        result = gateway.list_free(platforms=["linux"])
        assert len(result) == 0

    def test_list_free_returns_oldest_first(self, gateway: SSHMachineGateway) -> None:
        """list_free sorts by free_since ascending (oldest first)."""
        import time

        older = time.monotonic() - 100
        newer = time.monotonic() - 10
        s1 = _make_state(ip="10.0.0.1", state=MachineState.FREE)
        s2 = _make_state(ip="10.0.0.2", state=MachineState.FREE)
        # Override free_since for ordering
        s1 = _MachineState(
            conn=s1.conn,
            conn_opts=s1.conn_opts,
            machine=ConnectedMachine(
                ip="10.0.0.1",
                platform="linux",
                ncpus=4,
                state=MachineState.FREE,
                free_since=older,
            ),
            adapter=s1.adapter,
            platforms=s1.platforms,
            data_dir=s1.data_dir,
            engines_dir=s1.engines_dir,
            tasks_dir=s1.tasks_dir,
        )
        s2 = _MachineState(
            conn=s2.conn,
            conn_opts=s2.conn_opts,
            machine=ConnectedMachine(
                ip="10.0.0.2",
                platform="linux",
                ncpus=4,
                state=MachineState.FREE,
                free_since=newer,
            ),
            adapter=s2.adapter,
            platforms=s2.platforms,
            data_dir=s2.data_dir,
            engines_dir=s2.engines_dir,
            tasks_dir=s2.tasks_dir,
        )
        gateway._machines["10.0.0.1"] = s1
        gateway._machines["10.0.0.2"] = s2

        result = gateway.list_free(platforms=None)
        assert result[0].ip == "10.0.0.1"  # older free_since first


# =============================================================================
# Command Execution
# =============================================================================


class TestCommandExecution:
    """run, run_full, run_bg."""

    @pytest.mark.asyncio
    async def test_run_returns_process_result(self, gateway: SSHMachineGateway) -> None:
        """run() returns a ProcessResult from the adapter output."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        result = await gateway.run(state.machine, "echo hello")

        assert isinstance(result, ProcessResult)
        assert result.exit_code == 0
        assert result.stdout == "stdout"
        assert result.stderr == ""

    @pytest.mark.asyncio
    async def test_run_delegates_to_run_full(self, gateway: SSHMachineGateway) -> None:
        """run() internally calls run_full()."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        with patch.object(gateway, "run_full", AsyncMock()) as mock_run_full:
            mock_run_full.return_value = MagicMock(
                returncode=0, stdout="out", stderr=""
            )
            result = await gateway.run(state.machine, "echo hello")
            mock_run_full.assert_awaited_once_with(state.machine, "echo hello")
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_full_returns_ssh_completed_process(
        self, gateway: SSHMachineGateway
    ) -> None:
        """run_full() returns the raw adapter.run result."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        proc = await gateway.run_full(state.machine, "echo hello")
        assert proc.returncode == 0
        assert proc.stdout == "stdout"

    @pytest.mark.asyncio
    async def test_run_bg_starts_background_process(
        self, gateway: SSHMachineGateway
    ) -> None:
        """run_bg() delegates to adapter.run_bg and returns a process handle."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        proc = await gateway.run_bg(state.machine, "long_running", cwd="/tmp")
        # The adapter returns a MagicMock, so proc should be our mock
        assert proc is not None

    @pytest.mark.asyncio
    async def test_run_full_raises_key_error_for_unknown_ip(
        self, gateway: SSHMachineGateway
    ) -> None:
        """run_full() raises KeyError when machine is not registered."""
        machine = ConnectedMachine(ip="10.0.0.99", platform="linux", ncpus=4)
        with pytest.raises(KeyError):
            await gateway.run_full(machine, "echo hello")


# =============================================================================
# File Transfer
# =============================================================================


class TestFileTransfer:
    """upload, download, get_sftp context manager."""

    @pytest.mark.asyncio
    async def test_upload_uses_sftp(self, gateway: SSHMachineGateway) -> None:
        """upload() pushes file via SFTP put."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        local = Path("/tmp/local.txt")
        remote = "/remote/path/file.txt"

        await gateway.upload(state.machine, local, remote)

        # Enter the sftp context to access the same singleton sftp mock
        async with state.conn.start_sftp_client() as sf:
            sf.put.assert_awaited_once_with(str(local), remote)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_download_uses_sftp(self, gateway: SSHMachineGateway) -> None:
        """download() pulls file via SFTP get."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        local = Path("/tmp/local.txt")
        remote = "/remote/path/file.txt"

        await gateway.download(state.machine, remote, local)

        async with state.conn.start_sftp_client() as sf:
            sf.get.assert_awaited_once_with(remote, str(local))  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_get_sftp_context_manager(self, gateway: SSHMachineGateway) -> None:
        """get_sftp yields an SFTP client via async context manager."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        async with gateway.get_sftp("10.0.0.1") as sftp:
            assert sftp is not None
            # The sftp client should be our mock
            assert hasattr(sftp, "put")
            assert hasattr(sftp, "get")


# =============================================================================
# Machine State
# =============================================================================


class TestMachineState:
    """update_machine, contains, len, keys, items, register_machine."""

    def test_update_machine_replaces_state(self, gateway: SSHMachineGateway) -> None:
        """update_machine() replaces the ConnectedMachine in the state."""
        state = _make_state(ip="10.0.0.1", state=MachineState.FREE)
        gateway._machines["10.0.0.1"] = state

        updated = state.machine.occupy()
        gateway.update_machine(updated)

        assert gateway._machines["10.0.0.1"].machine.state == MachineState.BUSY

    def test_update_machine_unknown_ip_does_nothing(
        self, gateway: SSHMachineGateway
    ) -> None:
        """update_machine() with unknown IP silently does nothing."""
        machine = ConnectedMachine(ip="10.0.0.99", platform="linux", ncpus=4)
        gateway.update_machine(machine)  # should not raise

    def test_contains(self, gateway: SSHMachineGateway) -> None:
        """__contains__ checks by IP."""
        state = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.1"] = state
        assert "10.0.0.1" in gateway
        assert "10.0.0.2" not in gateway

    def test_len(self, gateway: SSHMachineGateway) -> None:
        """__len__ returns machine count."""
        gateway._machines["10.0.0.1"] = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.2"] = _make_state(ip="10.0.0.2")
        assert len(gateway) == 2

    def test_keys(self, gateway: SSHMachineGateway) -> None:
        """keys() returns all IPs."""
        gateway._machines["10.0.0.1"] = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.2"] = _make_state(ip="10.0.0.2")
        assert set(gateway.keys()) == {"10.0.0.1", "10.0.0.2"}

    def test_items(self, gateway: SSHMachineGateway) -> None:
        """items() returns (ip, state) pairs."""
        state = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.1"] = state
        items = dict(gateway.items())
        assert items["10.0.0.1"] is state

    def test_register_machine(self, gateway: SSHMachineGateway) -> None:
        """register_machine stores a _MachineState by IP."""
        state = _make_state(ip="10.0.0.1")
        gateway.register_machine("10.0.0.1", state)
        assert "10.0.0.1" in gateway
        assert gateway._machines["10.0.0.1"] is state

    def test_contains_method(self, gateway: SSHMachineGateway) -> None:
        """contains() checks by IP (explicit method)."""
        state = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.1"] = state
        assert gateway.contains("10.0.0.1") is True
        assert gateway.contains("10.0.0.2") is False

    def test_get_machine_state(self, gateway: SSHMachineGateway) -> None:
        """get_machine_state returns _MachineState or None."""
        state = _make_state(ip="10.0.0.1")
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_machine_state("10.0.0.1") is state
        assert gateway.get_machine_state("10.0.0.2") is None


# =============================================================================
# Property Helpers
# =============================================================================


class TestPropertyHelpers:
    """get_adapter, get_platforms, get_hostname, get_path, get_quote."""

    def test_get_adapter(self, gateway: SSHMachineGateway) -> None:
        """get_adapter returns the RemoteMachineAdapter."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_adapter("10.0.0.1") is state.adapter

    def test_get_platforms(self, gateway: SSHMachineGateway) -> None:
        """get_platforms returns the platform list."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_platforms("10.0.0.1") == ["linux", "debian-like"]

    def test_get_hostname(self, gateway: SSHMachineGateway) -> None:
        """get_hostname returns the host from conn_opts."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_hostname("10.0.0.1") == "10.0.0.1"

    def test_get_path(self, gateway: SSHMachineGateway) -> None:
        """get_path returns the adapter's path type."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_path("10.0.0.1") is PurePosixPath

    def test_get_quote(self, gateway: SSHMachineGateway) -> None:
        """get_quote returns the adapter's quote callable."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert callable(gateway.get_quote("10.0.0.1"))
        assert gateway.get_quote("10.0.0.1")("test") == "test"

    def test_get_data_dir(self, gateway: SSHMachineGateway) -> None:
        """get_data_dir returns the data directory."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_data_dir("10.0.0.1") == PurePosixPath("./data")

    def test_get_engines_dir(self, gateway: SSHMachineGateway) -> None:
        """get_engines_dir returns the engines directory."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_engines_dir("10.0.0.1") == PurePosixPath("./data/engines")

    def test_get_tasks_dir(self, gateway: SSHMachineGateway) -> None:
        """get_tasks_dir returns the tasks directory."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        assert gateway.get_tasks_dir("10.0.0.1") == PurePosixPath("./data/tasks")


# =============================================================================
# Occupancy
# =============================================================================


class TestOccupancy:
    """occupancy_check via pgrep and check_cmd, start_occupancy_check."""

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_found(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns True when pgrep yields a process."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "testproc"

        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_not_found(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns False when pgrep yields no process."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "nonexistent"

        # Override adapter.pgrep to yield nothing
        state.adapter.pgrep = lambda *a, **kw: _AsyncIter([])  # type: ignore[assignment,misc]

        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_match(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns True when check_cmd exit code matches."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        # Override adapter.run to return matching exit code
        async def _run_match(*args: object, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "active"
            result.stderr = ""
            return result

        state.adapter.run = _run_match  # type: ignore[assignment,misc]

        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_no_match(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns False when check_cmd exit code differs."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        async def _run_mismatch(*args: object, **kwargs: Any) -> MagicMock:
            result = MagicMock()
            result.returncode = 3  # service not running
            result.stdout = "inactive"
            result.stderr = ""
            return result

        state.adapter.run = _run_mismatch  # type: ignore[assignment,misc]

        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_uses_pgrep_when_both_set(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check prefers pgrep when check_pname is set even with check_cmd."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "testproc"
        mock_pengine.check_cmd = "systemctl is-active test"
        mock_pengine.check_cmd_code = 0

        # pgrep_found = True should short-circuit and return True
        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_no_checks_configured(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns False when neither check_pname nor check_cmd is set."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is False

    @pytest.mark.asyncio
    async def test_occupancy_check_pgrep_ssh_failure_returns_true(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns True (busy) when pgrep fails due to SSH error."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = "sleep"

        # Replace adapter.pgrep with one that raises SSHRetryExc
        async def _pgrep_ssh_fail(*args: object, **kwargs: object):
            raise ChannelOpenError(1, "SSH connection lost")
            yield  # makes this an async generator

        state.adapter.pgrep = _pgrep_ssh_fail  # type: ignore[assignment,misc]

        result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_occupancy_check_cmd_ssh_failure_returns_true(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """occupancy_check returns True (busy) when check_cmd fails due to SSH error."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = "ps -eocomm= | grep -q sleep"
        mock_pengine.check_cmd_code = 0

        # Patch run_full to raise SSHRetryExc — simulates SSH failure
        with patch.object(
            gateway,
            "run_full",
            AsyncMock(side_effect=ChannelOpenError(1, "SSH connection lost")),
        ):
            result = await gateway.occupancy_check("10.0.0.1", mock_pengine)
        assert result is True

    @pytest.mark.asyncio
    async def test_start_occupancy_check_releases_machine(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """start_occupancy_check background task releases machine when occupancy ends."""
        ip = "10.0.0.1"
        state = _make_state(ip=ip, state=MachineState.BUSY)
        gateway._machines[ip] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        with (
            patch("yascheduler.adapters.ssh.gateway.asyncio.sleep", AsyncMock()),
            patch.object(gateway, "occupancy_check", AsyncMock(return_value=False)),
        ):
            gateway.start_occupancy_check(ip, mock_pengine)
            # Wait for the background task to complete
            task = list(gateway._bg_tasks)[0]
            await asyncio.wait_for(task, timeout=1.0)

        # Machine should be released
        assert gateway._machines[ip].machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_start_occupancy_check_cancelled_gracefully(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """Start occupancy check then cancel it (disconnect)."""

        ip = "10.0.0.1"
        state = _make_state(ip=ip, state=MachineState.BUSY)
        gateway._machines[ip] = state
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None

        with (
            patch("yascheduler.adapters.ssh.gateway.asyncio.sleep", AsyncMock()),
            patch.object(
                gateway,
                "occupancy_check",
                AsyncMock(side_effect=[True, True, True]),
            ),
        ):
            gateway.start_occupancy_check(ip, mock_pengine)
            # Let the task start and do one iteration
            await asyncio.sleep(0)

            # Disconnect cancels the background task
            await gateway.disconnect(ip)

        # Machine removed
        assert ip not in gateway


# =============================================================================
# Advanced Operations
# =============================================================================


class TestAdvancedOperations:
    """setup_node, get_cpu_cores, pgrep generator, list_processes generator."""

    @pytest.mark.asyncio
    async def test_setup_node(self, gateway: SSHMachineGateway) -> None:
        """setup_node delegates to adapter.setup_node with filtered engines."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        engine_repo = MagicMock(spec=PEngineRepository)
        engine_repo.filter_platforms.return_value = engine_repo

        await gateway.setup_node("10.0.0.1", engine_repo)

        engine_repo.filter_platforms.assert_called_once_with(state.platforms)
        state.adapter.setup_node.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_get_cpu_cores(self, gateway: SSHMachineGateway) -> None:
        """get_cpu_cores returns count from adapter."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        cores = await gateway.get_cpu_cores("10.0.0.1")
        assert cores == 4

    @pytest.mark.asyncio
    async def test_pgrep_yields_processes(self, gateway: SSHMachineGateway) -> None:
        """pgrep yields process info objects."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        results: list[PProcessInfo] = []
        async for proc in gateway.pgrep("10.0.0.1", "testproc"):
            results.append(proc)

        assert len(results) == 1
        assert results[0].pid == 1234

    @pytest.mark.asyncio
    async def test_list_processes_yields_processes(
        self, gateway: SSHMachineGateway
    ) -> None:
        """list_processes yields all running processes."""
        state = _make_state()
        gateway._machines["10.0.0.1"] = state

        results: list[PProcessInfo] = []
        async for proc in gateway.list_processes("10.0.0.1"):
            results.append(proc)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_pgrep_unknown_ip(self, gateway: SSHMachineGateway) -> None:
        """pgrep raises KeyError for unknown IP."""
        with pytest.raises(KeyError):
            async for _ in gateway.pgrep("10.0.0.99", "test"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_list_processes_unknown_ip(self, gateway: SSHMachineGateway) -> None:
        """list_processes raises KeyError for unknown IP."""
        with pytest.raises(KeyError):
            async for _ in gateway.list_processes("10.0.0.99"):
                pass  # pragma: no cover

    @pytest.mark.asyncio
    async def test_setup_node_unknown_ip(self, gateway: SSHMachineGateway) -> None:
        """setup_node raises KeyError for unknown IP."""
        engine_repo = MagicMock(spec=PEngineRepository)
        with pytest.raises(KeyError):
            await gateway.setup_node("10.0.0.99", engine_repo)

    @pytest.mark.asyncio
    async def test_get_cpu_cores_unknown_ip(self, gateway: SSHMachineGateway) -> None:
        """get_cpu_cores raises KeyError for unknown IP."""
        with pytest.raises(KeyError):
            await gateway.get_cpu_cores("10.0.0.99")

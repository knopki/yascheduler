# FILE: tests/unit/test_ssh_gateway.py
# VERSION: 1.0.3
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineRepository + SSHMachineOperations — connection lifecycle, command execution, SFTP, machine state, property helpers.
#   SCOPE: SSHMachineRepository + SSHMachineOperations with asyncssh fully mocked. No real SSH, SFTP, or platform detection.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-DOMAIN-MODEL, M-PLATFORM-PROTOCOL
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestConnectionLifecycle - connect / disconnect / disconnect_all
#   TestListFree - list_free filtering by state and platform
#   TestCommandExecution - run / run_full / run_bg
#   TestFileTransfer - upload / download / get_sftp context manager
#   TestMachineState - update_machine, contains, len, keys, items, register_machine
#   TestPropertyHelpers - get_adapter, get_platforms, get_hostname, get_path, get_quote
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.4 - Extract TestOccupancy + TestAdvancedOperations to test_ssh_gateway_operations.py for size compliance (GRACE-lite 1000-line limit).
#   PREVIOUS_CHANGE: v1.0.3 - Migrate _bg_tasks access from list(set)[0] to dict[ip] keyed access for fix-disconnect-bg-task-leak; bg-task regression tests moved to test_ssh_gateway_bg_tasks.py.
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.domain import Engine
from yascheduler.domain.model import ConnectedMachine, MachineState, ProcessResult
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.platform.protocol import ProcessInfo
from yascheduler.infra.ssh.repository import SSHMachineRepository, _MachineState

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
    from unittest.mock import MagicMock

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
    from unittest.mock import MagicMock

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
    async def test_connect_stores_machine(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """connect() stores a _MachineState in _machines."""
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
            machine = await repository.connect(
                ip="10.0.0.1",
                username="root",
                client_keys=[],
            )

        assert "10.0.0.1" in repository
        assert repository._machines["10.0.0.1"].machine is machine
        assert repository._machines["10.0.0.1"].machine.state == MachineState.FREE

    @pytest.mark.asyncio
    async def test_connect_returns_connected_machine(
        self,
        repository: SSHMachineRepository,
        mock_conn: MagicMock,
        mock_adapter: MagicMock,
    ) -> None:
        """connect() returns a ConnectedMachine with correct IP and platform."""
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
            machine = await repository.connect(
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
    async def test_disconnect_removes_machine(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect() removes the machine from the registry."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        await repository.disconnect("10.0.0.1")
        assert "10.0.0.1" not in repository

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect() calls conn.close() and conn.wait_closed()."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        await repository.disconnect("10.0.0.1")
        state.conn.close.assert_called_once()  # type: ignore[attr-defined]
        state.conn.wait_closed.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_disconnect_all_removes_all(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect_all() clears all machines."""
        s1 = _make_state(ip="10.0.0.1")
        s2 = _make_state(ip="10.0.0.2")
        repository._machines["10.0.0.1"] = s1
        repository._machines["10.0.0.2"] = s2
        await repository.disconnect_all()
        assert len(repository) == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ip_does_nothing(
        self, repository: SSHMachineRepository
    ) -> None:
        """disconnect() with no state does not raise."""
        await repository.disconnect("10.0.0.99")  # should not raise


# =============================================================================
# List Free
# =============================================================================


class TestListFree:
    """list_free filtering by state and platform."""

    def test_list_free_returns_free_machines(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free returns only FREE machines."""
        s_free = _make_state(ip="10.0.0.1", state=MachineState.FREE)
        s_busy = _make_state(ip="10.0.0.2", state=MachineState.BUSY)
        repository._machines["10.0.0.1"] = s_free
        repository._machines["10.0.0.2"] = s_busy

        result = repository.list_free(platforms=None)
        assert len(result) == 1
        assert result[0].ip == "10.0.0.1"

    def test_list_free_filters_by_platform(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free filters machines by platform."""
        s_linux = _make_state(ip="10.0.0.1", platform="linux", state=MachineState.FREE)
        s_win = _make_state(ip="10.0.0.2", platform="windows", state=MachineState.FREE)
        repository._machines["10.0.0.1"] = s_linux
        repository._machines["10.0.0.2"] = s_win

        result = repository.list_free(platforms=["linux"])
        assert len(result) == 1
        assert result[0].ip == "10.0.0.1"

    def test_list_free_empty_when_no_match(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free returns empty list when no machines match."""
        s_linux = _make_state(ip="10.0.0.1", platform="linux", state=MachineState.FREE)
        repository._machines["10.0.0.1"] = s_linux

        result = repository.list_free(platforms=["windows"])
        assert len(result) == 0

    def test_list_free_skips_busy_machine_matching_platform(
        self, repository: SSHMachineRepository
    ) -> None:
        """list_free excludes BUSY machines even when platform matches."""
        s = _make_state(ip="10.0.0.1", platform="linux", state=MachineState.BUSY)
        repository._machines["10.0.0.1"] = s
        result = repository.list_free(platforms=["linux"])
        assert len(result) == 0

    def test_list_free_returns_oldest_first(
        self, repository: SSHMachineRepository
    ) -> None:
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
        repository._machines["10.0.0.1"] = s1
        repository._machines["10.0.0.2"] = s2

        result = repository.list_free(platforms=None)
        assert result[0].ip == "10.0.0.1"  # older free_since first


# =============================================================================
# Command Execution
# =============================================================================


class TestCommandExecution:
    """run, run_full, run_bg."""

    @pytest.mark.asyncio
    async def test_run_returns_process_result(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run() returns a ProcessResult from the adapter output."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        result = await operations.run(state.machine, "echo hello")

        assert isinstance(result, ProcessResult)
        assert result.exit_code == 0
        assert result.stdout == "stdout"
        assert result.stderr == ""

    @pytest.mark.asyncio
    async def test_run_delegates_to_run_full(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run() internally calls run_full()."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        with patch.object(operations, "run_full", AsyncMock()) as mock_run_full:
            mock_run_full.return_value = MagicMock(
                returncode=0, stdout="out", stderr=""
            )
            result = await operations.run(state.machine, "echo hello")
            mock_run_full.assert_awaited_once_with(state.machine, "echo hello")
            assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_run_full_returns_ssh_completed_process(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run_full() returns the raw adapter.run result."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        proc = await operations.run_full(state.machine, "echo hello")
        assert proc.returncode == 0
        assert proc.stdout == "stdout"

    @pytest.mark.asyncio
    async def test_run_bg_starts_background_process(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run_bg() delegates to adapter.run_bg (returns None per port contract)."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        await operations.run_bg(state.machine, "long_running", cwd="/tmp")

    @pytest.mark.asyncio
    async def test_run_full_raises_assertion_error_for_unknown_ip(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run_full() raises AssertionError when machine is not registered."""
        machine = ConnectedMachine(ip="10.0.0.99", platform="linux", ncpus=4)
        with pytest.raises(AssertionError):
            await operations.run_full(machine, "echo hello")


# =============================================================================
# File Transfer
# =============================================================================


class TestFileTransfer:
    """upload, download, get_sftp context manager."""

    @pytest.mark.asyncio
    async def test_upload_uses_sftp(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """upload() pushes file via SFTP put."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        local = Path("/tmp/local.txt")
        remote = "/remote/path/file.txt"

        await operations.upload(state.machine, local, remote)

        # Enter the sftp context to access the same singleton sftp mock
        async with state.conn.start_sftp_client() as sf:
            sf.put.assert_awaited_once_with(str(local), remote)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_download_uses_sftp(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """download equivalent via get_sftp pulls file via SFTP get."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        local = Path("/tmp/local.txt")
        remote = "/remote/path/file.txt"

        async with operations.get_sftp("10.0.0.1") as sftp:
            await sftp.get(remote, str(local))

        async with state.conn.start_sftp_client() as sf:
            sf.get.assert_awaited_once_with(remote, str(local))  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_get_sftp_context_manager(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """get_sftp yields an SFTP client via async context manager."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state

        async with operations.get_sftp("10.0.0.1") as sftp:
            assert sftp is not None
            # The sftp client should be our mock
            assert hasattr(sftp, "put")
            assert hasattr(sftp, "get")


# =============================================================================
# Machine State
# =============================================================================


class TestMachineState:
    """update_machine, contains, len, keys, items, register_machine."""

    def test_update_machine_replaces_state(
        self, repository: SSHMachineRepository
    ) -> None:
        """update_machine() replaces the ConnectedMachine in the state."""
        state = _make_state(ip="10.0.0.1", state=MachineState.FREE)
        repository._machines["10.0.0.1"] = state

        updated = state.machine.occupy()
        repository.update_machine(updated)

        assert repository._machines["10.0.0.1"].machine.state == MachineState.BUSY

    def test_update_machine_unknown_ip_does_nothing(
        self, repository: SSHMachineRepository
    ) -> None:
        """update_machine() with unknown IP silently does nothing."""
        machine = ConnectedMachine(ip="10.0.0.99", platform="linux", ncpus=4)
        repository.update_machine(machine)  # should not raise

    def test_contains(self, repository: SSHMachineRepository) -> None:
        """__contains__ checks by IP."""
        state = _make_state(ip="10.0.0.1")
        repository._machines["10.0.0.1"] = state
        assert "10.0.0.1" in repository
        assert "10.0.0.2" not in repository

    def test_len(self, repository: SSHMachineRepository) -> None:
        """__len__ returns machine count."""
        repository._machines["10.0.0.1"] = _make_state(ip="10.0.0.1")
        repository._machines["10.0.0.2"] = _make_state(ip="10.0.0.2")
        assert len(repository) == 2

    def test_keys(self, repository: SSHMachineRepository) -> None:
        """keys() returns all IPs."""
        repository._machines["10.0.0.1"] = _make_state(ip="10.0.0.1")
        repository._machines["10.0.0.2"] = _make_state(ip="10.0.0.2")
        assert set(repository.keys()) == {"10.0.0.1", "10.0.0.2"}

    def test_items(self, repository: SSHMachineRepository) -> None:
        """items() returns (ip, state) pairs."""
        state = _make_state(ip="10.0.0.1")
        repository._machines["10.0.0.1"] = state
        items = dict(repository.items())
        assert items["10.0.0.1"] is state

    def test_register_machine(self, repository: SSHMachineRepository) -> None:
        """register_machine stores a _MachineState by IP."""
        state = _make_state(ip="10.0.0.1")
        repository.register_machine("10.0.0.1", state)
        assert "10.0.0.1" in repository
        assert repository._machines["10.0.0.1"] is state

    def test_contains_method(self, repository: SSHMachineRepository) -> None:
        """contains() checks by IP (explicit method)."""
        state = _make_state(ip="10.0.0.1")
        repository._machines["10.0.0.1"] = state
        assert repository.contains("10.0.0.1") is True
        assert repository.contains("10.0.0.2") is False


# =============================================================================
# Property Helpers
# =============================================================================


class TestPropertyHelpers:
    """get_adapter, get_platforms, get_hostname, get_path, get_quote."""

    def test_get_adapter(self, repository: SSHMachineRepository) -> None:
        """get_adapter returns the RemoteMachineAdapter."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_adapter("10.0.0.1") is state.adapter

    def test_get_platforms(self, repository: SSHMachineRepository) -> None:
        """get_platforms returns the platform list."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_platforms("10.0.0.1") == ["linux", "debian-like"]

    def test_get_hostname(self, repository: SSHMachineRepository) -> None:
        """get_hostname returns the host from conn_opts."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_hostname("10.0.0.1") == "10.0.0.1"

    def test_get_path(self, repository: SSHMachineRepository) -> None:
        """get_path returns the adapter's path type."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_path("10.0.0.1") is PurePosixPath

    def test_get_quote(self, repository: SSHMachineRepository) -> None:
        """get_quote returns the adapter's quote callable."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert callable(repository.get_quote("10.0.0.1"))
        assert repository.get_quote("10.0.0.1")("test") == "test"

    def test_get_data_dir(self, repository: SSHMachineRepository) -> None:
        """get_data_dir returns the data directory."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_data_dir("10.0.0.1") == PurePosixPath("./data")

    def test_get_engines_dir(self, repository: SSHMachineRepository) -> None:
        """get_engines_dir returns the engines directory."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_engines_dir("10.0.0.1") == PurePosixPath("./data/engines")

    def test_get_tasks_dir(self, repository: SSHMachineRepository) -> None:
        """get_tasks_dir returns the tasks directory."""
        state = _make_state()
        repository._machines["10.0.0.1"] = state
        assert repository.get_tasks_dir("10.0.0.1") == PurePosixPath("./data/tasks")

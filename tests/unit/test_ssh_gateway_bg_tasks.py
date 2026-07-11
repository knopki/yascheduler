# FILE: tests/unit/test_ssh_gateway_bg_tasks.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineRepository background-task (monitor mechanism) keying and disconnect scoping.
#   SCOPE: _bg_tasks dict keying by IP, disconnect scope isolation, re-registration replacement.
#   DEPENDS: M-SSH-REPOSITORY, M-DOMAIN-MODEL
#   LINKS: M-SSH-REPOSITORY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_mock_adapter - Build a mock RemoteMachineAdapter
#   _make_mock_connection - Build a mock (conn, conn_opts) tuple
#   _make_state - Build a fully-mocked SSHMachineSession (bypasses connect)
#   TestBgTaskScoping - disconnect scope isolation and re-registration regression tests
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - session-based-machine-handle section 7.4: _machines → _sessions, _MachineState → SSHMachineSession, _monitors dict → per-session _monitor_task, start_occupancy_check(ip,…) → start_occupancy_check(session,…), disconnect pops _sessions before _close (pop-before-await). dataclasses.replace → session.release().
#   PREVIOUS_CHANGE: v1.0.0 - Extract bg-task regression tests from test_ssh_gateway.py for fix-disconnect-bg-task-leak: disconnect scope isolation across machines, prior-monitor replacement on re-register, unknown-IP disconnect no-op.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import Engine
from yascheduler.domain.model import ConnectedMachine, MachineState, NodeId
from yascheduler.infra.ssh.operations import OccupancyChecker
from yascheduler.infra.ssh.repository import SSHMachineRepository
from yascheduler.infra.ssh.session import SSHMachineSession

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _make_mock_adapter(platform: str = "linux", ncpus: int = 4) -> MagicMock:
    adapter = MagicMock()
    adapter.platform = platform
    adapter.path = PurePosixPath
    adapter.quote = lambda s: s
    return adapter


def _make_mock_connection(ip: str = "10.0.0.1") -> tuple[MagicMock, MagicMock]:
    conn = MagicMock(spec=SSHClientConnection)
    conn._transport = MagicMock()
    conn._transport.is_closing.return_value = False
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()

    sftp_client = AsyncMock()
    sftp_client.put = AsyncMock()
    sftp_client.get = AsyncMock()

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
        yield sftp_client

    conn.start_sftp_client = _sftp_ctx

    conn_opts = MagicMock(spec=SSHClientConnectionOptions)
    conn_opts.host = ip
    conn_opts.port = 22
    conn_opts.username = "root"
    return conn, conn_opts


def _make_state(
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


@pytest.fixture
def occupancy_checker() -> OccupancyChecker:
    return OccupancyChecker(log=logging.getLogger(__name__))


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


class TestBgTaskScoping:
    """Regression tests for fix-disconnect-bg-task-leak.

    Pins the IP-keyed _monitors data structure and the rule that
    disconnect(ip) cancels only that IP's monitor.
    """

    @pytest.mark.asyncio
    async def test_disconnect_does_not_cancel_other_machines_monitors(
        self,
        repository: SSHMachineRepository,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """Regression: disconnect(B) cancels only B's monitor; A and C untouched.

        Pins the fix for the bug where disconnect iterated the entire
        _monitors set and cancelled every machine's monitor.
        """
        ip_a, ip_b, ip_c = "[IP]", "[IP]", "[IP]"
        sessions = {}
        for idx, ip in enumerate((ip_a, ip_b, ip_c), 1):
            session = _make_state(hostname=ip, node_id=idx, state=MachineState.FREE)
            repository._sessions[NodeId(idx)] = session
            sessions[ip] = session
        session_a, session_b, session_c = sessions[ip_a], sessions[ip_b], sessions[ip_c]
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        mock_pengine.sleep_interval = 0.01

        async def _always_busy(*args: object, **kwargs: object) -> bool:
            return True

        # NOTE: real asyncio.sleep (not AsyncMock) — required so task.cancel()
        # during disconnect raises CancelledError at a clean await point.
        with patch.object(occupancy_checker, "occupancy_check", _always_busy):
            for session in (session_a, session_b, session_c):
                occupancy_checker.start_occupancy_check(session, mock_pengine)
            # Let each monitor enter its loop
            await asyncio.sleep(0.05)

            task_a = session_a._monitor_task  # noqa: SLF001
            task_c = session_c._monitor_task  # noqa: SLF001
            assert task_a is not None
            assert task_c is not None

            await repository.disconnect(NodeId(2))

            # B is gone from the sessions registry
            assert NodeId(2) not in repository._sessions
            # A and C monitors are still alive and registered
            assert not task_a.cancelled(), "A monitor must survive disconnect(B)"
            assert not task_c.cancelled(), "C monitor must survive disconnect(B)"
            assert session_a._monitor_task is task_a  # noqa: SLF001
            assert session_c._monitor_task is task_c  # noqa: SLF001
            assert NodeId(1) in repository._sessions
            assert NodeId(3) in repository._sessions

            # cleanup: cancel surviving monitors
            await repository.disconnect(NodeId(1))
            await repository.disconnect(NodeId(3))

    @pytest.mark.asyncio
    async def test_start_occupancy_check_replaces_prior_monitor(
        self,
        repository: SSHMachineRepository,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """Re-registering occupancy for an IP cancels the prior monitor.

        Pins the spec scenario: only the second task remains under
        _monitors[ip]; the first is cancelled.
        """
        ip = "[IP]"
        session = _make_state(hostname=ip, node_id=1, state=MachineState.FREE)
        repository._sessions[NodeId(1)] = session
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        mock_pengine.sleep_interval = 0.01

        async def _always_busy(*args: object, **kwargs: object) -> bool:
            return True

        with patch.object(occupancy_checker, "occupancy_check", _always_busy):
            occupancy_checker.start_occupancy_check(session, mock_pengine)
            first = session._monitor_task  # noqa: SLF001
            assert first is not None
            await asyncio.sleep(0.02)
            assert not first.done()

            # Reset machine to FREE so the second start_occupancy_check can occupy it
            session.release()
            occupancy_checker.start_occupancy_check(session, mock_pengine)
            second = session._monitor_task  # noqa: SLF001
            assert second is not None
            # Let the prior task finish cancelling. _checker swallows
            # CancelledError, so the prior task finishes with result=None
            # rather than raising — observable contract is done()+replaced.
            with contextlib.suppress(asyncio.CancelledError):
                await first

            # First monitor done and replaced; second installed and distinct
            assert second is not first
            assert first.done(), "prior monitor must be stopped on re-register"
            assert session._monitor_task is second  # noqa: SLF001
            assert not second.done()

            await repository.disconnect(NodeId(1))

        # After disconnect, the session's monitor task is cleared
        assert NodeId(1) not in repository._sessions
        assert session._monitor_task is None  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ip_leaves_other_monitors_alive(
        self,
        repository: SSHMachineRepository,
        occupancy_checker: OccupancyChecker,
        mock_pengine: MagicMock,
    ) -> None:
        """disconnect on an unknown IP is a no-op for every other monitor."""
        ip_a, ip_b = "[IP]", "[IP]"
        sessions = {}
        for idx, ip in enumerate((ip_a, ip_b), 1):
            session = _make_state(hostname=ip, node_id=idx, state=MachineState.FREE)
            repository._sessions[NodeId(idx)] = session
            sessions[ip] = session
        session_a, session_b = sessions[ip_a], sessions[ip_b]
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        mock_pengine.sleep_interval = 0.01

        async def _always_busy(*args: object, **kwargs: object) -> bool:
            return True

        with patch.object(occupancy_checker, "occupancy_check", _always_busy):
            occupancy_checker.start_occupancy_check(session_a, mock_pengine)
            occupancy_checker.start_occupancy_check(session_b, mock_pengine)
            await asyncio.sleep(0.05)

            task_a = session_a._monitor_task  # noqa: SLF001
            task_b = session_b._monitor_task  # noqa: SLF001
            assert task_a is not None
            assert task_b is not None

            await repository.disconnect(NodeId(99))

            assert not task_a.cancelled()
            assert not task_b.cancelled()
            assert session_a._monitor_task is task_a  # noqa: SLF001
            assert session_b._monitor_task is task_b  # noqa: SLF001
            assert NodeId(1) in repository._sessions
            assert NodeId(2) in repository._sessions

            await repository.disconnect(NodeId(1))
            await repository.disconnect(NodeId(2))

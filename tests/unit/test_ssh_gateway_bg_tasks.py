# FILE: tests/unit/test_ssh_gateway_bg_tasks.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineGateway background-task keying and disconnect scoping.
#   SCOPE: _bg_tasks dict keying by IP, disconnect scope isolation, re-registration replacement.
#   DEPENDS: M-SSH-GATEWAY, M-DOMAIN-MODEL
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_mock_adapter - Build a mock RemoteMachineAdapter
#   _make_mock_connection - Build a mock (conn, conn_opts) tuple
#   _make_state - Build a fully-mocked _MachineState (bypasses connect)
#   TestBgTaskScoping - disconnect scope isolation and re-registration regression tests
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Extract bg-task regression tests from test_ssh_gateway.py for fix-disconnect-bg-task-leak: disconnect scope isolation across machines, prior-monitor replacement on re-register, unknown-IP disconnect no-op.
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import contextlib
import time
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asyncssh.connection import SSHClientConnection, SSHClientConnectionOptions

from yascheduler.domain import Engine
from yascheduler.domain.model import ConnectedMachine, MachineState
from yascheduler.infra.ssh.gateway import SSHMachineGateway, _MachineState

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

    Pins the IP-keyed _bg_tasks data structure and the rule that
    disconnect(ip) cancels only that IP's monitor.
    """

    @pytest.mark.asyncio
    async def test_disconnect_does_not_cancel_other_machines_monitors(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """Regression: disconnect(B) cancels only B's monitor; A and C untouched.

        Pins the fix for the bug where disconnect iterated the entire
        _bg_tasks set and cancelled every machine's monitor.
        """
        ip_a, ip_b, ip_c = "10.0.0.1", "10.0.0.2", "10.0.0.3"
        for ip in (ip_a, ip_b, ip_c):
            gateway._machines[ip] = _make_state(ip=ip, state=MachineState.BUSY)
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        mock_pengine.sleep_interval = 0.01

        async def _always_busy(*args: object, **kwargs: object) -> bool:
            return True

        # NOTE: real asyncio.sleep (not AsyncMock) — required so task.cancel()
        # during disconnect raises CancelledError at a clean await point.
        with patch.object(gateway, "occupancy_check", _always_busy):
            for ip in (ip_a, ip_b, ip_c):
                gateway.start_occupancy_check(ip, mock_pengine)
            # Let each monitor enter its loop
            await asyncio.sleep(0.05)

            task_a = gateway._bg_tasks[ip_a]
            task_c = gateway._bg_tasks[ip_c]

            await gateway.disconnect(ip_b)

            # B is gone from both registries
            assert ip_b not in gateway._machines
            assert ip_b not in gateway._bg_tasks
            # A and C monitors are still alive and registered
            assert not task_a.cancelled(), "A monitor must survive disconnect(B)"
            assert not task_c.cancelled(), "C monitor must survive disconnect(B)"
            assert gateway._bg_tasks[ip_a] is task_a
            assert gateway._bg_tasks[ip_c] is task_c
            assert ip_a in gateway._machines
            assert ip_c in gateway._machines

            # cleanup: cancel surviving monitors
            await gateway.disconnect(ip_a)
            await gateway.disconnect(ip_c)

    @pytest.mark.asyncio
    async def test_start_occupancy_check_replaces_prior_monitor(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """Re-registering occupancy for an IP cancels the prior monitor.

        Pins the spec scenario: only the second task remains under
        _bg_tasks[ip]; the first is cancelled.
        """
        ip = "10.0.0.1"
        gateway._machines[ip] = _make_state(ip=ip, state=MachineState.BUSY)
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        mock_pengine.sleep_interval = 0.01

        async def _always_busy(*args: object, **kwargs: object) -> bool:
            return True

        with patch.object(gateway, "occupancy_check", _always_busy):
            gateway.start_occupancy_check(ip, mock_pengine)
            first = gateway._bg_tasks[ip]
            await asyncio.sleep(0.02)
            assert not first.done()

            gateway.start_occupancy_check(ip, mock_pengine)
            second = gateway._bg_tasks[ip]
            # Let the prior task finish cancelling. _checker swallows
            # CancelledError, so the prior task finishes with result=None
            # rather than raising — observable contract is done()+replaced.
            with contextlib.suppress(asyncio.CancelledError):
                await first

            # First monitor done and replaced; second installed and distinct
            assert second is not first
            assert first.done(), "prior monitor must be stopped on re-register"
            assert gateway._bg_tasks[ip] is second
            assert not second.done()

            await gateway.disconnect(ip)

        assert ip not in gateway._bg_tasks

    @pytest.mark.asyncio
    async def test_disconnect_unknown_ip_leaves_other_monitors_alive(
        self, gateway: SSHMachineGateway, mock_pengine: MagicMock
    ) -> None:
        """disconnect on an unknown IP is a no-op for every other monitor."""
        ip_a, ip_b = "10.0.0.1", "10.0.0.2"
        for ip in (ip_a, ip_b):
            gateway._machines[ip] = _make_state(ip=ip, state=MachineState.BUSY)
        mock_pengine.check_pname = None
        mock_pengine.check_cmd = None
        mock_pengine.sleep_interval = 0.01

        async def _always_busy(*args: object, **kwargs: object) -> bool:
            return True

        with patch.object(gateway, "occupancy_check", _always_busy):
            gateway.start_occupancy_check(ip_a, mock_pengine)
            gateway.start_occupancy_check(ip_b, mock_pengine)
            await asyncio.sleep(0.05)

            task_a = gateway._bg_tasks[ip_a]
            task_b = gateway._bg_tasks[ip_b]

            await gateway.disconnect("10.0.0.99")

            assert not task_a.cancelled()
            assert not task_b.cancelled()
            assert gateway._bg_tasks[ip_a] is task_a
            assert gateway._bg_tasks[ip_b] is task_b
            assert ip_a in gateway._machines
            assert ip_b in gateway._machines

            await gateway.disconnect(ip_a)
            await gateway.disconnect(ip_b)

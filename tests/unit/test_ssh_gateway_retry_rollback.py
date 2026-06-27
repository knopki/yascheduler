# FILE: tests/unit/test_ssh_gateway_retry_rollback.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for non-idempotent retry removal (run_bg/upload/download single-attempt) and start_task_on_machine BUSY rollback.
#   SCOPE: run_bg/upload/download no longer retry on transient SSH/SFTP errors; start_task_on_machine rolls back gateway BUSY on upload/spawn/Cancelled/unexpected-state/concurrent-disconnect failures.
#   DEPENDS: M-SSH-GATEWAY, M-DOMAIN-MODEL
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestNonIdempotentRetry - run_bg / upload / download SHALL NOT retry on transient errors
#   TestStartTaskRollback - start_task_on_machine rolls back gateway BUSY on deploy/spawn failure
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial tests for fix-nonidempotent-ssh-retries: run_bg/upload/download single-attempt propagation; start_task_on_machine BUSY rollback (upload failure, spawn failure, CancelledError, unexpected non-BUSY state, concurrent disconnect).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_ssh_gateway import _make_state
from yascheduler.domain import Engine
from yascheduler.domain.model import (
    MachineState,
    Task,
    TaskContext,
)
from yascheduler.infra.ssh.gateway import SSHMachineGateway, _MachineState
from yascheduler.infra.ssh.platform.protocol import (
    ChannelOpenError,
    SFTPConnectionLost,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
def gateway() -> SSHMachineGateway:
    return SSHMachineGateway()


def _make_engine() -> Engine:
    """Minimal Engine for start_task_on_machine tests."""
    return Engine(name="test_engine", spawn="{engine_path} {task_path}")


def _make_task(remote_folder: str = "/remote/tasks/1") -> Task:
    """Minimal Task with a remote_folder set (required by start_task_on_machine)."""
    return Task(
        task_id=1,
        label="test-task",
        context=TaskContext(engine="test_engine", remote_folder=remote_folder),
    )


def _wire_realpath(state: _MachineState) -> None:
    """Configure the DEPLOY SFTP client's realpath before start_task_on_machine."""
    sftp = AsyncMock()
    sftp.realpath = AsyncMock(return_value="/root")

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
        yield sftp

    state.conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]


# =============================================================================
# Non-idempotent retry behaviour (run_bg / upload / download are single-attempt)
# =============================================================================


class TestNonIdempotentRetry:
    """run_bg / upload / download SHALL NOT retry on transient errors."""

    @pytest.mark.asyncio
    async def test_run_bg_no_longer_retries_on_ssh_error(
        self, gateway: SSHMachineGateway
    ) -> None:
        """run_bg propagates ChannelOpenError immediately, single attempt (no retry)."""
        state = _make_state()
        adapter = cast("MagicMock", state.adapter)
        adapter.run_bg = AsyncMock(side_effect=ChannelOpenError(11, "open failed"))
        gateway._machines["10.0.0.1"] = state

        with pytest.raises(ChannelOpenError):
            await gateway.run_bg(state.machine, "spawn-cmd", cwd="/tmp")

        adapter.run_bg.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_upload_no_longer_retries_on_sftp_error(
        self, gateway: SSHMachineGateway
    ) -> None:
        """upload propagates SFTPConnectionLost immediately, single put attempt."""
        state = _make_state()
        sftp = AsyncMock()
        sftp.put = AsyncMock(side_effect=SFTPConnectionLost("connection lost"))

        @asynccontextmanager
        async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield sftp

        state.conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]
        gateway._machines["10.0.0.1"] = state

        with pytest.raises(SFTPConnectionLost):
            await gateway.upload(state.machine, Path("/tmp/local"), "/remote/file")

        sftp.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_download_no_longer_retries_on_sftp_error(
        self, gateway: SSHMachineGateway
    ) -> None:
        """download propagates SFTPConnectionLost immediately, single get attempt."""
        state = _make_state()
        sftp = AsyncMock()
        sftp.get = AsyncMock(side_effect=SFTPConnectionLost("connection lost"))

        @asynccontextmanager
        async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield sftp

        state.conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]
        gateway._machines["10.0.0.1"] = state

        with pytest.raises(SFTPConnectionLost):
            await gateway.download(state.machine, "/remote/file", Path("/tmp/local"))

        sftp.get.assert_awaited_once()


# =============================================================================
# start_task_on_machine BUSY rollback
# =============================================================================


class TestStartTaskRollback:
    """start_task_on_machine rolls back the gateway-level BUSY marking on failure."""

    @pytest.mark.asyncio
    async def test_rollback_busy_on_upload_failure(
        self, gateway: SSHMachineGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Upload failure -> machine released, info log, original error re-raised."""
        state = _make_state()
        _wire_realpath(state)
        gateway._machines["10.0.0.1"] = state
        machine = gateway._machines["10.0.0.1"].machine

        with patch.object(
            gateway,
            "_upload_task_data",
            AsyncMock(side_effect=OSError("upload boom")),
        ):
            with caplog.at_level(logging.INFO):
                with pytest.raises(OSError, match="upload boom"):
                    await gateway.start_task_on_machine(
                        machine,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert gateway._machines["10.0.0.1"].machine.state == MachineState.FREE
        assert "rolling back gateway BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_busy_on_spawn_failure(
        self, gateway: SSHMachineGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Spawn failure (ChannelOpenError) -> machine released, info log, re-raised."""
        state = _make_state()
        _wire_realpath(state)
        gateway._machines["10.0.0.1"] = state
        machine = gateway._machines["10.0.0.1"].machine

        with (
            patch.object(gateway, "_upload_task_data", AsyncMock(return_value=True)),
            patch.object(
                gateway,
                "_exec_spawn_command",
                AsyncMock(side_effect=ChannelOpenError(11, "no chan")),
            ),
        ):
            with caplog.at_level(logging.INFO):
                with pytest.raises(ChannelOpenError):
                    await gateway.start_task_on_machine(
                        machine,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert gateway._machines["10.0.0.1"].machine.state == MachineState.FREE
        assert "rolling back gateway BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_on_cancelled_error(
        self, gateway: SSHMachineGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        """CancelledError (BaseException) is caught, machine released, then re-raised."""
        state = _make_state()
        _wire_realpath(state)
        gateway._machines["10.0.0.1"] = state
        machine = gateway._machines["10.0.0.1"].machine

        with patch.object(
            gateway,
            "_upload_task_data",
            AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with caplog.at_level(logging.INFO):
                with pytest.raises(asyncio.CancelledError):
                    await gateway.start_task_on_machine(
                        machine,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert gateway._machines["10.0.0.1"].machine.state == MachineState.FREE
        assert "rolling back gateway BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_warns_on_unexpected_state(
        self, gateway: SSHMachineGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-BUSY state at rollback -> warn, still release, re-raise."""
        state = _make_state()
        _wire_realpath(state)
        gateway._machines["10.0.0.1"] = state
        machine = gateway._machines["10.0.0.1"].machine

        async def _fail_with_unexpected_state(
            ip: str, task: Task, task_dir: object, input_files: object
        ) -> bool:
            # Simulate a concurrent transition away from BUSY before rollback.
            cur = gateway._machines[ip]
            gateway._machines[ip] = replace(cur, machine=cur.machine.release())
            raise OSError("boom")

        with patch.object(
            gateway,
            "_upload_task_data",
            AsyncMock(side_effect=_fail_with_unexpected_state),
        ):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(OSError):
                    await gateway.start_task_on_machine(
                        machine,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert gateway._machines["10.0.0.1"].machine.state == MachineState.FREE
        assert "unexpected state" in caplog.text
        assert "expected BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_warns_on_concurrent_disconnect(
        self, gateway: SSHMachineGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Machine gone (concurrent disconnect) -> warn, skip release, re-raise."""
        state = _make_state()
        _wire_realpath(state)
        gateway._machines["10.0.0.1"] = state

        async def _fail_after_disconnect(
            ip: str, task: Task, task_dir: object, input_files: object
        ) -> bool:
            gateway._machines.pop(ip, None)  # simulate concurrent disconnect
            raise OSError("boom")

        machine = gateway._machines["10.0.0.1"].machine
        update_spy = patch.object(
            gateway, "update_machine", wraps=gateway.update_machine
        )

        with (
            update_spy as spy,
            patch.object(
                gateway,
                "_upload_task_data",
                AsyncMock(side_effect=_fail_after_disconnect),
            ),
        ):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(OSError):
                    await gateway.start_task_on_machine(
                        machine,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        # Rollback saw None and did not re-register via update_machine/release.
        assert gateway._machines.get("10.0.0.1") is None
        # update_machine was called exactly once (the initial occupy); no release call.
        assert spy.call_count == 1
        assert "already disconnected" in caplog.text

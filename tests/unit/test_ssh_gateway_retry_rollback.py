# FILE: tests/unit/test_ssh_gateway_retry_rollback.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for non-idempotent retry removal (run_bg/upload/download single-attempt) and start_task_on_machine BUSY rollback.
#   SCOPE: run_bg/upload/download no longer retry on transient SSH/SFTP errors; start_task_on_machine rolls back gateway BUSY on upload/spawn/Cancelled/unexpected-state/concurrent-disconnect failures.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-OPS-DEPLOY, M-DOMAIN-MODEL
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPS-DEPLOY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestNonIdempotentRetry - run_bg / upload / download SHALL NOT retry on transient errors
#   TestStartTaskRollback - start_task_on_machine rolls back gateway BUSY on deploy/spawn failure
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - session-based-machine-handle: repository._machines → repository._sessions; operations.run_bg/start_task_on_machine take session; operations.upload/get_sftp removed — use session.upload/session.open_sftp; rollback uses session.is_closed; occupy spy on session not repository. Log substring "rolling back BUSY" (no "repository").
#   PREVIOUS_CHANGE: v1.0.0 - Initial tests for fix-nonidempotent-ssh-retries: run_bg/upload/download single-attempt propagation; start_task_on_machine BUSY rollback (upload failure, spawn failure, CancelledError, unexpected non-BUSY state, concurrent disconnect).
# END_CHANGE_SUMMARY

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit.test_ssh_gateway import _make_state
from yascheduler.domain import Engine
from yascheduler.domain.model import (
    MachineState,
    NodeId,
    Task,
    TaskContext,
    TaskId,
)
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.platform.protocol import (
    ChannelOpenError,
    SFTPConnectionLost,
)
from yascheduler.infra.ssh.repository import SSHMachineRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from yascheduler.infra.ssh.session import SSHMachineSession


@pytest.fixture
def repository() -> SSHMachineRepository:
    return SSHMachineRepository()


@pytest.fixture
def operations(repository: SSHMachineRepository) -> SSHMachineOperations:
    return SSHMachineOperations(repository=repository)


def _make_engine() -> Engine:
    """Minimal Engine for start_task_on_machine tests."""
    return Engine(name="test_engine", spawn="{engine_path} {task_path}")


def _make_task(remote_folder: str = "/remote/tasks/1") -> Task:
    """Minimal Task with a remote_folder set (required by start_task_on_machine)."""
    return Task(
        task_id=TaskId(1),
        label="test-task",
        context=TaskContext(engine="test_engine", remote_folder=remote_folder),
    )


def _wire_realpath(state: SSHMachineSession) -> None:
    """Configure the DEPLOY SFTP client's realpath before start_task_on_machine."""
    sftp = AsyncMock()
    sftp.realpath = AsyncMock(return_value="/root")

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
        yield sftp

    state._conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]  # noqa: SLF001


# =============================================================================
# Non-idempotent retry behaviour (run_bg / upload / download are single-attempt)
# =============================================================================


class TestNonIdempotentRetry:
    """run_bg / upload / download SHALL NOT retry on transient errors."""

    @pytest.mark.asyncio
    async def test_run_bg_no_longer_retries_on_ssh_error(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """run_bg propagates ChannelOpenError immediately, single attempt (no retry)."""
        session = _make_state()
        adapter = cast("MagicMock", session.adapter)
        adapter.run_bg = AsyncMock(side_effect=ChannelOpenError(11, "open failed"))
        repository._sessions[NodeId(1)] = session

        with pytest.raises(ChannelOpenError):
            await operations.run_bg(session, "spawn-cmd", cwd="/tmp")

        adapter.run_bg.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_upload_no_longer_retries_on_sftp_error(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """upload propagates SFTPConnectionLost immediately, single put attempt."""
        session = _make_state()
        sftp = AsyncMock()
        sftp.put = AsyncMock(side_effect=SFTPConnectionLost("connection lost"))

        @asynccontextmanager
        async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield sftp

        session._conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]  # noqa: SLF001
        repository._sessions[NodeId(1)] = session

        with pytest.raises(SFTPConnectionLost):
            await session.upload(Path("/tmp/local"), "/remote/file")

        sftp.put.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_download_no_longer_retries_on_sftp_error(
        self, repository: SSHMachineRepository, operations: SSHMachineOperations
    ) -> None:
        """download equivalent via open_sftp propagates SFTPConnectionLost immediately, single get attempt."""
        session = _make_state()
        sftp = AsyncMock()
        sftp.get = AsyncMock(side_effect=SFTPConnectionLost("connection lost"))

        @asynccontextmanager
        async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
            yield sftp

        session._conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]  # noqa: SLF001
        repository._sessions[NodeId(1)] = session

        with pytest.raises(SFTPConnectionLost):
            async with session.open_sftp() as sftp_client:
                await sftp_client.get("/remote/file", "/tmp/local")

        sftp.get.assert_awaited_once()


# =============================================================================
# start_task_on_machine BUSY rollback
# =============================================================================


class TestStartTaskRollback:
    """start_task_on_machine rolls back the repository-level BUSY marking on failure."""

    @pytest.mark.asyncio
    async def test_rollback_busy_on_upload_failure(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Upload failure -> machine released, info log, original error re-raised."""
        session = _make_state()
        _wire_realpath(session)
        repository._sessions[NodeId(1)] = session

        with patch.object(
            operations.deploy,
            "_upload_task_data",
            AsyncMock(side_effect=OSError("upload boom")),
        ):
            with caplog.at_level(logging.INFO):
                with pytest.raises(OSError, match="upload boom"):
                    await operations.start_task_on_machine(
                        session,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert repository._sessions[NodeId(1)].machine.state == MachineState.FREE
        assert "rolling back BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_busy_on_spawn_failure(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Spawn failure (ChannelOpenError) -> machine released, info log, re-raised."""
        session = _make_state()
        _wire_realpath(session)
        repository._sessions[NodeId(1)] = session

        with (
            patch.object(
                operations.deploy, "_upload_task_data", AsyncMock(return_value=True)
            ),
            patch.object(
                operations.deploy,
                "_exec_spawn_command",
                AsyncMock(side_effect=ChannelOpenError(11, "no chan")),
            ),
        ):
            with caplog.at_level(logging.INFO):
                with pytest.raises(ChannelOpenError):
                    await operations.start_task_on_machine(
                        session,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert repository._sessions[NodeId(1)].machine.state == MachineState.FREE
        assert "rolling back BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_on_cancelled_error(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """CancelledError (BaseException) is caught, machine released, then re-raised."""
        session = _make_state()
        _wire_realpath(session)
        repository._sessions[NodeId(1)] = session

        with patch.object(
            operations.deploy,
            "_upload_task_data",
            AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with caplog.at_level(logging.INFO):
                with pytest.raises(asyncio.CancelledError):
                    await operations.start_task_on_machine(
                        session,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert repository._sessions[NodeId(1)].machine.state == MachineState.FREE
        assert "rolling back BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_warns_on_unexpected_state(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Non-BUSY state at rollback -> warn, still release, re-raise."""
        session = _make_state()
        _wire_realpath(session)
        repository._sessions[NodeId(1)] = session

        async def _fail_with_unexpected_state(
            s: object, task: Task, task_dir: object, input_files: object
        ) -> bool:
            # Simulate a concurrent transition away from BUSY before rollback.
            session.release()
            raise OSError("boom")

        with patch.object(
            operations.deploy,
            "_upload_task_data",
            AsyncMock(side_effect=_fail_with_unexpected_state),
        ):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(OSError):
                    await operations.start_task_on_machine(
                        session,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        assert repository._sessions[NodeId(1)].machine.state == MachineState.FREE
        assert "unexpected state" in caplog.text
        assert "expected BUSY" in caplog.text

    @pytest.mark.asyncio
    async def test_rollback_warns_on_concurrent_disconnect(
        self,
        repository: SSHMachineRepository,
        operations: SSHMachineOperations,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Session closed (concurrent disconnect) -> warn, skip release, re-raise."""
        session = _make_state()
        _wire_realpath(session)
        repository._sessions[NodeId(1)] = session

        async def _fail_after_disconnect(
            s: object, task: Task, task_dir: object, input_files: object
        ) -> bool:
            await session._close()  # noqa: SLF001
            raise OSError("boom")

        occupy_spy = patch.object(session, "occupy", wraps=session.occupy)

        with (
            occupy_spy as spy,
            patch.object(
                operations.deploy,
                "_upload_task_data",
                AsyncMock(side_effect=_fail_after_disconnect),
            ),
        ):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(OSError):
                    await operations.start_task_on_machine(
                        session,
                        _make_engine(),
                        _make_task(),
                        4,
                        PurePosixPath("/engines"),
                    )

        # Rollback saw is_closed and skipped release; session stays BUSY in repo.
        assert session.is_closed
        assert repository._sessions[NodeId(1)].machine.state == MachineState.BUSY
        # occupy was called exactly once (the initial occupy); no release call.
        assert spy.call_count == 1
        assert "already disconnected" in caplog.text

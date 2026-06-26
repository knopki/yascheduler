# FILE: tests/unit/test_ssh_gateway_download_outputs.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineGateway.download_outputs classification + conditional rmtree.
#   SCOPE: Success path, per-file permanent error, per-file transient error, session-level error, rmtree gating, task_id log correlation.
#   DEPENDS: M-SSH-GATEWAY
#   LINKS: M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_download_outputs_success - All files download OK; returns (meta_add, [], []); rmtree called
#   test_download_outputs_per_file_permanent_error - Per-file OSError caught; classified permanent; rmtree called
#   test_download_outputs_per_file_transient_error - Per-file SFTPFailure (SFTPRetryExc) caught; classified transient; rmtree NOT called
#   test_download_outputs_session_error - Session-level failure caught; returned in transient_errors; rmtree NOT called
#   test_download_outputs_task_id_in_signature - task_id param accepted for log correlation
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Update for 3-tuple return (meta_add, transient_errors, permanent_errors) + classification + conditional rmtree gating (fix-download-rmtree-data-loss). Replace sftp_errors assertions with split transient/permanent; add transient-error rmtree-preserved test.
#   PREVIOUS_CHANGE: v1.0.0 - Initial tests for download_outputs catch-all contract (gateway-port-cleanup).
# END_CHANGE_SUMMARY

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncssh.sftp import SFTPClient, SFTPFailure

from yascheduler.infra.ssh.gateway import SSHMachineGateway


def make_gateway_with_sftp(sftp_mock: AsyncMock) -> SSHMachineGateway:
    """Construct a gateway with mocked SFTP context manager and path type."""
    gw = SSHMachineGateway()

    @asynccontextmanager
    async def fake_sftp(_ip: str) -> AsyncGenerator[SFTPClient, None]:
        yield sftp_mock

    gw.get_sftp = fake_sftp  # type: ignore[assignment]
    gw.get_path = MagicMock(return_value=PurePosixPath)  # type: ignore[assignment]
    return gw


@pytest.mark.asyncio
async def test_download_outputs_success() -> None:
    """All files download OK, rmtree called, returns (meta_add, [], [])."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(return_value=None)
    sftp_mock.rmtree = AsyncMock(return_value=None)
    gw = make_gateway_with_sftp(sftp_mock)

    meta_add, transient_errors, permanent_errors = await gw.download_outputs(
        ip="10.0.0.1",
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=42,
    )

    assert meta_add == [
        ("remote_folder", "/remote/path"),
        ("local_folder", "/local/path"),
    ]
    assert transient_errors == []
    assert permanent_errors == []
    assert sftp_mock.get.await_count == 2
    sftp_mock.rmtree.assert_awaited_once_with(PurePosixPath("/remote/path"))


@pytest.mark.asyncio
async def test_download_outputs_per_file_permanent_error() -> None:
    """Per-file OSError (not SFTPRetryExc) -> permanent_errors; rmtree still called."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(side_effect=OSError("permission denied"))
    sftp_mock.rmtree = AsyncMock(return_value=None)
    gw = make_gateway_with_sftp(sftp_mock)

    meta_add, transient_errors, permanent_errors = await gw.download_outputs(
        ip="10.0.0.1",
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=42,
    )

    assert meta_add == [
        ("remote_folder", "/remote/path"),
        ("local_folder", "/local/path"),
    ]
    assert transient_errors == []
    assert len(permanent_errors) == 2
    for file_name, exc in permanent_errors:
        assert file_name in ("f1.out", "f2.out")
        assert isinstance(exc, OSError)
    # No transient errors -> rmtree runs (permanent-only finalises)
    sftp_mock.rmtree.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_outputs_per_file_transient_error() -> None:
    """Per-file SFTPFailure (in SFTPRetryExc) -> transient_errors; rmtree NOT called."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(side_effect=SFTPFailure("connection lost"))
    sftp_mock.rmtree = AsyncMock(return_value=None)
    gw = make_gateway_with_sftp(sftp_mock)

    meta_add, transient_errors, permanent_errors = await gw.download_outputs(
        ip="10.0.0.1",
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=42,
    )

    assert meta_add == [
        ("remote_folder", "/remote/path"),
        ("local_folder", "/local/path"),
    ]
    assert permanent_errors == []
    assert len(transient_errors) == 2
    for file_name, exc in transient_errors:
        assert file_name in ("f1.out", "f2.out")
        assert isinstance(exc, SFTPFailure)
    # Transient errors -> rmtree NOT called (remote dir preserved for retry)
    sftp_mock.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_session_error() -> None:
    """get_sftp raises (session-level failure); caught in transient_errors; rmtree NOT called."""
    gw = SSHMachineGateway()

    @asynccontextmanager
    async def bad_sftp(_ip: str) -> AsyncGenerator[Any, None]:
        raise OSError("no connection")
        yield  # type: ignore[unreachable]

    gw.get_sftp = bad_sftp  # type: ignore[assignment]
    gw.get_path = MagicMock(return_value=PurePosixPath)  # type: ignore[assignment]

    meta_add, transient_errors, permanent_errors = await gw.download_outputs(
        ip="10.0.0.1",
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=42,
    )

    assert meta_add == [
        ("remote_folder", "/remote/path"),
        ("local_folder", "/local/path"),
    ]
    assert permanent_errors == []
    assert len(transient_errors) == 1
    remote_dir, exc = transient_errors[0]
    assert remote_dir == "/remote/path"
    assert isinstance(exc, OSError)


@pytest.mark.asyncio
async def test_download_outputs_task_id_in_signature() -> None:
    """Verify task_id param is accepted without error for log correlation."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(return_value=None)
    sftp_mock.rmtree = AsyncMock(return_value=None)
    gw = make_gateway_with_sftp(sftp_mock)

    # With task_id
    meta_add, transient_errors, permanent_errors = await gw.download_outputs(
        ip="10.0.0.1",
        remote_dir="/r",
        local_dir=Path("/l"),
        files=["f.out"],
        task_id=99,
    )
    assert len(transient_errors) == 0
    assert len(permanent_errors) == 0
    assert len(meta_add) == 2

    # Without task_id (None default)
    meta_add2, transient_errors2, permanent_errors2 = await gw.download_outputs(
        ip="10.0.0.1",
        remote_dir="/r",
        local_dir=Path("/l"),
        files=["f.out"],
    )
    assert len(transient_errors2) == 0
    assert len(permanent_errors2) == 0

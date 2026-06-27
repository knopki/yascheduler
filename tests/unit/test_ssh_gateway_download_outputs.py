# FILE: tests/unit/test_ssh_gateway_download_outputs.py
# VERSION: 1.2.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineOperations.download_outputs classification + conditional rmtree.
#   SCOPE: Success path, per-file permanent error, per-file transient error, session-level error, rmtree gating, per-file SFTP isolation, task_id log correlation.
#   DEPENDS: M-SSH-OPS-DOWNLOAD
#   LINKS: M-SSH-OPS-DOWNLOAD
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_download_outputs_success - All files download OK; returns (meta_add, [], []); rmtree called
#   test_download_outputs_per_file_permanent_error - Per-file OSError caught; classified permanent; rmtree NOT called (conservative gate)
#   test_download_outputs_per_file_transient_error - Per-file SFTPFailure (SFTPRetryExc) caught; classified transient; rmtree NOT called
#   test_download_outputs_session_error - Session-level failure caught; returned in transient_errors; rmtree NOT called
#   test_download_outputs_task_id_in_signature - task_id param accepted for log correlation
#   test_download_outputs_rmtree_only_on_full_success - rmtree called only when both error lists empty
#   test_download_outputs_per_file_sftp_isolation - dropped client on file 2 does not fail-fast file 3
#   test_download_outputs_session_level_failure_transient - get_sftp-open failure -> session-level transient
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.2.0 - Update for fix-nonidempotent-ssh-retries: download_outputs now opens a FRESH get_sftp client per file and rmtree is gated on `not transient_errors AND not permanent_errors` (conservative — permanent errors now preserve the remote dir). Add an autouse fixture that neutralizes my_backoff_sftp (per-file retry) to a passthrough so transient SFTP exceptions (SFTPFailure/SFTPConnectionLost) reach the classifier immediately instead of triggering the real 60s fibonacci backoff — this was the unit-test timeout root cause. Add per-file SFTP isolation test (fresh client per file; file-2 failure does not fail-fast file 3) and session-level-failure test (get_sftp-open raises -> session-level transient). Flip the permanent-error rmtree assertion to assert_not_awaited (gate now includes permanent_errors).
#   PREVIOUS_CHANGE: v1.1.0 - Update for 3-tuple return (meta_add, transient_errors, permanent_errors) + classification + conditional rmtree gating (fix-download-rmtree-data-loss). Replace sftp_errors assertions with split transient/permanent; add transient-error rmtree-preserved test.
# END_CHANGE_SUMMARY

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from asyncssh.sftp import SFTPClient, SFTPFailure

from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.operations import download as download_module
from yascheduler.infra.ssh.platform.protocol import SFTPConnectionLost
from yascheduler.infra.ssh.repository import SSHMachineRepository


@pytest.fixture(autouse=True)
def _no_sftp_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize my_backoff_sftp so per-file retry is a passthrough in unit tests.

    file_get_retry = my_backoff_sftp() wraps sftp.get in a real 60s fibonacci
    backoff on SFTPRetryExc. Without this patch, a test that makes sftp.get raise
    a retryable SFTP exception (SFTPFailure / SFTPConnectionLost) blocks for 60s
    per file before the exception reaches the classifier — the unit-test timeout
    root cause. Unit tests verify classification/isolation logic, not real
    backoff timing, so the retry is replaced with identity (raise immediately).
    """
    monkeypatch.setattr(download_module, "my_backoff_sftp", lambda: lambda fn: fn)


def make_gateway_with_sftp(
    sftp_mock: AsyncMock,
) -> tuple[SSHMachineRepository, SSHMachineOperations]:
    """Construct a repository + operations with mocked SFTP context manager and path type."""
    repository = SSHMachineRepository()
    operations = SSHMachineOperations(repository=repository)

    @asynccontextmanager
    async def fake_sftp(_ip: str) -> AsyncGenerator[SFTPClient, None]:
        yield sftp_mock

    operations.get_sftp = fake_sftp  # type: ignore[assignment]
    repository.get_path = MagicMock(return_value=PurePosixPath)  # type: ignore[assignment]
    return repository, operations


@pytest.mark.asyncio
async def test_download_outputs_success() -> None:
    """All files download OK, rmtree called, returns (meta_add, [], [])."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(return_value=None)
    sftp_mock.rmtree = AsyncMock(return_value=None)
    _repository, operations = make_gateway_with_sftp(sftp_mock)

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
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
    """Per-file OSError (not SFTPRetryExc) -> permanent_errors; rmtree NOT called (conservative gate)."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(side_effect=OSError("permission denied"))
    sftp_mock.rmtree = AsyncMock(return_value=None)
    _repository, operations = make_gateway_with_sftp(sftp_mock)

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
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
    # Permanent errors now also preserve the remote dir (gate: no error at all).
    sftp_mock.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_per_file_transient_error() -> None:
    """Per-file SFTPFailure (in SFTPRetryExc) -> transient_errors; rmtree NOT called."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(side_effect=SFTPFailure("connection lost"))
    sftp_mock.rmtree = AsyncMock(return_value=None)
    _repository, operations = make_gateway_with_sftp(sftp_mock)

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
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
    repository = SSHMachineRepository()
    operations = SSHMachineOperations(repository=repository)

    @asynccontextmanager
    async def bad_sftp(_ip: str) -> AsyncGenerator[Any, None]:
        raise OSError("no connection")
        yield  # type: ignore[unreachable]

    operations.get_sftp = bad_sftp  # type: ignore[assignment]
    repository.get_path = MagicMock(return_value=PurePosixPath)  # type: ignore[assignment]

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
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
    _repository, operations = make_gateway_with_sftp(sftp_mock)

    # With task_id
    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
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
    meta_add2, transient_errors2, permanent_errors2 = await operations.download_outputs(
        ip="10.0.0.1",
        remote_dir="/r",
        local_dir=Path("/l"),
        files=["f.out"],
    )
    assert len(transient_errors2) == 0
    assert len(permanent_errors2) == 0


@pytest.mark.asyncio
async def test_download_outputs_rmtree_only_on_full_success() -> None:
    """rmtree runs ONLY when both transient_errors and permanent_errors are empty."""
    # Full success -> rmtree called once.
    sftp_ok = AsyncMock()
    sftp_ok.get = AsyncMock(return_value=None)
    sftp_ok.rmtree = AsyncMock(return_value=None)
    _repo_ok, ops_ok = make_gateway_with_sftp(sftp_ok)
    await ops_ok.download_outputs(
        ip="10.0.0.1", remote_dir="/r", local_dir=Path("/l"), files=["f1", "f2"]
    )
    sftp_ok.rmtree.assert_awaited_once_with(PurePosixPath("/r"))

    # One permanent error -> rmtree NOT called.
    sftp_perm = AsyncMock()
    sftp_perm.get = AsyncMock(side_effect=OSError("denied"))
    sftp_perm.rmtree = AsyncMock(return_value=None)
    _repo_perm, ops_perm = make_gateway_with_sftp(sftp_perm)
    _, transient, permanent = await ops_perm.download_outputs(
        ip="10.0.0.1", remote_dir="/r", local_dir=Path("/l"), files=["f1", "f2"]
    )
    assert len(permanent) == 2
    assert transient == []
    sftp_perm.rmtree.assert_not_awaited()

    # One transient error -> rmtree NOT called.
    sftp_trans = AsyncMock()
    sftp_trans.get = AsyncMock(side_effect=SFTPFailure("lost"))
    sftp_trans.rmtree = AsyncMock(return_value=None)
    _repo_trans, ops_trans = make_gateway_with_sftp(sftp_trans)
    _, transient2, permanent2 = await ops_trans.download_outputs(
        ip="10.0.0.1", remote_dir="/r", local_dir=Path("/l"), files=["f1", "f2"]
    )
    assert len(transient2) == 2
    assert permanent2 == []
    sftp_trans.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_per_file_sftp_isolation() -> None:
    """A dropped SFTP client on file 2 does not fail-fast file 3 (fresh client per file)."""
    repository = SSHMachineRepository()
    operations = SSHMachineOperations(repository=repository)
    repository.get_path = MagicMock(return_value=PurePosixPath)  # type: ignore[assignment]

    clients: list[AsyncMock] = []

    @asynccontextmanager
    async def fresh_sftp(_ip: str) -> AsyncGenerator[AsyncMock, None]:
        idx = len(clients)
        sftp = AsyncMock()
        # file 2 (index 1) drops its connection mid-transfer; others succeed.
        if idx == 1:
            sftp.get = AsyncMock(side_effect=SFTPConnectionLost("dropped"))
        else:
            sftp.get = AsyncMock(return_value=None)
        sftp.rmtree = AsyncMock(return_value=None)
        clients.append(sftp)
        yield sftp

    operations.get_sftp = fresh_sftp  # type: ignore[assignment]

    _, transient_errors, permanent_errors = await operations.download_outputs(
        ip="10.0.0.1",
        remote_dir="/r",
        local_dir=Path("/l"),
        files=["f1", "f2", "f3"],
        task_id=7,
    )

    # 3 per-file clients opened (rmtree NOT reached: a transient error exists).
    assert len(clients) == 3
    # file 2 classified transient; no permanent errors.
    assert len(transient_errors) == 1
    assert transient_errors[0][0] == "f2"
    assert isinstance(transient_errors[0][1], SFTPConnectionLost)
    assert permanent_errors == []
    # file 3 got its own fresh client and was actually attempted.
    assert clients[2].get.await_count == 1
    # rmtree never reached (gate false due to the transient error).
    for c in clients:
        c.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_session_level_failure_transient() -> None:
    """get_sftp OPEN failure -> outer handler -> session-level transient (remote dir preserved)."""
    repository = SSHMachineRepository()
    operations = SSHMachineOperations(repository=repository)
    repository.get_path = MagicMock(return_value=PurePosixPath)  # type: ignore[assignment]

    @asynccontextmanager
    async def broken_sftp(_ip: str) -> AsyncGenerator[Any, None]:
        raise SFTPConnectionLost("no session")
        yield  # type: ignore[unreachable]

    operations.get_sftp = broken_sftp  # type: ignore[assignment]

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
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
    assert isinstance(exc, SFTPConnectionLost)

# FILE: tests/unit/test_ssh_gateway_download_outputs.py
# VERSION: 1.3.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for SSHMachineOperations.download_outputs classification + conditional rmtree.
#   SCOPE: Success path, per-file permanent error, per-file transient error, session-level error, rmtree gating, per-file SFTP isolation, task_id log correlation.
#   DEPENDS: M-SSH-OPS-DOWNLOAD, M-SSH-SESSION
#   LINKS: M-SSH-OPS-DOWNLOAD, M-SSH-SESSION
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   _make_session_with_sftp - Build an SSHMachineSession whose _conn.start_sftp_client yields a configured sftp mock
#   test_download_outputs_success - All files download OK; returns (meta_add, [], []); rmtree called
#   test_download_outputs_per_file_permanent_error - Per-file OSError caught; classified permanent; rmtree NOT called (conservative gate)
#   test_download_outputs_per_file_transient_error - Per-file SFTPFailure (SFTPRetryExc) caught; classified transient; rmtree NOT called
#   test_download_outputs_session_error - Session-level failure caught; returned in transient_errors; rmtree NOT called
#   test_download_outputs_task_id_in_signature - task_id param accepted for log correlation
#   test_download_outputs_rmtree_only_on_full_success - rmtree called only when both error lists empty
#   test_download_outputs_per_file_sftp_isolation - dropped client on file 2 does not fail-fast file 3
#   test_download_outputs_session_level_failure_transient - open_sftp failure -> session-level transient
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - session-based-machine-handle: download_outputs now takes a session param (was ip). Tests build a real SSHMachineSession via _make_state and wire sftp mocks on session._conn.start_sftp_client (was operations.get_sftp / repository.get_path monkey-patches). session.path replaces repository.get_path.
#   PREVIOUS_CHANGE: v1.2.0 - Update for fix-nonidempotent-ssh-retries: download_outputs now opens a FRESH get_sftp client per file and rmtree is gated on `not transient_errors AND not permanent_errors` (conservative — permanent errors now preserve the remote dir). Add an autouse fixture that neutralizes my_backoff_sftp (per-file retry) to a passthrough so transient SFTP exceptions (SFTPFailure/SFTPConnectionLost) reach the classifier immediately instead of triggering the real 60s fibonacci backoff — this was the unit-test timeout root cause. Add per-file SFTP isolation test (fresh client per file; file-2 failure does not fail-fast file 3) and session-level-failure test (get_sftp-open raises -> session-level transient). Flip the permanent-error rmtree assertion to assert_not_awaited (gate now includes permanent_errors).
# END_CHANGE_SUMMARY

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asyncssh.sftp import SFTPFailure

from tests.unit.test_ssh_gateway import _make_state
from yascheduler.domain.model import TaskId
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.operations import download as download_module
from yascheduler.infra.ssh.platform.protocol import SFTPConnectionLost
from yascheduler.infra.ssh.repository import SSHMachineRepository
from yascheduler.infra.ssh.session import SSHMachineSession


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


def _wire_sftp(session: SSHMachineSession, sftp_mock: AsyncMock) -> SSHMachineSession:
    """Install ``sftp_mock`` as the singleton SFTP client yielded by the session's conn."""
    session._adapter.path = PurePosixPath  # type: ignore[method-assign,misc]  # noqa: SLF001

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[AsyncMock, None]:
        yield sftp_mock

    session._conn.start_sftp_client = _sftp_ctx  # type: ignore[method-assign,misc,assignment]  # noqa: SLF001
    return session


def _make_session_with_sftp(sftp_mock: AsyncMock) -> SSHMachineSession:
    """Construct a session whose open_sftp() yields sftp_mock and whose .path is PurePosixPath."""
    session = _make_state()
    return _wire_sftp(session, sftp_mock)


def _make_operations() -> SSHMachineOperations:
    return SSHMachineOperations(repository=SSHMachineRepository())


@pytest.mark.asyncio
async def test_download_outputs_success() -> None:
    """All files download OK, rmtree called, returns (meta_add, [], [])."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(return_value=None)
    sftp_mock.rmtree = AsyncMock(return_value=None)
    session = _make_session_with_sftp(sftp_mock)
    operations = _make_operations()

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=TaskId(42),
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
    session = _make_session_with_sftp(sftp_mock)
    operations = _make_operations()

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=TaskId(42),
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
    sftp_mock.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_per_file_transient_error() -> None:
    """Per-file SFTPFailure (in SFTPRetryExc) -> transient_errors; rmtree NOT called."""
    sftp_mock = AsyncMock()
    sftp_mock.get = AsyncMock(side_effect=SFTPFailure("connection lost"))
    sftp_mock.rmtree = AsyncMock(return_value=None)
    session = _make_session_with_sftp(sftp_mock)
    operations = _make_operations()

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=TaskId(42),
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
    sftp_mock.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_session_error() -> None:
    """open_sftp raises (session-level failure); caught in transient_errors; rmtree NOT called."""
    session = _make_state()
    session._adapter.path = PurePosixPath  # type: ignore[method-assign,misc]  # noqa: SLF001

    @asynccontextmanager
    async def bad_sftp() -> AsyncGenerator[Any, None]:
        raise OSError("no connection")
        yield  # type: ignore[unreachable]

    session._conn.start_sftp_client = bad_sftp  # type: ignore[method-assign,misc]  # noqa: SLF001
    operations = _make_operations()

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=TaskId(42),
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
    session = _make_session_with_sftp(sftp_mock)
    operations = _make_operations()

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/r",
        local_dir=Path("/l"),
        files=["f.out"],
        task_id=TaskId(99),
    )
    assert len(transient_errors) == 0
    assert len(permanent_errors) == 0
    assert len(meta_add) == 2

    # Without task_id (None default)
    meta_add2, transient_errors2, permanent_errors2 = await operations.download_outputs(
        session,
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
    session_ok = _make_session_with_sftp(sftp_ok)
    ops_ok = _make_operations()
    await ops_ok.download_outputs(
        session_ok, remote_dir="/r", local_dir=Path("/l"), files=["f1", "f2"]
    )
    sftp_ok.rmtree.assert_awaited_once_with(PurePosixPath("/r"))

    # One permanent error -> rmtree NOT called.
    sftp_perm = AsyncMock()
    sftp_perm.get = AsyncMock(side_effect=OSError("denied"))
    sftp_perm.rmtree = AsyncMock(return_value=None)
    session_perm = _make_session_with_sftp(sftp_perm)
    ops_perm = _make_operations()
    _, transient, permanent = await ops_perm.download_outputs(
        session_perm, remote_dir="/r", local_dir=Path("/l"), files=["f1", "f2"]
    )
    assert len(permanent) == 2
    assert transient == []
    sftp_perm.rmtree.assert_not_awaited()

    # One transient error -> rmtree NOT called.
    sftp_trans = AsyncMock()
    sftp_trans.get = AsyncMock(side_effect=SFTPFailure("lost"))
    sftp_trans.rmtree = AsyncMock(return_value=None)
    session_trans = _make_session_with_sftp(sftp_trans)
    ops_trans = _make_operations()
    _, transient2, permanent2 = await ops_trans.download_outputs(
        session_trans, remote_dir="/r", local_dir=Path("/l"), files=["f1", "f2"]
    )
    assert len(transient2) == 2
    assert permanent2 == []
    sftp_trans.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_per_file_sftp_isolation() -> None:
    """A dropped SFTP client on file 2 does not fail-fast file 3 (fresh client per file)."""
    session = _make_state()
    session._adapter.path = PurePosixPath  # type: ignore[method-assign,misc]  # noqa: SLF001
    operations = _make_operations()

    clients: list[AsyncMock] = []

    @asynccontextmanager
    async def fresh_sftp() -> AsyncGenerator[AsyncMock, None]:
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

    session._conn.start_sftp_client = fresh_sftp  # type: ignore[method-assign,misc,assignment]  # noqa: SLF001

    _, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/r",
        local_dir=Path("/l"),
        files=["f1", "f2", "f3"],
        task_id=TaskId(7),
    )

    # 3 per-file clients opened (rmtree NOT reached: a transient error exists).
    assert len(clients) == 3
    assert len(transient_errors) == 1
    assert transient_errors[0][0] == "f2"
    assert isinstance(transient_errors[0][1], SFTPConnectionLost)
    assert permanent_errors == []
    assert clients[2].get.await_count == 1
    for c in clients:
        c.rmtree.assert_not_awaited()


@pytest.mark.asyncio
async def test_download_outputs_session_level_failure_transient() -> None:
    """open_sftp OPEN failure -> outer handler -> session-level transient (remote dir preserved)."""
    session = _make_state()
    session._adapter.path = PurePosixPath  # type: ignore[method-assign,misc]  # noqa: SLF001
    operations = _make_operations()

    @asynccontextmanager
    async def broken_sftp() -> AsyncGenerator[Any, None]:
        raise SFTPConnectionLost("no session")
        yield  # type: ignore[unreachable]

    session._conn.start_sftp_client = broken_sftp  # type: ignore[method-assign,misc]  # noqa: SLF001

    meta_add, transient_errors, permanent_errors = await operations.download_outputs(
        session,
        remote_dir="/remote/path",
        local_dir=Path("/local/path"),
        files=["f1.out", "f2.out"],
        task_id=TaskId(42),
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

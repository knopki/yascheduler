# FILE: tests/unit/test_ssh_gateway_write_remote_file.py
# VERSION: 1.0.1
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for _write_remote_file exception contract (fix-write-remote-file-swallow).
#   SCOPE: Non-SFTP exception propagates (not swallowed); asyncssh.misc.Error logged with
#     structured code/reason and re-raised; start_task_on_machine aborts spawn on upload failure;
#     successful write returns normally and the per-file loop continues.
#   DEPENDS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-DOMAIN-MODEL
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestWriteRemoteFilePropagation - non-SFTP and SFTP exceptions propagate per the spec contract
#   TestStartTaskAbortOnUploadFailure - upload failure aborts spawn (no _exec_spawn_command)
#   TestSuccessfulWrite - success path returns normally and the loop continues
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Add test_open_failure_propagates covering a non-SFTP exception raised by sftp.open() (same try block as f.write; gap surfaced by the bug-hunt review of v1.0.0). Helper _make_sftp_state gains an open_side_effect parameter.
#   PREVIOUS_CHANGE: v1.0.0 - Initial tests for fix-write-remote-file-swallow: non-SFTP exception
#     propagation through _write_remote_file / _upload_task_data; asyncssh.misc.Error structured
#     log + re-raise; start_task_on_machine abort contract (spawn not called on upload failure);
#     successful write + loop continuation.
# END_CHANGE_SUMMARY

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock, MagicMock

import asyncssh
import pytest

from yascheduler.domain import Engine
from yascheduler.domain.model import Task, TaskContext
from yascheduler.infra.ssh.operations import SSHMachineOperations
from yascheduler.infra.ssh.operations.deployment import _write_remote_file
from yascheduler.infra.ssh.repository import SSHMachineRepository, _MachineState

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from asyncssh.sftp import SFTPClient


# =============================================================================
# Helpers
# =============================================================================


class _FakeSFTPFile:
    """Async context manager mimicking asyncssh SFTPFile — write() is configurable."""

    def __init__(self, write_side_effect: BaseException | None = None) -> None:
        self._write_side_effect = write_side_effect
        self.write = AsyncMock(side_effect=write_side_effect)

    async def __aenter__(self) -> _FakeSFTPFile:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSFTPClient:
    """SFTP client whose open() returns a configured _FakeSFTPFile context manager."""

    def __init__(
        self, file: _FakeSFTPFile, open_side_effect: BaseException | None = None
    ) -> None:
        self._file = file
        self.open = (
            MagicMock(return_value=file)
            if open_side_effect is None
            else MagicMock(side_effect=open_side_effect)
        )
        self.makedirs = AsyncMock(return_value=None)
        self.realpath = AsyncMock(return_value="/root")


def _make_sftp_state(
    write_side_effect: BaseException | None = None,
    open_side_effect: BaseException | None = None,
) -> tuple[_MachineState, _FakeSFTPClient]:
    """Build a _MachineState wired so its SFTP session yields a _FakeSFTPClient.

    The _FakeSFTPFile.write() raises ``write_side_effect`` (if set) or returns
    None (success path). If ``open_side_effect`` is set, sftp.open() raises
    before the file context is entered (exercises the same try block). The
    connection's start_sftp_client returns the same _FakeSFTPClient on every
    entry so _upload_task_data and start_task_on_machine see a consistent mock.
    """
    from tests.unit.test_ssh_gateway import _make_state

    file = _FakeSFTPFile(write_side_effect=write_side_effect)
    sftp = _FakeSFTPClient(file, open_side_effect=open_side_effect)

    state = _make_state()

    @asynccontextmanager
    async def _sftp_ctx() -> AsyncGenerator[_FakeSFTPClient, None]:
        yield sftp

    state.conn.start_sftp_client = _sftp_ctx  # type: ignore[assignment]
    return state, sftp


def _make_engine(input_files: tuple[str, ...] = ("input.txt",)) -> Engine:
    return Engine(
        name="test_engine",
        spawn="{engine_path} {task_path} {ncpus}",
        input_files=input_files,
    )


def _make_task(extra: dict[str, object] | None = None) -> Task:
    return Task(
        task_id=7,
        label="t7",
        context=TaskContext(
            engine="test_engine",
            remote_folder="/remote/tasks/7",
            extra=extra or {"input.txt": "hello"},
        ),
    )


# =============================================================================
# _write_remote_file exception contract
# =============================================================================


class TestWriteRemoteFilePropagation:
    """_write_remote_file SHALL re-raise non-SFTP exceptions (not swallow) and
    SHALL log structured code/reason for asyncssh.misc.Error then re-raise."""

    @pytest.mark.asyncio
    async def test_non_sftp_exception_propagates(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A ValueError raised by f.write() propagates out of _write_remote_file.

        The asyncssh.misc.Error-branch structured log line ("Write <path> -
        SFTPError: ...") MUST NOT be emitted for a non-SFTP exception.
        """
        log = logging.getLogger("test_write_remote_file_non_sftp")
        log.setLevel(logging.DEBUG)
        file = _FakeSFTPFile(write_side_effect=ValueError("bad data"))
        sftp = _FakeSFTPClient(file)

        with caplog.at_level(logging.ERROR, logger=log.name):
            with pytest.raises(ValueError, match="bad data"):
                await _write_remote_file(
                    cast("SFTPClient", sftp), "/r/input.txt", b"data", log, mode="wb"
                )

        # The structured SFTPError log line is reserved for asyncssh.misc.Error.
        assert not any("SFTPError" in r.getMessage() for r in caplog.records), (
            "asyncssh.misc.Error-branch log was emitted for a non-SFTP exception"
        )

    @pytest.mark.asyncio
    async def test_binascii_error_propagates(self) -> None:
        """A binascii.Error (the real malformed-fort.9 failure class) propagates."""
        import binascii

        log = logging.getLogger("test_write_remote_file_binascii")
        file = _FakeSFTPFile(write_side_effect=binascii.Error("Invalid base64"))
        sftp = _FakeSFTPClient(file)

        with pytest.raises(binascii.Error):
            await _write_remote_file(
                cast("SFTPClient", sftp), "/r/fort.9", b"x", log, mode="wb"
            )

    @pytest.mark.asyncio
    async def test_open_failure_propagates(self) -> None:
        """A non-SFTP exception raised by sftp.open() (before write) propagates.

        The try block wraps `async with sftp.open(...) as f:` — an exception
        from `open` takes the same propagation path as one from `f.write`.
        """
        log = logging.getLogger("test_write_remote_file_open_fail")
        file = _FakeSFTPFile()
        sftp = _FakeSFTPClient(file, open_side_effect=OSError("open boom"))

        with pytest.raises(OSError, match="open boom"):
            await _write_remote_file(
                cast("SFTPClient", sftp), "/r/input.txt", b"data", log, mode="wb"
            )

        # write was never reached (open failed first).
        file.write.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_asyncssh_misc_error_logged_and_reraised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An asyncssh.misc.Error is logged with structured code/reason and re-raised."""
        log = logging.getLogger("test_write_remote_file_sftp")
        log.setLevel(logging.DEBUG)
        err = asyncssh.misc.Error(2, "No such file")
        file = _FakeSFTPFile(write_side_effect=err)
        sftp = _FakeSFTPClient(file)

        with caplog.at_level(logging.ERROR, logger=log.name):
            with pytest.raises(asyncssh.misc.Error) as exc_info:
                await _write_remote_file(
                    cast("SFTPClient", sftp), "/r/input.txt", b"data", log, mode="wb"
                )

        # The same exception instance is re-raised (no swallow, no rewrap).
        assert exc_info.value is err
        # The structured log line carries the path, reason, and code.
        assert any(
            "SFTPError" in r.getMessage()
            and "No such file" in r.getMessage()
            and "/r/input.txt" in r.getMessage()
            for r in caplog.records
        ), "asyncssh.misc.Error was not logged with structured code/reason and path"

    @pytest.mark.asyncio
    async def test_sftp_error_subclass_logged_and_reraised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SFTPError (asyncssh.misc.Error subclass from sftp.open/f.write) is logged and re-raised."""
        from asyncssh.sftp import SFTPError

        log = logging.getLogger("test_write_remote_file_sftperror")
        log.setLevel(logging.DEBUG)
        err = SFTPError(3, "Permission denied")
        file = _FakeSFTPFile(write_side_effect=err)
        sftp = _FakeSFTPClient(file)

        with caplog.at_level(logging.ERROR, logger=log.name):
            with pytest.raises(SFTPError) as exc_info:
                await _write_remote_file(
                    cast("SFTPClient", sftp), "/r/fort.9", b"x", log, mode="wb"
                )

        assert exc_info.value is err
        assert any(
            "SFTPError" in r.getMessage() and "Permission denied" in r.getMessage()
            for r in caplog.records
        )


# =============================================================================
# start_task_on_machine abort contract
# =============================================================================


class TestStartTaskAbortOnUploadFailure:
    """When _upload_task_data fails, _exec_spawn_command SHALL NOT run."""

    @pytest.mark.asyncio
    async def test_non_sftp_upload_failure_aborts_spawn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-SFTP exception during an input file write aborts start_task_on_machine:
        _exec_spawn_command is NOT called; the exception propagates to the caller;
        the upstream handler logs "Can't upload task_id=N files: <err>" with the task_id.
        """
        repository = SSHMachineRepository()
        operations = SSHMachineOperations(repository=repository)
        state, _sftp = _make_sftp_state(write_side_effect=ValueError("bad input"))
        repository._machines["10.0.0.1"] = state
        machine = repository._machines["10.0.0.1"].machine

        spawn_calls: list[Any] = []
        operations.deploy._exec_spawn_command = AsyncMock(  # type: ignore[method-assign]
            side_effect=lambda *a, **kw: spawn_calls.append((a, kw))
        )

        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError, match="bad input"):
                await operations.start_task_on_machine(
                    machine,
                    _make_engine(input_files=("input.txt",)),
                    _make_task(extra={"input.txt": "hello"}),
                    4,
                    PurePosixPath("/engines"),
                )

        # spawn never runs — the abort contract.
        assert spawn_calls == [], (
            "_exec_spawn_command was called despite an input file write failure"
        )
        # The upstream handler logs with task_id (better diagnostics than the
        # old swallowed "Error processing file" line which lacked task_id).
        assert any(
            "Can't upload task_id=7 files" in r.getMessage() for r in caplog.records
        ), "upstream upload-failure log did not carry the task_id"

    @pytest.mark.asyncio
    async def test_sftp_upload_failure_aborts_spawn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An asyncssh.misc.Error during an input file write aborts start_task_on_machine."""
        repository = SSHMachineRepository()
        operations = SSHMachineOperations(repository=repository)
        err = asyncssh.misc.Error(2, "No such file")
        state, _sftp = _make_sftp_state(write_side_effect=err)
        repository._machines["10.0.0.1"] = state
        machine = repository._machines["10.0.0.1"].machine

        operations.deploy._exec_spawn_command = AsyncMock()  # type: ignore[method-assign]

        with caplog.at_level(logging.ERROR):
            with pytest.raises(asyncssh.misc.Error):
                await operations.start_task_on_machine(
                    machine,
                    _make_engine(input_files=("input.txt",)),
                    _make_task(extra={"input.txt": "hello"}),
                    4,
                    PurePosixPath("/engines"),
                )

        operations.deploy._exec_spawn_command.assert_not_awaited()  # type: ignore[attr-defined]
        # Both diagnostic lines present: the structured SFTPError (from the
        # _write_remote_file branch) and the task_id-bearing upload-failure
        # log (from the start_task_on_machine DEPLOY handler).
        assert any("SFTPError" in r.getMessage() for r in caplog.records)
        assert any(
            "Can't upload task_id=7 files" in r.getMessage() for r in caplog.records
        )


# =============================================================================
# Successful write path
# =============================================================================


class TestSuccessfulWrite:
    """A successful write returns normally and the per-file loop continues."""

    @pytest.mark.asyncio
    async def test_successful_write_no_log_no_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_write_remote_file returns normally on success — no exception, no error log."""
        log = logging.getLogger("test_write_remote_file_success")
        log.setLevel(logging.DEBUG)
        file = _FakeSFTPFile(write_side_effect=None)
        sftp = _FakeSFTPClient(file)

        with caplog.at_level(logging.ERROR, logger=log.name):
            await _write_remote_file(
                cast("SFTPClient", sftp), "/r/input.txt", b"data", log, mode="wb"
            )

        file.write.assert_awaited_once_with(b"data")
        assert not any(r.levelno >= logging.ERROR for r in caplog.records), (
            "an error log was emitted on a successful write"
        )

    @pytest.mark.asyncio
    async def test_upload_loop_continues_across_files(self) -> None:
        """_upload_task_data writes every input file when none raise; returns True."""
        repository = SSHMachineRepository()
        operations = SSHMachineOperations(repository=repository)
        state, sftp = _make_sftp_state(write_side_effect=None)
        repository._machines["10.0.0.1"] = state

        # Two input files; the _FakeSFTPFile is shared across calls so we can
        # count write invocations across the loop.
        ok = await operations.deploy._upload_task_data(
            "10.0.0.1",
            _make_task(extra={"input.txt": "a", "fort.9": "AAAA"}),
            PurePosixPath("/remote/tasks/7"),
            input_files=("input.txt", "fort.9"),
        )

        assert ok is True
        # Both files were written (the loop did not bail after the first).
        assert sftp._file.write.await_count == 2

# region MODULE_CONTRACT
# PURPOSE: Unit tests for windows_list_processes JSON line parsing, self-process skipping, and broken-line handling.
# SCOPE: windows_list_processes against a fake SSHClientConnection emitting canned PowerShell JSON lines.
# KEYWORDS: windows, list_processes, pgrep, self-skip, occupancy, regression
# endregion MODULE_CONTRACT

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from yascheduler.infra.ssh.platform.windows import windows_list_processes

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from typing import Any


def _json_line(*, pid: int, name: str, command: str) -> str:
    return json.dumps({"pid": pid, "name": name, "command": command})


class _FakeStdout:
    def __init__(self, lines: Sequence[str]) -> None:
        self._lines = list(lines)

    def __aiter__(self) -> _FakeStdout:
        return self

    async def __anext__(self) -> str:
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class _FakeProcess:
    def __init__(self, lines: Sequence[str]) -> None:
        self.stdout = _FakeStdout(lines)

    async def __aenter__(self) -> _FakeProcess:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _conn(lines: Iterable[str]) -> Any:
    conn = MagicMock()
    conn.create_process.return_value = _FakeProcess(list(lines))
    return conn


async def test_yields_valid_lines_and_logs_broken_ones(caplog: Any) -> None:
    """Broken JSON is skipped but must not be silent: a warning record is emitted."""
    good = _json_line(
        pid=12345, name="dummyengine", command="./dummyengine --input foo"
    )
    conn = _conn([good, "not json at all", good])

    with caplog.at_level(
        logging.WARNING, logger="yascheduler.infra.ssh.platform.windows"
    ):
        results = [p async for p in windows_list_processes(conn)]

    assert len(results) == 2
    assert results[0].pid == 12345
    assert results[0].name == "dummyengine"

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "SKIP_UNPARSEABLE_PROCESS_LINE"
    assert record.line == "not json at all"
    assert "error" in record.__dict__


async def test_skips_self_ps_command() -> None:
    """The PowerShell wrapper running Get-CimInstance must not appear in the listing."""
    self_line = _json_line(
        pid=10761,
        name="powershell.exe",
        command="Get-CimInstance Win32_Process | %{ ... }",
    )
    engine_line = _json_line(pid=12345, name="dummyengine", command="./dummyengine")
    conn = _conn([self_line, engine_line])

    results = [p async for p in windows_list_processes(conn)]

    assert len(results) == 1
    assert results[0].pid == 12345


async def test_skips_lines_without_command_falls_back_to_name() -> None:
    """Empty command falls back to process name."""
    line = _json_line(pid=42, name="svchost.exe", command="")
    conn = _conn([line])

    results = [p async for p in windows_list_processes(conn)]

    assert len(results) == 1
    assert results[0].command == "svchost.exe"

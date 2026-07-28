# region MODULE_CONTRACT
# PURPOSE: Unit tests for yascheduler/entrypoints/logger.py — configure_logger.
# SCOPE: configure_logger handler/level/suppression/captureWarnings behavior; timestamp flag wiring.
# KEYWORDS: entrypoints, logger, configure_logger, timestamp
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    """Snapshot and restore the root logger so handler additions don't leak across tests."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    original_asyncssh_level = logging.getLogger("asyncssh").level
    try:
        yield
    finally:
        root.setLevel(original_level)
        root.handlers = list(original_handlers)
        logging.getLogger("asyncssh").setLevel(original_asyncssh_level)


# ── Test 1: Gherkin scenario — configure_logger timestamp defaults to off ──


def test_configure_logger_timestamp_defaults_to_off() -> None:
    """configure_logger called without timestamp wires a LogFormatter whose timestamp flag is False."""
    from yascheduler.entrypoints.logger import configure_logger
    from yascheduler.shared.log import LogFormatter

    root = configure_logger(None, logging.INFO)
    formatters = [
        h.formatter for h in root.handlers if isinstance(h.formatter, LogFormatter)
    ]
    assert formatters, "Expected at least one LogFormatter on root handlers"
    assert all(getattr(f, "_timestamp", None) is False for f in formatters), (
        f"Expected _timestamp=False on all LogFormatters, got: {formatters!r}"
    )


# ── Test 2: Gherkin scenario — configure_logger writes to stderr when log_file is None ──


def test_configure_logger_stderr_only_when_log_file_none() -> None:
    """configure_logger(log_file=None) adds a StreamHandler(sys.stderr) with a LogFormatter and no FileHandler."""
    from yascheduler.entrypoints.logger import configure_logger
    from yascheduler.shared.log import LogFormatter

    root = configure_logger(None, logging.INFO)
    sh = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and isinstance(h.formatter, LogFormatter)
    ]
    fh = [
        h
        for h in root.handlers
        if isinstance(h, logging.FileHandler) and isinstance(h.formatter, LogFormatter)
    ]
    assert sh, "Expected a StreamHandler(sys.stderr) with LogFormatter"
    assert any(h.stream is sys.stderr for h in sh)
    assert not fh, "Expected no LogFormatter-wired FileHandler"


# ── Test 3: Gherkin scenario — configure_logger writes to file and stderr when log_file is set ──


def test_configure_logger_file_and_stderr_when_log_file_set(tmp_path: Path) -> None:
    """configure_logger(log_file=path) adds both a StreamHandler(sys.stderr) and a FileHandler, both with LogFormatter."""
    from yascheduler.entrypoints.logger import configure_logger
    from yascheduler.shared.log import LogFormatter

    log_path = tmp_path / "y.log"
    root = configure_logger(str(log_path), logging.INFO)

    sh = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and isinstance(h.formatter, LogFormatter)
    ]
    fh = [
        h
        for h in root.handlers
        if isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == str(log_path)
        and isinstance(h.formatter, LogFormatter)
    ]
    assert sh, "Expected a StreamHandler(sys.stderr) with LogFormatter"
    assert len(fh) == 1, f"Expected one FileHandler at {log_path}, got {fh!r}"
    assert isinstance(fh[0].formatter, LogFormatter)


# ── Test 4: configure_logger sets asyncssh to ERROR ──


def test_configure_logger_sets_asyncssh_to_error() -> None:
    """configure_logger suppresses asyncssh chatter to ERROR."""
    from yascheduler.entrypoints.logger import configure_logger

    configure_logger(None, logging.INFO)
    assert logging.getLogger("asyncssh").level == logging.ERROR


# ── Test 5: configure_logger calls captureWarnings(True) ──


def test_configure_logger_calls_capture_warnings_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logger routes warnings.warn through logging."""
    from yascheduler.entrypoints.logger import configure_logger

    spy = MagicMock()
    monkeypatch.setattr(logging, "captureWarnings", spy)
    configure_logger(None, logging.INFO)
    spy.assert_called_once_with(True)


# ── Test 6: configure_logger does NOT call basicConfig ──


def test_configure_logger_does_not_call_basic_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_logger sets handlers and level explicitly; never delegates to basicConfig."""
    from yascheduler.entrypoints.logger import configure_logger

    spy = MagicMock()
    monkeypatch.setattr(logging, "basicConfig", spy)
    configure_logger(None, logging.INFO)
    spy.assert_not_called()


# ── Test 7: configure_logger sets the ROOT level ──


def test_configure_logger_sets_root_level() -> None:
    """configure_logger sets the ROOT logger level to the provided value."""
    from yascheduler.entrypoints.logger import configure_logger

    root = configure_logger(None, logging.DEBUG)
    assert root.level == logging.DEBUG


# ── Test 8: Gherkin scenario — single formatter serves both handlers ──


def test_configure_logger_single_formatter_serves_both_handlers(
    tmp_path: Path,
) -> None:
    """configure_logger wires the SAME LogFormatter instance onto stderr and file handlers."""
    from yascheduler.entrypoints.logger import configure_logger
    from yascheduler.shared.log import LogFormatter

    log_path = tmp_path / "y.log"
    root = configure_logger(str(log_path), logging.INFO)

    sh = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and isinstance(h.formatter, LogFormatter)
    ]
    fh = [
        h
        for h in root.handlers
        if isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == str(log_path)
        and isinstance(h.formatter, LogFormatter)
    ]
    assert sh and fh
    assert sh[0].formatter is fh[0].formatter


# ── Slice 3 — configure_cli_logger scenarios ──


# ── Test 9: Gherkin — StreamHandler with LogFormatter added when no handler present ──


def test_configure_cli_logger_adds_streamhandler_with_logformatter_when_no_handler() -> (
    None
):
    """configure_cli_logger adds StreamHandler(sys.stderr) wired with LogFormatter when the ROOT logger has no handlers."""
    from yascheduler.entrypoints.logger import configure_cli_logger
    from yascheduler.shared.log import LogFormatter

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers.clear()
    try:
        configure_cli_logger(logging.DEBUG)
        sh = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
            and isinstance(h.formatter, LogFormatter)
        ]
        assert sh, (
            f"Expected a StreamHandler(sys.stderr) with LogFormatter, got handlers={root.handlers!r}"
        )
        assert any(h.stream is sys.stderr for h in sh)
        # LogFormatter is timestamp-disabled in the CLI path.
        assert all(getattr(h.formatter, "_timestamp", None) is False for h in sh)
    finally:
        root.handlers = saved_handlers


# ── Test 10: Gherkin — pre-attached handler is preserved (no duplicate added) ──


def test_configure_cli_logger_preserves_pre_attached_handler() -> None:
    """configure_cli_logger does NOT add a StreamHandler when the ROOT logger already has one."""
    from yascheduler.entrypoints.logger import configure_cli_logger

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    sentinel = logging.StreamHandler()
    root.handlers = [sentinel]
    try:
        configure_cli_logger(logging.INFO)
        assert root.handlers == [sentinel], (
            f"Expected the pre-attached handler to be preserved unchanged, got {root.handlers!r}"
        )
    finally:
        root.handlers = saved_handlers


# ── Test 11: Gherkin — captureWarnings(True) in effect ──


def test_configure_cli_logger_enables_capture_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """configure_cli_logger routes warnings.warn through logging."""
    from yascheduler.entrypoints.logger import configure_cli_logger

    spy = MagicMock()
    monkeypatch.setattr(logging, "captureWarnings", spy)
    configure_cli_logger(logging.INFO)
    spy.assert_called_once_with(True)


# ── Test 12: Gherkin — asyncssh logger level is NOT changed ──


def test_configure_cli_logger_does_not_change_asyncssh_level() -> None:
    """configure_cli_logger leaves asyncssh at its inherited default (unlike configure_logger)."""
    from yascheduler.entrypoints.logger import configure_cli_logger

    original_asyncssh_level = logging.getLogger("asyncssh").level
    try:
        configure_cli_logger(logging.INFO)
        assert logging.getLogger("asyncssh").level == original_asyncssh_level
    finally:
        logging.getLogger("asyncssh").setLevel(original_asyncssh_level)


# ── Test 13: Gherkin — no FileHandler added ──


def test_configure_cli_logger_does_not_add_filehandler() -> None:
    """configure_cli_logger adds NO FileHandler to the ROOT logger."""
    from yascheduler.entrypoints.logger import configure_cli_logger

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers.clear()
    try:
        configure_cli_logger(logging.INFO)
        assert not any(isinstance(h, logging.FileHandler) for h in root.handlers), (
            f"Expected no FileHandler, got {root.handlers!r}"
        )
    finally:
        root.handlers = saved_handlers


# ── Test 14: ROOT logger level is set ──


def test_configure_cli_logger_sets_root_level() -> None:
    """configure_cli_logger sets the ROOT logger level to the provided value."""
    from yascheduler.entrypoints.logger import configure_cli_logger

    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = root.handlers[:]
    try:
        configure_cli_logger(logging.DEBUG)
        assert root.level == logging.DEBUG
    finally:
        root.setLevel(saved_level)
        root.handlers = saved_handlers


# ── Test 2: Gherkin scenario — configure_logger timestamp=True enables ISO 8601 prefix on both handlers ──


def test_configure_logger_timestamp_true_enables_prefix_on_both_handlers(
    tmp_path: Path,
) -> None:
    """configure_logger(log_file, level, timestamp=True) wires a timestamp-enabled LogFormatter on both stderr and file handlers."""
    from yascheduler.entrypoints.logger import configure_logger
    from yascheduler.shared.log import LogFormatter

    log_path = tmp_path / "y.log"
    root = configure_logger(str(log_path), logging.INFO, timestamp=True)

    stderr_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and isinstance(h.formatter, LogFormatter)
    ]
    file_handlers = [
        h
        for h in root.handlers
        if isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == str(log_path)
        and isinstance(h.formatter, LogFormatter)
    ]
    assert stderr_handlers, "No StreamHandler(sys.stderr) found"
    assert file_handlers, f"No FileHandler pointing at {log_path} found"

    assert all(
        getattr(h.formatter, "_timestamp", None) is True for h in stderr_handlers
    ), f"stderr handlers missing _timestamp=True: {stderr_handlers!r}"
    assert all(
        getattr(h.formatter, "_timestamp", None) is True for h in file_handlers
    ), f"file handlers missing _timestamp=True: {file_handlers!r}"
    assert all(
        isinstance(h.formatter, LogFormatter) for h in stderr_handlers + file_handlers
    )


# ── Test 3: Gherkin scenarios — daemon launchers route the timestamp flag ──


def test_daemonize_passes_timestamp_true(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """daemonize (foreground yascheduler) calls configure_logger with timestamp=True."""
    from yascheduler.entrypoints.cli import daemonize

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemonize.configure_logger",
        lambda *args, **kwargs: captured.update(kwargs) or logging.getLogger(),
    )
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemonize.run_daemon",
        lambda *a, **kw: None,
        raising=False,
    )
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemonize.parse_config",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("asyncio.run", lambda coro: None)

    config_file = tmp_path / "yascheduler.conf"
    config_file.write_text("")
    daemonize.daemonize(["--config", str(config_file), "--log-level", "INFO"])
    assert captured.get("timestamp") is True, (
        f"daemonize should pass timestamp=True; got kwargs={captured!r}"
    )


def test_daemon_sysv_passes_timestamp_true(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """daemon_sysv (file-logging) calls configure_logger with timestamp=True."""
    from yascheduler.entrypoints.cli import daemon_sysv

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemon_sysv.configure_logger",
        lambda *args, **kwargs: captured.update(kwargs) or logging.getLogger(),
    )

    class _FakeDaemonContext:
        def __init__(self, **kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> None:
            pass

    monkeypatch.setattr(daemon_sysv.daemon, "DaemonContext", _FakeDaemonContext)
    monkeypatch.setattr(
        daemon_sysv.pidfile, "TimeoutPIDLockFile", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemon_sysv.run_daemon",
        lambda *a, **kw: None,
        raising=False,
    )
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemon_sysv.parse_config",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("asyncio.run", lambda coro: None)

    config_file = tmp_path / "yascheduler.conf"
    config_file.write_text("")
    daemon_sysv.main(["--config", str(config_file), "--log-level", "INFO"])
    assert captured.get("timestamp") is True, (
        f"daemon_sysv should pass timestamp=True; got kwargs={captured!r}"
    )


def test_daemon_systemd_passes_timestamp_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """daemon_systemd (journald-supervised) calls configure_logger WITHOUT timestamp=True."""
    from yascheduler.entrypoints.cli import daemon_systemd

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemon_systemd.configure_logger",
        lambda *args, **kwargs: captured.update(kwargs) or logging.getLogger(),
    )
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemon_systemd.run_daemon",
        lambda *a, **kw: None,
        raising=False,
    )
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.daemon_systemd.parse_config",
        lambda *a, **kw: None,
    )
    monkeypatch.setattr("asyncio.run", lambda coro: None)

    config_file = tmp_path / "yascheduler.conf"
    config_file.write_text("")
    daemon_systemd.main(["--config", str(config_file), "--log-level", "INFO"])
    assert captured.get("timestamp") in (None, False), (
        f"daemon_systemd should NOT enable timestamp; got kwargs={captured!r}"
    )

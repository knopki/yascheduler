# region MODULE_CONTRACT
# PURPOSE: Unit tests for yascheduler/entrypoints/cli/daemon_common.py — configure_logger and run_daemon with mocked DI (no real DB/SSH).
# SCOPE: configure_logger handler/level/suppression/captureWarnings behavior; run_daemon shape (async, awaits make_daemon + orch.start, owns signal handlers) with mocked make_daemon.
# KEYWORDS: daemon_common, configure_logger, run_daemon, signal handlers
# endregion MODULE_CONTRACT

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from yascheduler.entrypoints.cli import daemon_common
from yascheduler.shared.log import LogFormatter

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    """Snapshot and restore the root logger so handler additions don't leak across tests."""
    root = logging.getLogger()
    original_level = root.level
    original_handlers = list(root.handlers)
    try:
        yield
    finally:
        root.setLevel(original_level)
        root.handlers = list(original_handlers)


def _handler_types(logger: logging.Logger) -> list[type]:
    return [type(h) for h in logger.handlers]


class TestConfigureLogger:
    """configure_logger: handlers, levels, suppression, captureWarnings, no basicConfig."""

    def test_stderr_only_when_log_file_none(self) -> None:
        root = daemon_common.configure_logger(None, logging.INFO)
        types_ = _handler_types(root)
        assert logging.StreamHandler in types_
        assert logging.FileHandler not in types_
        # The StreamHandler streams to stderr.
        sh = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
        assert any(h.stream is sys.stderr for h in sh)
        # The StreamHandler carries a LogFormatter per the reform-grace-logging spec.
        assert any(isinstance(h.formatter, LogFormatter) for h in sh)

    def test_file_and_stderr_when_log_file_set(self, tmp_path: Path) -> None:
        log_path = tmp_path / "y.log"
        root = daemon_common.configure_logger(str(log_path), logging.INFO)
        types_ = _handler_types(root)
        assert logging.StreamHandler in types_
        assert logging.FileHandler in types_
        # A FileHandler pointed at the requested log_path was added (other FileHandlers
        # may exist from pytest's log capturing — filter by baseFilename).
        fh = [
            h
            for h in root.handlers
            if isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", None) == str(log_path)
        ]
        assert len(fh) == 1
        # The StreamHandler streams to stderr.
        sh = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        # Both handlers carry a LogFormatter per the reform-grace-logging spec.
        assert any(isinstance(h.formatter, LogFormatter) for h in sh)
        assert any(isinstance(h.formatter, LogFormatter) for h in fh)

    def test_asyncssh_level_error(self) -> None:
        daemon_common.configure_logger(None, logging.INFO)
        assert logging.getLogger("asyncssh").level == logging.ERROR

    def test_capture_warnings_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = MagicMock()
        monkeypatch.setattr(logging, "captureWarnings", spy)
        daemon_common.configure_logger(None, logging.INFO)
        spy.assert_called_once_with(True)

    def test_basic_config_not_called(self, monkeypatch: pytest.MonkeyPatch) -> None:
        spy = MagicMock()
        monkeypatch.setattr(logging, "basicConfig", spy)
        daemon_common.configure_logger(None, logging.INFO)
        spy.assert_not_called()

    def test_root_level_set(self) -> None:
        root = daemon_common.configure_logger(None, logging.DEBUG)
        assert root.level == logging.DEBUG


class TestRunDaemonShape:
    """run_daemon: async, awaits make_daemon + orch.start, owns signal handlers."""

    def test_run_daemon_is_async_def(self) -> None:
        assert inspect.iscoroutinefunction(daemon_common.run_daemon)

    def test_run_daemon_awaits_make_daemon_and_orch_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        orch = MagicMock()
        orch.start = AsyncMock()
        orch.stop = AsyncMock()

        make_daemon_mock = AsyncMock(return_value=orch)
        monkeypatch.setattr(daemon_common, "make_daemon", make_daemon_mock)

        config = MagicMock()
        logger = logging.getLogger("test-run-daemon")

        asyncio.run(daemon_common.run_daemon(config, logger))

        make_daemon_mock.assert_awaited_once_with(config)
        orch.start.assert_awaited_once()

    def test_run_daemon_owns_signal_handlers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The signal handlers are registered on the running loop inside run_daemon;
        # verify by spying on loop.add_signal_handler.
        orch = MagicMock()
        orch.start = AsyncMock()
        orch.stop = AsyncMock()
        monkeypatch.setattr(daemon_common, "make_daemon", AsyncMock(return_value=orch))

        registered: list = []

        async def _drive() -> None:
            loop = asyncio.get_running_loop()

            def fake_add_signal_handler(
                sig: object,
                handler: object,
                *args: object,
            ) -> None:
                registered.append((sig, handler))

            # Bypass the strict asyncio type stub by going through object.__setattr__.
            object.__setattr__(loop, "add_signal_handler", fake_add_signal_handler)
            await daemon_common.run_daemon(MagicMock(), logging.getLogger("t"))

        asyncio.run(_drive())

        # SIGTERM and SIGINT registered (signal numbers may differ by platform but the
        # constants are importable).
        import signal as _signal

        sigs = [sig for sig, _ in registered]
        assert _signal.SIGTERM in sigs
        assert _signal.SIGINT in sigs

    def test_each_signal_handler_dispatches_its_own_signal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: the signal-handler closure must bind `sig` by value, not by
        reference. A bare closure over the loop variable would dispatch SIGINT for
        both signals (the loop's final value). Verify each handler produces a task
        whose wrapped coroutine carries the CORRECT signal.
        """
        import signal as _signal

        orch = MagicMock()
        orch.start = AsyncMock()
        orch.stop = AsyncMock()
        monkeypatch.setattr(daemon_common, "make_daemon", AsyncMock(return_value=orch))

        registered: dict = {}

        async def _drive() -> None:
            loop = asyncio.get_running_loop()

            def fake_add_signal_handler(
                sig: object,
                handler: object,
                *args: object,
            ) -> None:
                registered[_signal.Signals(sig)] = handler

            object.__setattr__(loop, "add_signal_handler", fake_add_signal_handler)
            await daemon_common.run_daemon(MagicMock(), logging.getLogger("t"))

        asyncio.run(_drive())

        # Each handler is a zero-arg callable that creates a task wrapping on_signal.
        # Inspect the on_signal call's `sig` argument via the closure cells.
        for sig, handler in registered.items():
            # The handler closure captures `on_signal`, `orch`, `shielded`, and `sig`.
            # The created task wraps `on_signal(orch, shielded, sig)`. We verify the
            # `sig` cell holds the same value as the registration key (not the loop's
            # final value).
            # Easiest robust check: call the handler and inspect the produced coroutine's
            # cr_frame locals is fragile; instead verify the closure cell for `sig`.
            closure = handler.__closure__
            assert closure is not None, "handler must be a closure"
            # Find the cell whose contents equals `sig` — the factory binds it by value.
            cell_values = [c.cell_contents for c in closure]
            assert sig in cell_values, (
                f"handler for {sig.name} did not bind sig by value; "
                f"closure holds {cell_values}"
            )

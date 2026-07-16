# region MODULE_CONTRACT
# PURPOSE: Unit tests for yascheduler/entrypoints/cli/daemonize.py — argparse, exit codes, argv injection, runtime-error path with mocked daemon core.
# SCOPE: daemonize() argparse behavior (--help/--bogus/--config/--log-level/--log-file defaults, -l short alias) and the runtime-error → exit 1 path; make_daemon mocked, no real DB/SSH.
# KEYWORDS: daemonize, argparse, argv injection, runtime error
# endregion MODULE_CONTRACT

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from yascheduler.entrypoints.cli import daemonize as daemonize_mod

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

pytestmark = pytest.mark.unit


def _run(argv: list[str]) -> None:
    daemonize_mod.daemonize(argv)


class TestDaemonizeParsing:
    """argparse: --help prog=yascheduler, --bogus exit 2, --config missing exit 2, defaults."""

    def test_help_exits_zero_prog_yascheduler(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "usage: yascheduler" in out
        assert "--config" in out
        assert "--log-level" in out
        assert "-l" in out  # -l short alias for --log-level is now listed
        assert "--log-file" in out

    def test_log_level_short_alias_parses(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # `yascheduler -l DEBUG` MUST work (pre-refactor backward compatibility).
        cfg_logger_spy = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(daemonize_mod, "configure_logger", cfg_logger_spy)
        monkeypatch.setattr(
            daemonize_mod,
            "parse_config",
            MagicMock(return_value=MagicMock()),
        )

        def fake_run(coro: Coroutine) -> None:
            coro.close()

        monkeypatch.setattr(daemonize_mod.asyncio, "run", fake_run)
        _run(["-l", "DEBUG"])
        # configure_logger's second arg is logging.getLevelName("DEBUG") == logging.DEBUG.
        assert cfg_logger_spy.call_args.args[1] == logging.getLevelName("DEBUG")

    def test_bogus_flag_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--bogus"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()

    def test_missing_config_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--config", "/nonexistent.conf"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert "not a file" in err
        assert "/nonexistent.conf" in err

    def test_default_log_file_is_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Spy on configure_logger to capture the log_file argument (default None).
        cfg_logger_spy = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(daemonize_mod, "configure_logger", cfg_logger_spy)
        monkeypatch.setattr(
            daemonize_mod,
            "parse_config",
            MagicMock(return_value=MagicMock()),
        )

        def fake_run(coro: Coroutine) -> None:
            # Close the coroutine without running to avoid RuntimeWarning.
            coro.close()

        monkeypatch.setattr(daemonize_mod.asyncio, "run", fake_run)
        _run([])
        assert cfg_logger_spy.called
        assert cfg_logger_spy.call_args.args[0] is None  # log_file default None

    def test_default_log_level_is_info(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg_logger_spy = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(daemonize_mod, "configure_logger", cfg_logger_spy)
        monkeypatch.setattr(
            daemonize_mod,
            "parse_config",
            MagicMock(return_value=MagicMock()),
        )

        def fake_run(coro: Coroutine) -> None:
            coro.close()

        monkeypatch.setattr(daemonize_mod.asyncio, "run", fake_run)
        _run([])
        # Second positional arg is logging.getLevelName("INFO") == logging.INFO.
        assert cfg_logger_spy.call_args.args[1] == logging.getLevelName("INFO")


class TestDaemonizeRuntime:
    """Runtime: make_daemon raising → exit 1 with Error:; argv injection."""

    def test_runtime_error_exits_one_with_error_message(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            daemonize_mod,
            "configure_logger",
            MagicMock(return_value=MagicMock()),
        )
        monkeypatch.setattr(
            daemonize_mod,
            "parse_config",
            MagicMock(side_effect=RuntimeError("db connection refused")),
        )

        with pytest.raises(SystemExit) as exc:
            _run([])
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error:" in err
        assert "db connection refused" in err

    def test_argv_injection_reads_explicit_argv_not_sys_argv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Set sys.argv to something unrelated to prove argv wins.
        monkeypatch.setattr("sys.argv", ["python", "-c", "unrelated"])
        cfg = tmp_path / "yascheduler.conf"
        cfg.write_text("[local]")
        cfg_spy = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(daemonize_mod, "parse_config", cfg_spy)
        monkeypatch.setattr(
            daemonize_mod,
            "configure_logger",
            MagicMock(return_value=MagicMock()),
        )

        def fake_run(coro: Coroutine) -> None:
            coro.close()

        monkeypatch.setattr(daemonize_mod.asyncio, "run", fake_run)
        _run(["--config", str(cfg)])
        cfg_spy.assert_called_once_with(cfg)

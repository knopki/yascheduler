# FILE: tests/unit/test_cli_daemonize.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yascheduler/entrypoints/cli/daemonize.py — argparse, exit codes, argv injection, runtime-error path with mocked daemon core.
#   SCOPE: daemonize() argparse behavior (--help/--bogus/--config/--log-level/--log-file defaults) and the runtime-error → exit 1 path; make_daemon mocked, no real DB/SSH.
#   DEPENDS: M-CLI-COMMANDS
#   LINKS: M-CLI-COMMANDS, M-DAEMON-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestDaemonizeParsing - --help exit 0 (prog=yascheduler), --bogus exit 2, --config /nonexistent exit 2, defaults
#   TestDaemonizeRuntime - make_daemon raising → exit 1 with Error: on stderr; argv injection
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial tests for relocated daemonize (consolidate-daemon-entrypoints).
# END_CHANGE_SUMMARY

from __future__ import annotations

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
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run(["--help"])
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "usage: yascheduler" in out
        assert "--config" in out
        assert "--log-level" in out
        assert "--log-file" in out

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
        import logging

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
            daemonize_mod, "configure_logger", MagicMock(return_value=MagicMock())
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
            daemonize_mod, "configure_logger", MagicMock(return_value=MagicMock())
        )

        def fake_run(coro: Coroutine) -> None:
            coro.close()

        monkeypatch.setattr(daemonize_mod.asyncio, "run", fake_run)
        _run(["--config", str(cfg)])
        cfg_spy.assert_called_once_with(cfg)

# FILE: tests/unit/test_cli_daemon_systemd.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yascheduler/entrypoints/cli/daemon_systemd.py — argparse and defaults.
#   SCOPE: main() argparse behavior (--help exit 0, default --log-file None for journald, default --log-level INFO) with mocked daemon core.
#   DEPENDS: M-DAEMON-SYSTEMD
#   LINKS: M-DAEMON-SYSTEMD, M-DAEMON-COMMON
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestDaemonSystemdParsing - --help exit 0 prog=yascheduler; default --log-file None; default --log-level INFO
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial tests for relocated daemon_systemd (consolidate-daemon-entrypoints).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from yascheduler.entrypoints.cli import daemon_systemd as systemd_mod

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

pytestmark = pytest.mark.unit


def _run(argv: list[str]) -> None:
    systemd_mod.main(argv)


class TestDaemonSystemdParsing:
    """--help exit 0 (prog=yascheduler); default --log-file None (journald); default --log-level INFO."""

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
        tmp_path: Path,
    ) -> None:
        cfg = tmp_path / "yascheduler.conf"
        cfg.write_text("[local]")
        cfg_logger_spy = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(systemd_mod, "configure_logger", cfg_logger_spy)
        monkeypatch.setattr(
            systemd_mod.Config,
            "from_config_parser",
            MagicMock(return_value=MagicMock()),
        )

        def fake_run(coro: Coroutine) -> None:
            coro.close()

        monkeypatch.setattr(systemd_mod.asyncio, "run", fake_run)
        _run(["--config", str(cfg)])
        assert cfg_logger_spy.call_args.args[0] is None  # journald default

    def test_default_log_level_is_info(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import logging

        cfg = tmp_path / "yascheduler.conf"
        cfg.write_text("[local]")
        cfg_logger_spy = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(systemd_mod, "configure_logger", cfg_logger_spy)
        monkeypatch.setattr(
            systemd_mod.Config,
            "from_config_parser",
            MagicMock(return_value=MagicMock()),
        )

        def fake_run(coro: Coroutine) -> None:
            coro.close()

        monkeypatch.setattr(systemd_mod.asyncio, "run", fake_run)
        _run(["--config", str(cfg)])
        assert cfg_logger_spy.call_args.args[1] == logging.getLevelName("INFO")

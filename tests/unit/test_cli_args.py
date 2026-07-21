# region MODULE_CONTRACT
# PURPOSE: Unit tests for yascheduler/entrypoints/cli/args.py — existing_path validator and the three add_*_arg helpers.
# SCOPE: existing_path validator and the three add_*_arg helpers with a real ArgumentParser; no DB/SSH/config.
# KEYWORDS: existing_path, ArgumentParser, CLI arg helpers
# endregion MODULE_CONTRACT

from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from yascheduler import CONFIG_FILE
from yascheduler.entrypoints.cli.args import (
    LOG_LEVEL_CHOICES,
    add_config_arg,
    add_log_file_arg,
    add_log_level_arg,
    existing_path,
)

pytestmark = pytest.mark.unit


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="test-prog")


class TestExistingPath:
    """existing_path: returns Path for an existing file, raises for missing."""

    def test_returns_path_for_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "real.txt"
        f.write_text("x")
        result = existing_path(str(f))
        assert result == f

    def test_raises_argument_type_error_for_missing_file(self) -> None:
        with pytest.raises(argparse.ArgumentTypeError) as exc:
            existing_path("/nonexistent/path/to/file.conf")
        assert "not a file" in str(exc.value)
        assert "/nonexistent/path/to/file.conf" in str(exc.value)


class TestAddConfigArg:
    """add_config_arg: default=CONFIG_FILE, type=existing_path → exit 2 on missing."""

    def test_default_is_config_file(self) -> None:
        parser = _parser()
        add_config_arg(parser)
        args = parser.parse_args([])
        # Default is wrapped in Path so argparse doesn't validate it (3.13+);
        # the resolved path equals CONFIG_FILE.
        assert str(args.config) == str(CONFIG_FILE)

    def test_missing_config_exits_two(self, capsys: pytest.CaptureFixture[str]) -> None:
        parser = _parser()
        add_config_arg(parser)
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--config", "/nonexistent.conf"])
        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert "not a file" in err
        assert "/nonexistent.conf" in err

    def test_custom_config_passed_through(self, tmp_path: Path) -> None:
        f = tmp_path / "custom.conf"
        f.write_text("[local]")
        parser = _parser()
        add_config_arg(parser)
        args = parser.parse_args(["--config", str(f)])
        assert args.config == f

    def test_custom_dest(self) -> None:
        parser = _parser()
        add_config_arg(parser, dest="cfg")
        args = parser.parse_args([])
        assert str(args.cfg) == str(CONFIG_FILE)
        assert not hasattr(args, "config")


class TestAddLogLevelArg:
    """add_log_level_arg: explicit choices, rejects WARN, getLevelName resolves."""

    def test_default_is_warning(self) -> None:
        parser = _parser()
        add_log_level_arg(parser)
        args = parser.parse_args([])
        assert args.log_level == "WARNING"

    def test_warn_alias_rejected(self, capsys: pytest.CaptureFixture[str]) -> None:
        parser = _parser()
        add_log_level_arg(parser)
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["--log-level", "WARN"])
        assert exc.value.code == 2

    def test_all_choices_accepted(self) -> None:
        parser = _parser()
        add_log_level_arg(parser)
        for level in LOG_LEVEL_CHOICES:
            args = parser.parse_args(["--log-level", level])
            assert args.log_level == level

    def test_get_level_name_resolves_to_int(self) -> None:
        # The spec requires resolution via logging.getLevelName (not _nameToLevel).
        for level in LOG_LEVEL_CHOICES:
            assert isinstance(logging.getLevelName(level), int)
        assert logging.getLevelName("WARNING") == logging.WARNING == 30

    def test_custom_default(self) -> None:
        parser = _parser()
        add_log_level_arg(parser, default="INFO")
        args = parser.parse_args([])
        assert args.log_level == "INFO"

    def test_long_only_by_default_rejects_short_l(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Without `short`, only --log-level is registered; -l is unrecognized.
        parser = _parser()
        add_log_level_arg(parser)
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["-l", "DEBUG"])
        assert exc.value.code == 2

    def test_short_alias_registers_minus_l(self) -> None:
        parser = _parser()
        add_log_level_arg(parser, short="-l")
        # Both the short and long forms resolve to the same dest.
        assert parser.parse_args(["-l", "DEBUG"]).log_level == "DEBUG"
        assert parser.parse_args(["--log-level", "DEBUG"]).log_level == "DEBUG"

    def test_short_alias_honors_choices(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # The short alias MUST reject invalid choices just like --log-level.
        parser = _parser()
        add_log_level_arg(parser, short="-l")
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(["-l", "WARN"])
        assert exc.value.code == 2


class TestAddLogFileArg:
    """add_log_file_arg: default None (stderr), custom default honored."""

    def test_default_is_none(self) -> None:
        parser = _parser()
        add_log_file_arg(parser)
        args = parser.parse_args([])
        assert args.log_file is None

    def test_custom_default(self) -> None:
        parser = _parser()
        add_log_file_arg(parser, default="/var/log/yascheduler.log")
        args = parser.parse_args([])
        assert args.log_file == "/var/log/yascheduler.log"

    def test_explicit_value_passed_through(self) -> None:
        parser = _parser()
        add_log_file_arg(parser)
        args = parser.parse_args(["--log-file", "/tmp/y.log"])
        assert args.log_file == "/tmp/y.log"

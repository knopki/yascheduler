# FILE: tests/unit/test_cli_init.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for yainit init() flag parsing, dispatch, exit codes, and service overwrite behavior.
#   SCOPE: init() and its helpers with mocked apply_schema + filesystem.
#   DEPENDS: M-ENTRYPOINTS-CLI-INIT
#   LINKS: M-ENTRYPOINTS-CLI-INIT
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TestInitFlags - Flag parsing and dispatch (no flags, --schema, --daemon, both, --help, --bogus)
#   TestInitErrors - Exit-code contract on DatabaseError and OSError
#   TestServiceInstall - Service file overwrite and detection logic
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.0 - Initial unit tests for relocated yainit (entrypoints/cli/init.py) in relocate-init-command.
# END_CHANGE_SUMMARY

"""Unit tests for yainit (entrypoints/cli/init.py).

Covers flag parsing, dispatch, exit codes (0/1/2), service overwrite, and
systemd-vs-sysv detection. apply_schema and the service helpers are mocked
or injected via the public unit_file/startup_file parameters.
"""

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pg8000 import DatabaseError

from yascheduler.entrypoints.cli.init import _init_systemd, _init_sysv, init

pytestmark = pytest.mark.unit


@pytest.fixture
def install_path() -> Path:
    """Real yascheduler/ package root — same as init() computes."""
    return Path(__file__).resolve().parent.parent.parent / "yascheduler"


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid touching the real CONFIG_FILE: stub Config.from_config_parser."""
    monkeypatch.setattr(
        "yascheduler.entrypoints.cli.init.Config.from_config_parser",
        MagicMock(return_value=MagicMock(db=MagicMock())),
    )


class TestInitFlags:
    """Flag parsing and dispatch (tasks 9.3-9.8)."""

    def test_no_flags_runs_both(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No flags → both service install and apply_schema run; exit 0."""
        systemd_mock = MagicMock()
        sysv_mock = MagicMock()
        apply_mock = MagicMock()
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init._init_systemd", systemd_mock
        )
        monkeypatch.setattr("yascheduler.entrypoints.cli.init._init_sysv", sysv_mock)
        monkeypatch.setattr("yascheduler.entrypoints.cli.init.apply_schema", apply_mock)
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init.Path.is_dir", lambda self: True
        )

        with pytest.raises(SystemExit) as exc:
            init([])

        assert exc.value.code == 0
        assert systemd_mock.call_count == 1
        assert sysv_mock.call_count == 0
        assert apply_mock.call_count == 1

    def test_schema_only_skips_service(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--schema → apply_schema called, service install NOT called; exit 0."""
        systemd_mock = MagicMock()
        sysv_mock = MagicMock()
        apply_mock = MagicMock()
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init._init_systemd", systemd_mock
        )
        monkeypatch.setattr("yascheduler.entrypoints.cli.init._init_sysv", sysv_mock)
        monkeypatch.setattr("yascheduler.entrypoints.cli.init.apply_schema", apply_mock)

        with pytest.raises(SystemExit) as exc:
            init(["--schema"])

        assert exc.value.code == 0
        assert systemd_mock.call_count == 0
        assert sysv_mock.call_count == 0
        assert apply_mock.call_count == 1

    def test_daemon_only_skips_schema(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--daemon → service install called, apply_schema NOT called; exit 0."""
        systemd_mock = MagicMock()
        sysv_mock = MagicMock()
        apply_mock = MagicMock()
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init._init_systemd", systemd_mock
        )
        monkeypatch.setattr("yascheduler.entrypoints.cli.init._init_sysv", sysv_mock)
        monkeypatch.setattr("yascheduler.entrypoints.cli.init.apply_schema", apply_mock)
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init.Path.is_dir", lambda self: True
        )

        with pytest.raises(SystemExit) as exc:
            init(["--daemon"])

        assert exc.value.code == 0
        assert systemd_mock.call_count == 1
        assert sysv_mock.call_count == 0
        assert apply_mock.call_count == 0

    def test_both_flags_runs_both(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--schema --daemon → both run (equivalent to no-flags default); exit 0."""
        systemd_mock = MagicMock()
        sysv_mock = MagicMock()
        apply_mock = MagicMock()
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init._init_systemd", systemd_mock
        )
        monkeypatch.setattr("yascheduler.entrypoints.cli.init._init_sysv", sysv_mock)
        monkeypatch.setattr("yascheduler.entrypoints.cli.init.apply_schema", apply_mock)
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init.Path.is_dir", lambda self: True
        )

        with pytest.raises(SystemExit) as exc:
            init(["--schema", "--daemon"])

        assert exc.value.code == 0
        assert systemd_mock.call_count == 1
        assert sysv_mock.call_count == 0
        assert apply_mock.call_count == 1

    def test_help_exits_zero(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--help → argparse prints usage mentioning --schema and --daemon; exit 0."""
        with pytest.raises(SystemExit) as exc:
            init(["--help"])

        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "--schema" in out
        assert "--daemon" in out

    def test_unknown_flag_exits_two(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--bogus → argparse usage error on stderr; exit 2."""
        with pytest.raises(SystemExit) as exc:
            init(["--bogus"])

        assert exc.value.code == 2
        _, err = capsys.readouterr()
        assert err.strip()  # argparse prints a usage error


class TestInitErrors:
    """Exit-code contract on DatabaseError and OSError (tasks 9.9-9.10, 9.13)."""

    def test_database_error_exits_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """DatabaseError from apply_schema → init prints error, exits 1."""
        apply_mock = MagicMock(side_effect=DatabaseError("connection refused"))
        monkeypatch.setattr("yascheduler.entrypoints.cli.init.apply_schema", apply_mock)

        with pytest.raises(SystemExit) as exc:
            init(["--schema"])

        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "Error" in err

    def test_service_write_oserror_exits_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """OSError writing service file → init prints 'Error: cannot write to'; exit 1."""
        # Force systemd path and make write_text raise OSError
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init.Path.is_dir", lambda self: True
        )
        with patch(
            "yascheduler.entrypoints.cli.init.Path.write_text",
            side_effect=OSError("Permission denied"),
        ):
            with pytest.raises(SystemExit) as exc:
                init(["--daemon"])

        assert exc.value.code == 1
        out, err = capsys.readouterr()
        combined = out + err
        assert "Error: cannot write to" in combined


class TestServiceInstall:
    """Service file overwrite, missing parent, and detection (tasks 9.11-9.15)."""

    def test_overwrites_existing_systemd_unit(
        self,
        install_path: Path,
        tmp_path: Path,
    ) -> None:
        """_init_systemd overwrites an existing unit file with the fresh template."""
        unit_file = tmp_path / "yascheduler.service"
        unit_file.write_text("STALE CONTENT\n")

        _init_systemd(install_path, unit_file=unit_file)

        content = unit_file.read_text("utf-8")
        assert "STALE CONTENT" not in content
        assert "%YASCHEDULER_DAEMON_FILE%" not in content
        assert "daemon_systemd.py" in content

    def test_overwrites_existing_sysv_script(
        self,
        install_path: Path,
        tmp_path: Path,
    ) -> None:
        """_init_sysv overwrites an existing init script and applies chmod 0755."""
        startup_file = tmp_path / "yascheduler"
        startup_file.write_text("STALE CONTENT\n")

        _init_sysv(install_path, startup_file=startup_file)

        content = startup_file.read_text("utf-8")
        assert "STALE CONTENT" not in content
        assert "%YASCHEDULER_DAEMON_FILE%" not in content
        assert "daemon_sysv.py" in content
        mode = stat.S_IMODE(os.stat(startup_file).st_mode)
        assert mode == 0o755

    def test_missing_parent_dir_exits_one(
        self,
        install_path: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Missing parent dir → write_text raises OSError → exit 1 with message."""
        unit_file = tmp_path / "nonexistent_dir" / "yascheduler.service"

        with pytest.raises(SystemExit) as exc:
            _init_systemd(install_path, unit_file=unit_file)

        assert exc.value.code == 1
        out, _ = capsys.readouterr()
        assert "Error: cannot write to" in out

    def test_systemd_detection_via_run_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """/run/systemd/system exists → _init_systemd called, _init_sysv not."""
        systemd_mock = MagicMock()
        sysv_mock = MagicMock()
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init._init_systemd", systemd_mock
        )
        monkeypatch.setattr("yascheduler.entrypoints.cli.init._init_sysv", sysv_mock)
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init.Path.is_dir", lambda self: True
        )

        with pytest.raises(SystemExit) as exc:
            init(["--daemon"])

        assert exc.value.code == 0
        assert systemd_mock.call_count == 1
        assert sysv_mock.call_count == 0

    def test_non_systemd_detection(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """/run/systemd/system absent → _init_sysv called, _init_systemd not."""
        systemd_mock = MagicMock()
        sysv_mock = MagicMock()
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init._init_systemd", systemd_mock
        )
        monkeypatch.setattr("yascheduler.entrypoints.cli.init._init_sysv", sysv_mock)
        monkeypatch.setattr(
            "yascheduler.entrypoints.cli.init.Path.is_dir", lambda self: False
        )

        with pytest.raises(SystemExit) as exc:
            init(["--daemon"])

        assert exc.value.code == 0
        assert systemd_mock.call_count == 0
        assert sysv_mock.call_count == 1

    def test_schema_idempotent_rerun(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Re-running --schema twice succeeds both times (schema.sql idempotency)."""
        apply_mock = MagicMock()
        monkeypatch.setattr("yascheduler.entrypoints.cli.init.apply_schema", apply_mock)

        for _ in range(2):
            with pytest.raises(SystemExit) as exc:
                init(["--schema"])
            assert exc.value.code == 0

        assert apply_mock.call_count == 2

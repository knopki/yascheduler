# region MODULE_CONTRACT
# PURPOSE: Unit tests for MyPureWindowsPath leading-backslash normalization across pathlib APIs (<=3.11 _parse_args, 3.12+ _parse_path).
# SCOPE: str() round-trip of MyPureWindowsPath for the SFTP leading-\ case, plain drive paths, UNC, and drive-less absolute paths.
# KEYWORDS: MyPureWindowsPath, windows path, leading backslash, pathlib version
# endregion MODULE_CONTRACT

import pytest

from yascheduler.infra.ssh.platform.windows import MyPureWindowsPath

pytestmark = pytest.mark.unit


def test_leading_backslash_before_drive_is_normalized() -> None:
    """asyncssh SFTP realpath returns a leading \\ before the drive; it must be dropped."""
    assert str(MyPureWindowsPath(r"\C:\Users\user")) == "C:\\Users\\user"


def test_plain_drive_path_unchanged() -> None:
    assert str(MyPureWindowsPath("C:\\Users\\user")) == "C:\\Users\\user"


def test_unc_path_preserved() -> None:
    assert str(MyPureWindowsPath("\\\\server\\share\\dir")) == "\\\\server\\share\\dir"


def test_drive_less_absolute_preserved() -> None:
    """r"\\Users\\user" (absolute from current drive, no drive letter) must stay intact."""
    assert str(MyPureWindowsPath(r"\Users\user")) == "\\Users\\user"

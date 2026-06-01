# FILE: tests/unit/test_checks.py
# VERSION: 1.0.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Unit tests for OS check functions in yascheduler.remote_machine.checks.
#   SCOPE: check_is_linux, check_is_debian_like, check_is_debian, check_is_debian_11, check_is_windows, check_is_windows10.
#   DEPENDS: M-REMOTE-CHECKS, M-PLATFORM-CHECKS
#   LINKS: M-REMOTE-CHECKS, M-PLATFORM-CHECKS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   test_check_is_linux_true — check_is_linux returns True when uname returns Linux
#   test_check_is_linux_darwin — check_is_linux returns False when uname returns Darwin
#   test_check_is_linux_nonzero_returncode — check_is_linux returns False when returncode is non-zero
#   test_check_is_debian_like_true — check_is_debian_like returns True when ID_LIKE contains debian
#   test_check_is_debian_true — check_is_debian returns True when ID is debian
#   test_check_is_debian_false_for_ubuntu — check_is_debian returns False when ID is ubuntu
#   test_check_is_debian_version_match — check_is_debian_11 returns True when version matches
#   test_check_is_debian_version_mismatch — check_is_debian_11 returns False when version differs
#   test_check_is_windows_true — check_is_windows returns True when PowerShell OSVersion succeeds
#   test_check_is_windows_false — check_is_windows returns False when PowerShell OSVersion fails
#   test_check_is_windows_version_match — check_is_windows10 returns True when caption contains version
#   test_check_is_windows_version_mismatch — check_is_windows10 returns False when caption lacks version
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Removed task-number comments, added MODULE_MAP, added version-specific check tests.
#   PREVIOUS_CHANGE: v1.0.0 - Initial unit tests for OS check functions.
# END_CHANGE_SUMMARY

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from yascheduler.remote_machine.checks import (
    check_is_debian,
    check_is_debian_11,
    check_is_debian_like,
    check_is_linux,
    check_is_windows,
    check_is_windows10,
)


# START_CONTRACT: test_check_is_linux_true
#   PURPOSE: Verifies check_is_linux returns True when uname returns Linux
#   INPUTS: { None - mock SSH connection }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_linux_true
@pytest.mark.asyncio
async def test_check_is_linux_true() -> None:
    """check_is_linux returns True when uname returns Linux"""
    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=MagicMock(returncode=0, stdout="Linux\n"))
    assert await check_is_linux(mock_conn) is True


# START_CONTRACT: test_check_is_linux_darwin
#   PURPOSE: Verifies check_is_linux returns False when uname returns Darwin
#   INPUTS: { None - mock SSH connection }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_linux_darwin
@pytest.mark.asyncio
async def test_check_is_linux_darwin() -> None:
    """check_is_linux returns False when uname returns Darwin"""
    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=MagicMock(returncode=0, stdout="Darwin\n"))
    assert await check_is_linux(mock_conn) is False


# START_CONTRACT: test_check_is_linux_nonzero_returncode
#   PURPOSE: Verifies check_is_linux returns False on non-zero returncode
#   INPUTS: { None - mock SSH connection }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_linux_nonzero_returncode
@pytest.mark.asyncio
async def test_check_is_linux_nonzero_returncode() -> None:
    """check_is_linux returns False when returncode is non-zero"""
    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=MagicMock(returncode=1, stdout="Linux\n"))
    assert await check_is_linux(mock_conn) is False


# START_CONTRACT: test_check_is_debian_like_true
#   PURPOSE: Verifies check_is_debian_like returns True when ID_LIKE contains debian
#   INPUTS: { None - mock _get_os_release }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_debian_like_true
@pytest.mark.asyncio
async def test_check_is_debian_like_true() -> None:
    """check_is_debian_like returns True when ID_LIKE contains debian"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks._get_os_release",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = ("debian", "debian-like", "11")
        assert await check_is_debian_like(mock_conn) is True


# START_CONTRACT: test_check_is_debian_true
#   PURPOSE: Verifies check_is_debian returns True when ID is debian
#   INPUTS: { None - mock _get_os_release }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_debian_true
@pytest.mark.asyncio
async def test_check_is_debian_true() -> None:
    """check_is_debian returns True when ID is debian"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks._get_os_release",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = ("debian", "debian-like", "11")
        assert await check_is_debian(mock_conn) is True


# START_CONTRACT: test_check_is_debian_false_for_ubuntu
#   PURPOSE: Verifies check_is_debian returns False when ID is ubuntu
#   INPUTS: { None - mock _get_os_release }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_debian_false_for_ubuntu
@pytest.mark.asyncio
async def test_check_is_debian_false_for_ubuntu() -> None:
    """check_is_debian returns False when ID is ubuntu"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks._get_os_release",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = ("ubuntu", "debian", "22.04")
        assert await check_is_debian(mock_conn) is False


# START_CONTRACT: test_check_is_debian_version_match
#   PURPOSE: Verifies check_is_debian_11 returns True when version matches
#   INPUTS: { None - mock _get_os_release }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_debian_version_match
@pytest.mark.asyncio
async def test_check_is_debian_version_match() -> None:
    """check_is_debian_11 returns True when version matches"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks._get_os_release",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = ("debian", "debian-like", "11")
        assert await check_is_debian_11(mock_conn) is True


# START_CONTRACT: test_check_is_debian_version_mismatch
#   PURPOSE: Verifies check_is_debian_11 returns False when version differs
#   INPUTS: { None - mock _get_os_release }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_debian_version_mismatch
@pytest.mark.asyncio
async def test_check_is_debian_version_mismatch() -> None:
    """check_is_debian_11 returns False when version differs"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks._get_os_release",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = ("debian", "debian-like", "12")
        assert await check_is_debian_11(mock_conn) is False


# START_CONTRACT: test_check_is_windows_true
#   PURPOSE: Verifies check_is_windows returns True when PowerShell succeeds
#   INPUTS: { None - mock SSH connection }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_windows_true
@pytest.mark.asyncio
async def test_check_is_windows_true() -> None:
    """check_is_windows returns True when PowerShell OSVersion succeeds"""
    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=MagicMock(returncode=0))
    assert await check_is_windows(mock_conn) is True


# START_CONTRACT: test_check_is_windows_false
#   PURPOSE: Verifies check_is_windows returns False when PowerShell fails
#   INPUTS: { None - mock SSH connection }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_windows_false
@pytest.mark.asyncio
async def test_check_is_windows_false() -> None:
    """check_is_windows returns False when PowerShell OSVersion fails"""
    mock_conn = AsyncMock()
    mock_conn.run = AsyncMock(return_value=MagicMock(returncode=1))
    assert await check_is_windows(mock_conn) is False


# START_CONTRACT: test_check_is_windows_version_match
#   PURPOSE: Verifies check_is_windows10 returns True when caption contains version
#   INPUTS: { None - mock get_wmi_w32_os_caption }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_windows_version_match
@pytest.mark.asyncio
async def test_check_is_windows_version_match() -> None:
    """check_is_windows10 returns True when caption contains version"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks.get_wmi_w32_os_caption",
        new_callable=AsyncMock,
    ) as mock_caption:
        mock_caption.return_value = "Microsoft Windows 10 Pro"
        assert await check_is_windows10(mock_conn) is True


# START_CONTRACT: test_check_is_windows_version_mismatch
#   PURPOSE: Verifies check_is_windows10 returns False when caption lacks version
#   INPUTS: { None - mock get_wmi_w32_os_caption }
#   OUTPUTS: { None - assertion on bool result }
# END_CONTRACT: test_check_is_windows_version_mismatch
@pytest.mark.asyncio
async def test_check_is_windows_version_mismatch() -> None:
    """check_is_windows10 returns False when caption lacks version"""
    mock_conn = MagicMock()
    with patch(
        "yascheduler.adapters.ssh.platform.checks.get_wmi_w32_os_caption",
        new_callable=AsyncMock,
    ) as mock_caption:
        mock_caption.return_value = "Microsoft Windows 11 Pro"
        assert await check_is_windows10(mock_conn) is False

"""SSH-based platform detection check functions for each supported OS."""
# region MODULE_CONTRACT
# PURPOSE: Platform check functions for Debian, Linux, Darwin, Windows variants — invoked via SSHClientConnection.
# SCOPE:
# - Linux/Darwin detection: uname-based
# - Debian detection: os-release-based (ID, ID_LIKE, VERSION_ID)
# - Windows detection: PowerShell OSVersion and WMI Win32_OperatingSystem.Caption
# DEPENDENCIES: USES API: asyncssh (SSHClientConnection.run), asyncstdlib (lru_cache)
# KEYWORDS: checks, platform detection, os, linux, debian, windows, darwin
# endregion MODULE_CONTRACT

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, cast

from asyncstdlib import lru_cache

if TYPE_CHECKING:
    from asyncssh.connection import SSHClientConnection

__all__ = [
    "check_is_darwin",
    "check_is_debian",
    "check_is_debian_10",
    "check_is_debian_11",
    "check_is_debian_12",
    "check_is_debian_13",
    "check_is_debian_14",
    "check_is_debian_15",
    "check_is_debian_like",
    "check_is_linux",
    "check_is_windows",
    "check_is_windows7",
    "check_is_windows8",
    "check_is_windows10",
    "check_is_windows11",
    "check_is_windows12",
    "get_wmi_w32_os_caption",
]


# region FUNC_check_is_linux
# PURPOSE: Check if remote machine runs generic Linux via uname.
@lru_cache
async def check_is_linux(conn: SSHClientConnection) -> bool:
    """Check for generic Linux."""
    proc = await conn.run("uname")
    return (
        proc.returncode == 0
        and proc.stdout is not None
        and proc.stdout.strip() == "Linux"
    )


# endregion FUNC_check_is_linux


# region FUNC_check_is_darwin
# PURPOSE: Check if remote machine runs Darwin/macOS via uname.
@lru_cache
async def check_is_darwin(conn: SSHClientConnection) -> bool:
    """Check for Mac."""
    proc = await conn.run("uname")
    return (
        proc.returncode == 0
        and proc.stdout is not None
        and proc.stdout.strip() == "Darwin"
    )


# endregion FUNC_check_is_darwin


# region FUNC__get_os_release
# PURPOSE: Get os-release fields (ID, ID_LIKE, VERSION_ID) from remote Linux.
@lru_cache
async def _get_os_release(conn: SSHClientConnection) -> tuple[str, ...] | None:
    """Get os release string on linuxes."""
    proc = await conn.run(
        "sh -c 'source /etc/os-release; echo $ID@@@$ID_LIKE@@@$VERSION_ID'",
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return tuple(x.strip() for x in str(proc.stdout).split("@@@", maxsplit=3))


# endregion FUNC__get_os_release


# region FUNC_check_is_debian_like
# PURPOSE: Check if remote is Debian-like via os-release ID/ID_LIKE.
async def check_is_debian_like(conn: SSHClientConnection) -> bool:
    """Check for any Debian-like."""
    os_release = await _get_os_release(conn)
    if not os_release:
        return False
    parts = cast("tuple[str, str, str]", os_release)
    return "debian" in parts[0:2]


# endregion FUNC_check_is_debian_like


# region FUNC_check_is_debian
# PURPOSE: Check if remote is Debian via os-release ID.
async def check_is_debian(conn: SSHClientConnection) -> bool:
    """Check for any Debian."""
    os_release = await _get_os_release(conn)
    return os_release[0] == "debian" if os_release else False


# endregion FUNC_check_is_debian


# region FUNC__check_debian_version
# PURPOSE: Check if remote matches a specific Debian version number.
async def _check_debian_version(version: str, conn: SSHClientConnection) -> bool:
    """Check for Debian version."""
    os_release = await _get_os_release(conn)
    if not os_release:
        return False
    parts = cast("tuple[str, str, str]", os_release)
    min_parts = 3
    return len(parts) >= min_parts and parts[2] == version


# endregion FUNC__check_debian_version


check_is_debian_10 = partial(_check_debian_version, "10")
check_is_debian_11 = partial(_check_debian_version, "11")
check_is_debian_12 = partial(_check_debian_version, "12")
check_is_debian_13 = partial(_check_debian_version, "13")
check_is_debian_14 = partial(_check_debian_version, "14")
check_is_debian_15 = partial(_check_debian_version, "15")


# region FUNC_check_is_windows
# PURPOSE: Check if remote runs Windows via PowerShell OSVersion check.
@lru_cache
async def check_is_windows(conn: SSHClientConnection) -> bool:
    """Check for any Windows with Powershell."""
    proc = await conn.run("[environment]::OSVersion")
    return proc.returncode == 0


# endregion FUNC_check_is_windows


# region FUNC_get_wmi_w32_os_caption
# PURPOSE: Get Windows OS caption via WMI Win32_OperatingSystem.
@lru_cache
async def get_wmi_w32_os_caption(conn: SSHClientConnection) -> str | None:
    """Get OS caption from WMI object."""
    proc = await conn.run("(Get-WmiObject -class Win32_OperatingSystem).Caption")
    if proc.stdout:
        return str(proc.stdout)
    return None


# endregion FUNC_get_wmi_w32_os_caption


# region FUNC__check_is_windows_caption_version
# PURPOSE: Check if remote Windows caption contains a specific version string.
async def _check_is_windows_caption_version(
    version: str,
    conn: SSHClientConnection,
) -> bool:
    """Check for Windows version in caption."""
    caption = await get_wmi_w32_os_caption(conn)
    return version in caption if caption else False


# endregion FUNC__check_is_windows_caption_version


check_is_windows7 = partial(_check_is_windows_caption_version, "7")
check_is_windows8 = partial(_check_is_windows_caption_version, "8")
check_is_windows10 = partial(_check_is_windows_caption_version, "10")
check_is_windows11 = partial(_check_is_windows_caption_version, "11")
check_is_windows12 = partial(_check_is_windows_caption_version, "12")

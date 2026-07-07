#
# FILE: yascheduler/infra/ssh/platform/checks.py
# VERSION: 1.0.1
#
# START_MODULE_CONTRACT
#   PURPOSE: SSH-based platform detection check functions for each supported OS.
#   SCOPE: Platform check functions for Debian, Linux, Darwin, Windows variants.
#   DEPENDS: none
#   LINKS: M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   check_is_linux - Check if remote is generic Linux via uname
#   check_is_darwin - Check if remote is Darwin/macOS via uname
#   check_is_debian_like - Check if remote is Debian-like via os-release
#   check_is_debian - Check if remote is Debian via os-release
#   check_is_debian_10 .. check_is_debian_15 - Partial functions for specific Debian versions
#   check_is_windows - Check if remote runs Windows with PowerShell
#   get_wmi_w32_os_caption - WMI helper to get OS caption string
#   check_is_windows7 .. check_is_windows12 - Partial functions for specific Windows versions
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/; no behavioral change.
#   PREVIOUS_CHANGE: v1.0.0 - Initial version.
# END_CHANGE_SUMMARY
#

"OS checks"

from functools import partial
from typing import Optional, cast

from asyncssh.connection import SSHClientConnection
from asyncstdlib import lru_cache


# START_CONTRACT: check_is_linux
#   PURPOSE: Check if remote machine runs generic Linux via uname
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if remote is Linux }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: check_is_linux
@lru_cache
async def check_is_linux(conn: SSHClientConnection) -> bool:
    "Check for generic Linux"
    proc = await conn.run("uname")
    return (
        proc.returncode == 0
        and proc.stdout is not None
        and proc.stdout.strip() == "Linux"
    )


# START_CONTRACT: check_is_darwin
#   PURPOSE: Check if remote machine runs Darwin/macOS via uname
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if remote is Darwin }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: check_is_darwin
@lru_cache
async def check_is_darwin(conn: SSHClientConnection) -> bool:
    "Check for Mac"
    proc = await conn.run("uname")
    return (
        proc.returncode == 0
        and proc.stdout is not None
        and proc.stdout.strip() == "Darwin"
    )


# START_CONTRACT: _get_os_release
#   PURPOSE: Get os-release fields (ID, ID_LIKE, VERSION_ID) from remote Linux
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { Optional[tuple[str, ...]] - (ID, ID_LIKE, VERSION_ID) tuple or None }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: _get_os_release
@lru_cache
async def _get_os_release(conn: SSHClientConnection) -> Optional[tuple[str, ...]]:
    "Get os release string on linuxes"
    proc = await conn.run(
        "sh -c 'source /etc/os-release; echo $ID@@@$ID_LIKE@@@$VERSION_ID'"
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return tuple(map(lambda x: x.strip(), str(proc.stdout).split("@@@", maxsplit=3)))


# START_CONTRACT: check_is_debian_like
#   PURPOSE: Check if remote is Debian-like via os-release ID/ID_LIKE
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if remote is Debian-like }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: check_is_debian_like
async def check_is_debian_like(conn: SSHClientConnection) -> bool:
    "Check for any Debian-like"
    os_release = await _get_os_release(conn)
    if not os_release:
        return False
    parts = cast("tuple[str, str, str]", os_release)
    return "debian" in parts[0:2]


# START_CONTRACT: check_is_debian
#   PURPOSE: Check if remote is Debian via os-release ID
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if remote is Debian }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: check_is_debian
async def check_is_debian(conn: SSHClientConnection) -> bool:
    "Check for any Debian"
    os_release = await _get_os_release(conn)
    return os_release[0] == "debian" if os_release else False


# START_CONTRACT: _check_debian_version
#   PURPOSE: Check if remote matches a specific Debian version
#   INPUTS: { version: str - Debian version string } | { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if remote matches the version }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: _check_debian_version
async def _check_debian_version(version: str, conn: SSHClientConnection) -> bool:
    "Check for Debian version"
    os_release = await _get_os_release(conn)
    if not os_release:
        return False
    parts = cast("tuple[str, str, str]", os_release)
    return len(parts) >= 3 and parts[2] == version


check_is_debian_10 = partial(_check_debian_version, "10")
check_is_debian_11 = partial(_check_debian_version, "11")
check_is_debian_12 = partial(_check_debian_version, "12")
check_is_debian_13 = partial(_check_debian_version, "13")
check_is_debian_14 = partial(_check_debian_version, "14")
check_is_debian_15 = partial(_check_debian_version, "15")


# START_CONTRACT: check_is_windows
#   PURPOSE: Check if remote runs Windows via PowerShell OSVersion check
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if remote is Windows with PowerShell }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: check_is_windows
@lru_cache
async def check_is_windows(conn: SSHClientConnection) -> bool:
    "Check for any Windows with Powershell"
    proc = await conn.run("[environment]::OSVersion")
    return proc.returncode == 0


# START_CONTRACT: get_wmi_w32_os_caption
#   PURPOSE: Get Windows OS caption via WMI Win32_OperatingSystem
#   INPUTS: { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { Optional[str] - OS caption string or None }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: get_wmi_w32_os_caption
@lru_cache
async def get_wmi_w32_os_caption(conn: SSHClientConnection) -> Optional[str]:
    "Get OS caption from WMI object"
    proc = await conn.run("(Get-WmiObject -class Win32_OperatingSystem).Caption")
    if proc.stdout:
        return str(proc.stdout)


# START_CONTRACT: _check_is_windows_caption_version
#   PURPOSE: Check if remote Windows caption contains a specific version string
#   INPUTS: { version: str - Windows version string } | { conn: SSHClientConnection - SSH connection to remote }
#   OUTPUTS: { bool - True if caption contains version }
#   SIDE_EFFECTS: Runs SSH command on remote machine.
#   LINKS: M-REMOTE-CHECKS
# END_CONTRACT: _check_is_windows_caption_version
async def _check_is_windows_caption_version(
    version: str, conn: SSHClientConnection
) -> bool:
    "Check for Windows version in caption"
    caption = await get_wmi_w32_os_caption(conn)
    return version in caption if caption else False


check_is_windows7 = partial(_check_is_windows_caption_version, "7")
check_is_windows8 = partial(_check_is_windows_caption_version, "8")
check_is_windows10 = partial(_check_is_windows_caption_version, "10")
check_is_windows11 = partial(_check_is_windows_caption_version, "11")
check_is_windows12 = partial(_check_is_windows_caption_version, "12")

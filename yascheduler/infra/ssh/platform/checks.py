"""SSH-based platform detection check functions for each supported OS family."""
# region MODULE_CONTRACT
# PURPOSE: Family-level platform check functions — invoked via SSHClientConnection.
# SCOPE:
# - Linux/Darwin detection: uname-based
# - Debian detection: os-release-based (ID, ID_LIKE)
# - Windows detection: PowerShell OSVersion
# DEPENDENCIES: USES API: asyncssh (SSHClientConnection.run), asyncstdlib (lru_cache)
# KEYWORDS: checks, platform detection, os, linux, debian, windows, darwin
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from asyncstdlib import lru_cache

if TYPE_CHECKING:
    from asyncssh.connection import SSHClientConnection

__all__ = [
    "check_is_darwin",
    "check_is_debian",
    "check_is_debian_like",
    "check_is_linux",
    "check_is_windows",
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
# PURPOSE: Get os-release fields (ID, ID_LIKE) from remote Linux.
@lru_cache
async def _get_os_release(conn: SSHClientConnection) -> tuple[str, ...] | None:
    """Get os release string on linuxes."""
    proc = await conn.run("sh -c 'source /etc/os-release; echo $ID@@@$ID_LIKE'")
    if proc.returncode != 0 or not proc.stdout:
        return None
    return tuple(x.strip() for x in str(proc.stdout).split("@@@", maxsplit=2))


# endregion FUNC__get_os_release


# region FUNC_check_is_debian_like
# PURPOSE: Check if remote is Debian-like via os-release ID/ID_LIKE.
async def check_is_debian_like(conn: SSHClientConnection) -> bool:
    """Check for any Debian-like."""
    os_release = await _get_os_release(conn)
    if not os_release:
        return False
    parts = cast("tuple[str, str]", os_release)
    return "debian" in parts[0:2]


# endregion FUNC_check_is_debian_like


# region FUNC_check_is_debian
# PURPOSE: Check if remote is Debian via os-release ID.
async def check_is_debian(conn: SSHClientConnection) -> bool:
    """Check for any Debian."""
    os_release = await _get_os_release(conn)
    return os_release[0] == "debian" if os_release else False


# endregion FUNC_check_is_debian


# region FUNC_check_is_windows
# PURPOSE: Check if remote runs Windows via PowerShell OSVersion check.
@lru_cache
async def check_is_windows(conn: SSHClientConnection) -> bool:
    """Check for any Windows with Powershell."""
    proc = await conn.run("[environment]::OSVersion")
    return proc.returncode == 0


# endregion FUNC_check_is_windows

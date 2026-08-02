"""Platform detection and OS-specific command adapters for SSH-connected machines."""
# region MODULE_CONTRACT
# PURPOSE: Re-export platform detection infrastructure and OS-specific adapters for external consumers.
# SCOPE:
# - Adapter instances (linux, darwin, debian, windows variants)
# - Check functions (check_is_linux, check_is_darwin, etc.)
# - Common run/run_bg, detect, exceptions, linux/windows functions
# - Protocol types, registry, path helpers, run_fn factory
# KEYWORDS: platform, re-export, adapters, detect, linux, windows, darwin
# endregion MODULE_CONTRACT

from .adapters import (
    RemoteMachineAdapter,
    darwin_adapter,
    debian_10_adapter,
    debian_11_adapter,
    debian_12_adapter,
    debian_13_adapter,
    debian_14_adapter,
    debian_15_adapter,
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    windows7_adapter,
    windows8_adapter,
    windows10_adapter,
    windows11_adapter,
    windows12_adapter,
    windows_adapter,
)
from .checks import (
    check_is_darwin,
    check_is_debian,
    check_is_debian_10,
    check_is_debian_11,
    check_is_debian_12,
    check_is_debian_13,
    check_is_debian_14,
    check_is_debian_15,
    check_is_debian_like,
    check_is_linux,
    check_is_windows,
    check_is_windows7,
    check_is_windows8,
    check_is_windows10,
    check_is_windows11,
    check_is_windows12,
)
from .common import run, run_bg
from .detect import MAX_SESSIONS, _detect_platform
from .exceptions import PlatformGuessFailedError
from .linux import (
    deploy_local_archive,
    deploy_local_files,
    deploy_remote_archive,
    linux_deploy_engines,
    linux_get_cpu_cores,
    linux_list_processes,
    linux_pgrep,
    linux_setup_deb_node,
    linux_setup_node,
    log_mpi_version,
)
from .paths import _init_paths
from .registry import ADAPTERS
from .run_fn import make_run_fn
from .types import (
    AllSSHRetryExc,
    GetCPUCoresCallable,
    ListProcessesCallable,
    OuterRunCallable,
    PgrepCallable,
    ProcessInfo,
    QuoteCallable,
    RunBgCallable,
    RunCallable,
    SetupNodeCallable,
    SFTPRetryExc,
    SSHCheck,
    SSHRetryExc,
)
from .windows import (
    MyPureWindowsPath,
    windows_deploy_engines,
    windows_get_cpu_cores,
    windows_list_processes,
    windows_pgrep,
    windows_quote,
    windows_setup_node,
)
from .windows import (
    deploy_local_archive as windows_deploy_local_archive,
)
from .windows import (
    deploy_local_files as windows_deploy_local_files,
)
from .windows import (
    deploy_remote_archive as windows_deploy_remote_archive,
)

__all__ = [
    "ADAPTERS",
    "MAX_SESSIONS",
    "AllSSHRetryExc",
    "GetCPUCoresCallable",
    "ListProcessesCallable",
    "MyPureWindowsPath",
    "OuterRunCallable",
    "PgrepCallable",
    "PlatformGuessFailedError",
    "ProcessInfo",
    "QuoteCallable",
    "RemoteMachineAdapter",
    "RunBgCallable",
    "RunCallable",
    "SFTPRetryExc",
    "SSHCheck",
    "SSHRetryExc",
    "SetupNodeCallable",
    "_detect_platform",
    "_init_paths",
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
    "darwin_adapter",
    "debian_10_adapter",
    "debian_11_adapter",
    "debian_12_adapter",
    "debian_13_adapter",
    "debian_14_adapter",
    "debian_15_adapter",
    "debian_adapter",
    "debian_like_adapter",
    "deploy_local_archive",
    "deploy_local_files",
    "deploy_remote_archive",
    "linux_adapter",
    "linux_deploy_engines",
    "linux_get_cpu_cores",
    "linux_list_processes",
    "linux_pgrep",
    "linux_setup_deb_node",
    "linux_setup_node",
    "log_mpi_version",
    "make_run_fn",
    "run",
    "run_bg",
    "windows7_adapter",
    "windows8_adapter",
    "windows10_adapter",
    "windows11_adapter",
    "windows12_adapter",
    "windows_adapter",
    "windows_deploy_engines",
    "windows_deploy_local_archive",
    "windows_deploy_local_files",
    "windows_deploy_remote_archive",
    "windows_get_cpu_cores",
    "windows_list_processes",
    "windows_pgrep",
    "windows_quote",
    "windows_setup_node",
]

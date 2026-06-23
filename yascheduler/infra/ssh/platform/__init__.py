# FILE: yascheduler/infra/ssh/platform/__init__.py
# VERSION: 1.0.1
# START_MODULE_CONTRACT
#   PURPOSE: Platform detection and OS-specific command adapters for SSH-connected machines.
#   SCOPE: Re-exports from platform submodules.
#   DEPENDS: none
#   LINKS: M-SSH-GATEWAY, M-PLATFORM-ADAPTERS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Re-exports - Platform detection and OS-specific adapters re-exported from submodules
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/ (rename-adapters-to-infra); no behavioral change.
#   PREVIOUS_CHANGE: v1.0.0 - Initial platform adapters package.
# END_CHANGE_SUMMARY

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
from .common import ProcessInfo, run, run_bg
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
from .protocol import (
    AllSSHRetryExc,
    GetCPUCoresCallable,
    ListProcessesCallable,
    OuterRunCallable,
    PEngine,
    PEngineRepository,
    PgrepCallable,
    PNode,
    PProcessInfo,
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
    "RemoteMachineAdapter",
    "linux_adapter",
    "darwin_adapter",
    "debian_adapter",
    "debian_like_adapter",
    "debian_10_adapter",
    "debian_11_adapter",
    "debian_12_adapter",
    "debian_13_adapter",
    "debian_14_adapter",
    "debian_15_adapter",
    "windows_adapter",
    "windows7_adapter",
    "windows8_adapter",
    "windows10_adapter",
    "windows11_adapter",
    "windows12_adapter",
    "check_is_linux",
    "check_is_darwin",
    "check_is_debian_like",
    "check_is_debian",
    "check_is_debian_10",
    "check_is_debian_11",
    "check_is_debian_12",
    "check_is_debian_13",
    "check_is_debian_14",
    "check_is_debian_15",
    "check_is_windows",
    "check_is_windows7",
    "check_is_windows8",
    "check_is_windows10",
    "check_is_windows11",
    "check_is_windows12",
    "ProcessInfo",
    "run",
    "run_bg",
    "PlatformGuessFailedError",
    "SFTPRetryExc",
    "SSHRetryExc",
    "AllSSHRetryExc",
    "PProcessInfo",
    "PEngine",
    "PEngineRepository",
    "PNode",
    "SSHCheck",
    "QuoteCallable",
    "RunCallable",
    "RunBgCallable",
    "OuterRunCallable",
    "GetCPUCoresCallable",
    "ListProcessesCallable",
    "PgrepCallable",
    "SetupNodeCallable",
    "MyPureWindowsPath",
    "windows_quote",
    "linux_get_cpu_cores",
    "linux_list_processes",
    "linux_pgrep",
    "linux_deploy_engines",
    "linux_setup_node",
    "linux_setup_deb_node",
    "deploy_local_files",
    "deploy_local_archive",
    "deploy_remote_archive",
    "log_mpi_version",
    "windows_get_cpu_cores",
    "windows_list_processes",
    "windows_pgrep",
    "windows_deploy_engines",
    "windows_setup_node",
    "windows_deploy_local_files",
    "windows_deploy_local_archive",
    "windows_deploy_remote_archive",
]

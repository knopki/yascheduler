# FILE: yascheduler/infra/ssh/platform/__init__.py
# VERSION: 1.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Platform detection and OS-specific command adapters for SSH-connected machines.
#   SCOPE: Re-exports from platform submodules, including the detection registry/symbols migrated from the dissolved helpers.py.
#   DEPENDS: none
#   LINKS: M-PLATFORM-ADAPTERS, M-PLATFORM-DETECT, M-PLATFORM-PATHS, M-PLATFORM-RUN-FN
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   Re-exports - Platform detection and OS-specific adapters re-exported from submodules
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.3.0 - Re-export ADAPTERS (from .registry), _detect_platform + MAX_SESSIONS (from .detect), _init_paths (from .paths), make_run_fn (from .run_fn) — symbols migrated from the dissolved helpers.py / gateway._make_run_fn (decompose-ssh-gateway). repository.py and operations/base.py import these from here instead of helpers.py / gateway.
#   PREVIOUS_CHANGE: v1.2.0 - Relocate ProcessInfo import source to .protocol (was .common); drop PNode and PProcessInfo from re-export block and __all__ (prune-platform-protocols). ProcessInfo stays in __all__ unchanged.
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
from .protocol import (
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
from .registry import ADAPTERS
from .run_fn import make_run_fn
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
    "ADAPTERS",
    "MAX_SESSIONS",
    "_detect_platform",
    "_init_paths",
    "make_run_fn",
]

"""Platform detection and OS-specific command adapters for SSH-connected machines."""
# region MODULE_CONTRACT
# PURPOSE: Re-export platform detection infrastructure and OS-specific adapters for external consumers.
# KEYWORDS: platform, re-export, adapters, detect, linux, windows, darwin
# endregion MODULE_CONTRACT

from .adapters import (
    RemoteMachineAdapter,
    darwin_adapter,
    debian_adapter,
    debian_like_adapter,
    linux_adapter,
    windows_adapter,
)
from .checks import (
    check_is_darwin,
    check_is_debian,
    check_is_debian_like,
    check_is_linux,
    check_is_windows,
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
    "check_is_debian_like",
    "check_is_linux",
    "check_is_windows",
    "darwin_adapter",
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

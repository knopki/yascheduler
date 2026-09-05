"""Platform-specific adapter registry mapping OS family identifiers to adapter instances."""
# region MODULE_CONTRACT
# PURPOSE: Frozen adapter instances for each supported OS family, holding platform-specific callables and check sequences.
# SCOPE:
# - RemoteMachineAdapter frozen dataclass
# - adapters
# - All adapters are built from .common, .linux, .windows implementations
# KEYWORDS: adapters, platform, linux, windows, darwin, debian, registry
# endregion MODULE_CONTRACT

import shlex
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePath, PurePosixPath

from .checks import (
    check_is_darwin,
    check_is_debian,
    check_is_debian_like,
    check_is_linux,
    check_is_windows,
)
from .common import run, run_bg
from .linux import (
    linux_get_cpu_cores,
    linux_list_processes,
    linux_pgrep,
    linux_setup_deb_node,
    linux_setup_node,
)
from .types import (
    GetCPUCoresCallable,
    ListProcessesCallable,
    PgrepCallable,
    QuoteCallable,
    RunBgCallable,
    RunCallable,
    SetupNodeCallable,
    SSHCheck,
)
from .windows import (
    MyPureWindowsPath,
    windows_get_cpu_cores,
    windows_list_processes,
    windows_pgrep,
    windows_quote,
    windows_setup_node,
)

__all__ = [
    "RemoteMachineAdapter",
    "darwin_adapter",
    "debian_adapter",
    "debian_like_adapter",
    "linux_adapter",
    "windows_adapter",
]


# region CLASS_RemoteMachineAdapter
# PURPOSE: Bundle a platform's SSH-callables + check sequence into a single frozen value so platform detection can return one adapter carrying everything the session needs to operate on the remote machine.
@dataclass(frozen=True)
class RemoteMachineAdapter:
    """Remote machine adapter — frozen data class holding platform-specific callables and check sequence."""

    platform: str
    path: type[PurePath]

    quote: QuoteCallable
    run: RunCallable
    run_bg: RunBgCallable
    get_cpu_cores: GetCPUCoresCallable
    list_processes: ListProcessesCallable
    pgrep: PgrepCallable
    setup_node: SetupNodeCallable

    checks: Sequence[SSHCheck] = field(default_factory=tuple)


# endregion CLASS_RemoteMachineAdapter

linux_adapter = RemoteMachineAdapter(
    platform="linux",
    path=PurePosixPath,
    quote=shlex.quote,
    run=run,
    run_bg=run_bg,
    get_cpu_cores=linux_get_cpu_cores,
    list_processes=linux_list_processes,
    pgrep=linux_pgrep,
    setup_node=linux_setup_node,
    checks=(check_is_linux,),
)

debian_like_adapter = replace(
    linux_adapter,
    platform="debian-like",
    setup_node=linux_setup_deb_node,
    checks=(*linux_adapter.checks, check_is_debian_like),
)

debian_adapter = replace(
    debian_like_adapter,
    platform="debian",
    checks=(*debian_like_adapter.checks, check_is_debian),
)

darwin_adapter = replace(
    linux_adapter,
    platform="darwin",
    checks=(check_is_darwin,),
)

windows_adapter = RemoteMachineAdapter(
    platform="windows",
    path=MyPureWindowsPath,
    quote=windows_quote,
    run=run,
    run_bg=run_bg,
    get_cpu_cores=windows_get_cpu_cores,
    list_processes=windows_list_processes,
    pgrep=windows_pgrep,
    setup_node=windows_setup_node,
    checks=(check_is_windows,),
)

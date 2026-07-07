#!/usr/bin/env python3
#
# FILE: yascheduler/infra/ssh/platform/adapters.py
# VERSION: 1.1.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Platform-specific adapter registry mapping OS identifiers to adapter instances.
#   SCOPE: RemoteMachineAdapter dataclass and platform adapter instances.
#   DEPENDS: M-PLATFORM-PROTOCOL, M-PLATFORM-CHECKS, M-PLATFORM-LINUX, M-PLATFORM-WINDOWS, M-PLATFORM-COMMON
#   LINKS: M-SSH-REPOSITORY, M-SSH-OPERATIONS, M-PLATFORM-CHECKS, M-PLATFORM-LINUX, M-PLATFORM-WINDOWS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   RemoteMachineAdapter - Frozen dataclass holding platform-specific callables and check sequences
#   linux_adapter - Generic Linux adapter instance
#   debian_like_adapter - Debian-like variant evolved from linux_adapter
#   debian_adapter - Generic Debian variant evolved from debian_like_adapter
#   debian_10_adapter .. debian_15_adapter - Version-specific Debian adapters
#   darwin_adapter - Darwin/macOS adapter instance
#   windows_adapter - Generic Windows adapter instance
#   windows7_adapter .. windows12_adapter - Version-specific Windows adapters
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.1.0 - Migrated RemoteMachineAdapter from attrs.define/evolve/field to stdlib dataclasses.dataclass/replace/field; no behavioral change.
#   PREVIOUS_CHANGE: v1.0.1 - Relocated yascheduler/adapters/ -> yascheduler/infra/; no behavioral change.
# END_CHANGE_SUMMARY
#

import shlex
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePath, PurePosixPath

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
from .linux import (
    linux_get_cpu_cores,
    linux_list_processes,
    linux_pgrep,
    linux_setup_deb_node,
    linux_setup_node,
)
from .protocol import (
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


@dataclass(frozen=True)
class RemoteMachineAdapter:
    "Remote machine adapter"

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

debian_10_adapter = replace(
    debian_adapter,
    platform="debian-10",
    checks=(*debian_adapter.checks, check_is_debian_10),
)

debian_11_adapter = replace(
    debian_adapter,
    platform="debian-13",
    checks=(*debian_adapter.checks, check_is_debian_11),
)

debian_12_adapter = replace(
    debian_adapter,
    platform="debian-12",
    checks=(*debian_adapter.checks, check_is_debian_12),
)

debian_13_adapter = replace(
    debian_adapter,
    platform="debian-13",
    checks=(*debian_adapter.checks, check_is_debian_13),
)

debian_14_adapter = replace(
    debian_adapter,
    platform="debian-14",
    checks=(*debian_adapter.checks, check_is_debian_14),
)

debian_15_adapter = replace(
    debian_adapter,
    platform="debian-15",
    checks=(*debian_adapter.checks, check_is_debian_15),
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

windows7_adapter = replace(
    windows_adapter,
    platform="windows-7",
    checks=(*windows_adapter.checks, check_is_windows7),
)

windows8_adapter = replace(
    windows_adapter,
    platform="windows-8",
    checks=(*windows_adapter.checks, check_is_windows8),
)

windows10_adapter = replace(
    windows_adapter,
    platform="windows-10",
    checks=(*windows_adapter.checks, check_is_windows10),
)

windows11_adapter = replace(
    windows_adapter,
    platform="windows-11",
    checks=(*windows_adapter.checks, check_is_windows11),
)

windows12_adapter = replace(
    windows_adapter,
    platform="windows-12",
    checks=(*windows_adapter.checks, check_is_windows12),
)

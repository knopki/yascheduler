#!/usr/bin/env python3
# FILE: yascheduler/remote_machine/remote_machine_repository.py
# VERSION: 1.7.0
#
# START_MODULE_CONTRACT
#   PURPOSE: Compatibility registry of RemoteMachine wrappers. SSH operations delegated to SSHMachineGateway via RemoteMachine wrapper.
#   SCOPE: RemoteMachineRepository class with filter, disconnect_many, and disconnect_all operations.
#   DEPENDS: M-REMOTE, M-COMPAT, M-SSH-GATEWAY
#   LINKS: M-SCHEDULER, M-REMOTE, M-SSH-GATEWAY
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   RemoteMachineRepository - Dict-based registry of RemoteMachine wrappers; filter/close delegated to gateway via wrapper
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - SSH operations now delegated to SSHMachineGateway via RemoteMachine wrapper; filter/disconnect logic preserved for backward compat.
#   PREVIOUS_CHANGE: v1.6.0 - Initial GRACE-lite markup.
# END_CHANGE_SUMMARY
#

import asyncio
import logging
from collections import UserDict
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from operator import itemgetter
from typing import Optional

from attrs import define, evolve, field

from ..compat import Self
from .remote_machine import RemoteMachine


@define
class RemoteMachineRepository(UserDict[str, RemoteMachine]):
    """Registry of RemoteMachine instances. Delegates SSH operations to SSHMachineGateway via each RemoteMachine wrapper."""

    log: Optional[logging.Logger]
    data: dict[str, RemoteMachine] = field(factory=dict)
    connect_in_flight: set[str] = field(factory=set, init=False)

    # START_CONTRACT: disconnect_many
    #   PURPOSE: Close SSH connections for specific IPs and remove from registry.
    #            Delegates to RemoteMachine.close() which calls gateway.disconnect().
    #   INPUTS: { ips: Sequence[str] - IP addresses to disconnect }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Closes SSH connections, removes machines from registry, skips busy machines
    #   LINKS: M-REMOTE-REPO, M-SSH-GATEWAY
    # END_CONTRACT: disconnect_many
    async def disconnect_many(self, ips: Sequence[str]) -> None:
        "Disconnect from many remote machines and remove them from registry"
        if not ips:
            return
        if self.log:
            self.log.info("Disconnecting from machines: {}".format(", ".join(ips)))

        tasks: list[Awaitable[None]] = []
        for ip, machine in list(self.data.items()):
            # guard
            if machine.meta.busy:
                continue
            if ip in ips:
                tasks.append(machine.close())
                del self.data[ip]
        await asyncio.gather(*tasks, return_exceptions=True)

    # START_CONTRACT: disconnect_all
    #   PURPOSE: Close all SSH connections and clear registry via disconnect_many.
    #   INPUTS: { None }
    #   OUTPUTS: { None - no return value }
    #   SIDE_EFFECTS: Disconnects all non-busy machines from registry
    #   LINKS: M-REMOTE-REPO, M-SSH-GATEWAY
    # END_CONTRACT: disconnect_all
    async def disconnect_all(self) -> None:
        "Disconnect from all remotes"
        await self.disconnect_many(list(self.data.keys()))

    # START_CONTRACT: filter
    #   PURPOSE: Filter machines by busy/platform/free_since criteria and sort by free_since.
    #            Operates on self.data which holds RemoteMachine wrappers (meta, platforms still available).
    #   INPUTS: { busy: Optional[bool] - filter by busy status } | { platforms: Optional[Sequence[str]] - filter by platform } | { free_since_gt: Optional[timedelta] - filter by free duration } | { reverse_sort: bool - reverse sort order }
    #   OUTPUTS: { Self - new RemoteMachineRepository with filtered and sorted machines }
    #   SIDE_EFFECTS: None - returns a new evolved instance
    #   LINKS: M-REMOTE-REPO
    # END_CONTRACT: filter
    def filter(
        self,
        busy: Optional[bool] = None,
        platforms: Optional[Sequence[str]] = None,
        free_since_gt: Optional[timedelta] = None,
        reverse_sort: bool = False,
    ) -> Self:
        "Return machines filtered and sorted by `free_since`"

        checks: Sequence[Callable[[RemoteMachine], bool]] = []
        if busy is True:
            checks.append(lambda x: x.meta.busy is True)
        if busy is False:
            checks.append(lambda x: not x.meta.busy)
        if platforms:
            checks.append(lambda x: bool(set(platforms) & set(x.platforms)))
        if free_since_gt:
            checks.append(lambda x: x.meta.is_free_longer_than(free_since_gt))

        return evolve(
            self,
            data={
                ip: m
                for ip, m in sorted(
                    self.data.items(), key=itemgetter(1), reverse=reverse_sort
                )
                if all([x(m) for x in checks])
            },
        )

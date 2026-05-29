# FILE: yascheduler/domain/ports.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain port interfaces: abstract contracts for persistence, machine operations, and cloud provisioning.
#   SCOPE: TaskRepository, NodeRepository, MachineGateway, CloudProvisioner Protocol classes.
#   DEPENDS: M-DOMAIN-MODEL
#   LINKS:
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskRepository - Async port for task persistence (get, save, list_by_status)
#   NodeRepository - Async port for node persistence (full CRUD lifecycle)
#   MachineGateway - Async port for remote machine operations (list, run, upload, download)
#   CloudProvisioner - Async port for cloud node provisioning (allocate, deallocate, capacity)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Create domain port interfaces for Hexagonal + DDD migration.
# END_CHANGE_SUMMARY

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .model import (
    ConnectedMachine,
    Node,
    ProcessResult,
    Task,
    TaskStatus,
)


@runtime_checkable
class TaskRepository(Protocol):
    """Async port for task persistence: get, save, list_by_status."""

    async def get(self, task_id: int) -> Task: ...

    async def save(self, task: Task) -> None: ...

    async def list_by_status(self, statuses: set[TaskStatus]) -> list[Task]: ...


@runtime_checkable
class NodeRepository(Protocol):
    """Async port for node persistence: full CRUD lifecycle."""

    async def get(self, ip: str) -> Node: ...

    async def list_enabled(self) -> list[Node]: ...

    async def list_disabled(self) -> list[Node]: ...

    async def add(self, node: Node) -> None: ...

    async def add_tmp(self, ip: str, cloud: str) -> None: ...

    async def update(self, node: Node) -> None: ...

    async def enable(self, ip: str) -> None: ...

    async def disable(self, ip: str) -> None: ...

    async def remove(self, ip: str) -> None: ...


@runtime_checkable
class MachineGateway(Protocol):
    """Async port for remote machine operations: list, run, upload, download."""

    async def list_free(
        self, platforms: list[str] | None
    ) -> list[ConnectedMachine]: ...

    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult: ...

    async def upload(
        self, machine: ConnectedMachine, local: Path, remote: str
    ) -> None: ...

    async def download(
        self, machine: ConnectedMachine, remote: str, local: Path
    ) -> None: ...


@runtime_checkable
class CloudProvisioner(Protocol):
    """Async port for cloud node provisioning: allocate, deallocate, capacity."""

    async def allocate(self, platforms: list[str]) -> Node: ...

    async def deallocate(self, ip: str) -> None: ...

    async def capacity(self) -> dict[str, int]: ...

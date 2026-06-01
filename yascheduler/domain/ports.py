# FILE: yascheduler/domain/ports.py
# VERSION: 1.9.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain port interfaces: abstract contracts for persistence, machine operations, and cloud provisioning.
#   SCOPE: TaskRepository, NodeRepository, MachineGateway, CloudProvisioner Protocol classes.
#   DEPENDS: M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-MODEL, M-PERSISTENCE-POSTGRES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskRepository - Async port for task persistence (get, save, insert, list_by_status, list_by_jobs, update_status, list_ids_by_ip_and_status)
#   NodeRepository - Async port for node persistence (full CRUD lifecycle, list_all, get_by_ips)
#   MachineGateway - Async port for remote machine operations (list, run, upload, download)
#   CloudProvisioner - Async port for cloud node provisioning (allocate, deallocate, capacity)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.9.0 - Add update_status, list_ids_by_ip_and_status to TaskRepository; list_all, get_by_ips to NodeRepository.
#   PREVIOUS_CHANGE: v1.8.0 - Add list_by_jobs() to TaskRepository port for query use cases.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

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

    async def get(self, task_id: int) -> Task | None: ...

    async def save(self, task: Task) -> None: ...

    async def list_by_status(self, statuses: set[TaskStatus]) -> list[Task]: ...

    async def insert(self, task: Task) -> Task: ...

    async def list_by_jobs(self, job_ids: list[int]) -> list[Task]: ...

    async def update_status(self, task_id: int, status: TaskStatus) -> None: ...

    async def list_ids_by_ip_and_status(
        self, ip: str, status: TaskStatus
    ) -> list[int]: ...


@runtime_checkable
class NodeRepository(Protocol):
    """Async port for node persistence: full CRUD lifecycle."""

    async def get(self, ip: str) -> Node | None: ...

    async def list_enabled(self) -> list[Node]: ...

    async def list_disabled(self) -> list[Node]: ...

    async def add(self, node: Node) -> None: ...

    async def add_tmp(self, cloud: str, username: str = "root") -> str: ...

    async def update(self, node: Node) -> None: ...

    async def enable(self, ip: str) -> None: ...

    async def disable(self, ip: str) -> None: ...

    async def remove(self, ip: str) -> None: ...

    async def list_all(self) -> list[Node]: ...

    async def get_by_ips(self, ips: list[str]) -> dict[str, Node]: ...


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

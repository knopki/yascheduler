# FILE: yascheduler/domain/ports.py
# VERSION: 2.3.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain port interfaces: abstract contracts for persistence, machine operations, and cloud provisioning.
#   SCOPE: TaskRepository, NodeRepository, MachineGateway, OccupancyConfig, CloudProvisioner Protocol classes.
#   DEPENDS: M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-MODEL, M-PERSISTENCE-POSTGRES
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskRepository - Async port for task persistence (get, save, insert, list_by_status, list_by_jobs, update_status, list_ids_by_ip_and_status, count_by_status)
#   NodeRepository - Async port for node persistence (full CRUD lifecycle, list_all, get_by_ips, count_by_status)
#   OccupancyConfig - Minimal structural Protocol for occupancy check configuration (name, check_pname, check_cmd, check_cmd_code, sleep_interval)
#   TaskExecutionEngine - Engine contract for task deployment (superset of OccupancyConfig: adds spawn, input_files)
#   MachineGateway - Async port for remote machine operations (lifecycle, queries, run, run_bg, upload, download, download_outputs, occupancy, cpu_cores, start_task_on_machine)
#   CloudProvisioner - Async port for cloud node provisioning (allocate, deallocate, select_provider)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.3.0 - Collapse ProviderSelection: CloudProvisioner.select_provider returns str|None; NodeRepository.add_tmp drops username param (collapse-provider-selection).
#   PREVIOUS_CHANGE: v2.2.0 - Update CloudProvisioner Protocol: allocate takes provider:str, deallocate takes cloud+ip, new sync select_provider, removed capacity; add ProviderSelection import (cloud-provisioner-pure).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path, PurePath

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

    async def list_by_status(
        self, statuses: set[TaskStatus], *, limit: int | None = None
    ) -> list[Task]: ...

    async def insert(self, task: Task) -> Task: ...

    async def list_by_jobs(self, job_ids: list[int]) -> list[Task]: ...

    async def update_status(self, task_id: int, status: TaskStatus) -> None: ...

    async def list_ids_by_ip_and_status(
        self, ip: str, status: TaskStatus
    ) -> list[int]: ...

    async def count_by_status(self) -> Mapping[TaskStatus, int]: ...


@runtime_checkable
class NodeRepository(Protocol):
    """Async port for node persistence: full CRUD lifecycle."""

    async def get(self, ip: str) -> Node | None: ...

    async def list_enabled(self) -> list[Node]: ...

    async def list_disabled(self) -> list[Node]: ...

    async def add(self, node: Node) -> None: ...

    async def add_tmp(self, cloud: str) -> str: ...

    async def update(self, node: Node) -> None: ...

    async def enable(self, ip: str) -> None: ...

    async def disable(self, ip: str) -> None: ...

    async def remove(self, ip: str) -> None: ...

    async def list_all(self) -> list[Node]: ...

    async def get_by_ips(self, ips: list[str]) -> dict[str, Node]: ...

    async def count_by_status(self) -> Mapping[bool, int]: ...


# START_CONTRACT: OccupancyConfig
#   PURPOSE: Minimal structural contract for occupancy check configuration.
#   LINKS: M-DOMAIN-PORTS, M-SSH-GATEWAY
# END_CONTRACT: OccupancyConfig
@runtime_checkable
class OccupancyConfig(Protocol):
    """Minimal contract for occupancy check configuration.

    Satisfied structurally by `config.Engine` — captures exactly the fields
    the gateway needs to start background occupancy monitoring, without
    pulling in deployment or platform details.
    """

    name: str
    check_pname: str | None
    check_cmd: str | None
    check_cmd_code: int
    sleep_interval: int


# START_CONTRACT: TaskExecutionEngine
#   PURPOSE: Structural contract for engine metadata needed to deploy and spawn a task on a machine.
#   LINKS: M-DOMAIN-PORTS, M-SSH-GATEWAY
# END_CONTRACT: TaskExecutionEngine
@runtime_checkable
class TaskExecutionEngine(Protocol):
    """Engine contract for task deployment (superset of OccupancyConfig).

    `config.Engine` satisfies this structurally.
    """

    # OccupancyConfig fields
    name: str
    check_pname: str | None
    check_cmd: str | None
    check_cmd_code: int
    sleep_interval: int
    # Task deployment fields
    spawn: str
    input_files: tuple[str, ...]


@runtime_checkable
class MachineGateway(Protocol):
    """Async port for remote machine operations.

    Covers connection lifecycle, machine queries, command execution,
    file transfer, occupancy monitoring, remote info, and task deployment.
    """

    async def connect(
        self,
        ip: str,
        username: str,
        client_keys: Sequence[PurePath] | None,
        *,
        port: int = 22,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
        jump_host: str | None = None,
        jump_username: str | None = None,
    ) -> ConnectedMachine: ...

    async def disconnect(self, ip: str) -> None: ...

    async def disconnect_all(self) -> None: ...

    def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]: ...

    def list_connected(self) -> list[ConnectedMachine]: ...

    def contains(self, ip: str) -> bool: ...

    def get_machine_state(self, ip: str) -> ConnectedMachine | None: ...

    def update_machine(self, machine: ConnectedMachine) -> None: ...

    def __len__(self) -> int: ...

    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult: ...

    async def run_bg(
        self, machine: ConnectedMachine, cmd: str, *, cwd: str | None = None
    ) -> None: ...

    async def upload(
        self, machine: ConnectedMachine, local: Path, remote: str
    ) -> None: ...

    async def download(
        self, machine: ConnectedMachine, remote: str, local: Path
    ) -> None: ...

    async def download_outputs(
        self,
        ip: str,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: int | None = None,
    ) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]: ...

    def start_occupancy_check(self, ip: str, config: OccupancyConfig) -> None: ...

    async def start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: TaskExecutionEngine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool: ...

    async def get_cpu_cores(self, ip: str) -> int: ...


@runtime_checkable
class CloudProvisioner(Protocol):
    """Port for cloud node provisioning.

    Provider selection is sync (no I/O); allocate/deallocate are async.
    select_provider returns None when no provider has capacity OR when the
    selected provider is throttled (op semaphore locked).
    """

    async def allocate(self, provider: str) -> Node: ...

    async def deallocate(self, cloud: str, ip: str) -> None: ...

    def select_provider(
        self, platforms: list[str], current_counts: dict[str, int]
    ) -> str | None: ...

    async def stop(self) -> None: ...

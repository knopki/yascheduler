# FILE: yascheduler/domain/ports.py
# VERSION: 2.7.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain port interfaces: abstract contracts for persistence, machine operations, and cloud provisioning.
#   SCOPE: TaskRepository, NodeRepository, MachineGateway, CloudConfig, CloudProvisioner Protocol classes.
#   DEPENDS: M-DOMAIN-MODEL
#   LINKS: M-DOMAIN-MODEL, M-PERSISTENCE-POSTGRES, M-CLOUD-CONFIGS, M-APPLICATION-DEALLOCATE, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskRepository - Async port for task persistence (get, save, insert, list_by_status, list_by_jobs, update_status, list_ids_by_ip_and_status, count_by_status)
#   NodeRepository - Async port for node persistence (full CRUD lifecycle, list_all, get_by_ips, count_by_status)
#   CloudConfig - Structural Protocol for cloud provider config (7-field surface application consumers read: prefix, max_nodes, idle_tolerance, connect_grace, username, jump_username, jump_host)
#   MachineGateway - Async port for remote machine operations (lifecycle, queries, run, run_bg, upload, download, download_outputs, occupancy, cpu_cores, start_task_on_machine)
#   CloudProvisioner - Async port for cloud node provisioning (allocate, deallocate, select_provider)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.7.0 - Add connect_grace: int to CloudConfig Protocol between idle_tolerance and username (fix-never-connected-node-leak); widens the surface from 6 to 7 fields so the orchestrator can resolve a per-cloud SSH connect-failure deadline. The 4 ConfigCloud* DTOs declare per-provider defaults (Hetzner/Upcloud=60, Azure/VastAI=120).
#   PREVIOUS_CHANGE: v2.6.0 - Update CloudConfig Protocol docstring to reflect explicit inheritance by the 4 ConfigCloud* DTOs (resolve-type-bridge-debt / D6); no signature change. CloudConfig contract moved to its own Requirement in openspec/specs/domain-ports/spec.md (removed sub-prose from MachineGateway port Requirement).
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path, PurePath

    from .engine import Engine
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


# START_CONTRACT: CloudConfig
#   PURPOSE: Structural contract for cloud provider config — the 7-field surface application consumers read.
#   LINKS: M-DOMAIN-PORTS, M-CLOUD-CONFIGS, M-APPLICATION-DEALLOCATE, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_CONTRACT: CloudConfig
@runtime_checkable
class CloudConfig(Protocol):
    """Cloud provider config contract — minimal surface application consumers read.

    Satisfied by every `ConfigCloud*` DTO in `infra/cloud/cloud_configs.py` —
    the DTOs inherit this Protocol explicitly (typing aid); a DTO outside the
    inheritance tree still satisfies it structurally (PEP 544). Captures exactly
    the fields `deallocate_nodes` (prefix, idle_tolerance), `orchestrator`
    (prefix, max_nodes, jump_host, jump_username), and the never-connected-node
    cleanup path (prefix, connect_grace) read; provider-specific fields
    (`tenant_id`, `token`, `login`, `api_key`, `vm_size`, etc.) stay on
    the concrete DTOs and are accessed only by infra-layer consumers.
    """

    prefix: str
    max_nodes: int
    idle_tolerance: int
    connect_grace: int
    username: str
    jump_username: str | None
    jump_host: str | None


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

    def start_occupancy_check(self, ip: str, config: Engine) -> None: ...

    async def start_task_on_machine(
        self,
        machine: ConnectedMachine,
        engine: Engine,
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

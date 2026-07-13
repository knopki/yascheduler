# FILE: yascheduler/domain/ports.py
# VERSION: 2.22.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain port interfaces: abstract contracts for persistence, machine collection/sessions, and cloud provisioning.
#   SCOPE: Protocol-based port interfaces for persistence (TaskRepository, NodeRepository), machine collection/sessions (MachineRepository, MachineSession), and cloud provisioning (CloudConfig, CloudProvisioner).
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-ENGINE
#   LINKS: M-DOMAIN-MODEL, M-PERSISTENCE-POSTGRES, M-CLOUD-CONFIGS, M-APPLICATION-DEALLOCATE, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskRepository - Async port for task persistence
#   NodeRepository - Async port for node persistence
#   CloudConfig - Structural Protocol for cloud provider config
#   MachineRepository - Async port for the connected-machine collection
#   MachineSession - Connected-machine entity handle
#   CloudProvisioner - Async port for cloud node provisioning
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.24.0 - Add jump_port: int as 8th field on CloudConfig Protocol (alongside jump_host/jump_username).
#   PREVIOUS_CHANGE: v2.23.0 - node-owns-connection-identity: drop jump_host/jump_username from MachineRepository.connect signature.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path, PurePath
    from re import Pattern

    from asyncssh.sftp import SFTPClient

    from .engine import EngineRepository
    from .model import (
        ConnectedMachine,
        NewNode,
        NewTask,
        Node,
        NodeId,
        ProcessResult,
        Task,
        TaskId,
        TaskStatus,
    )


@runtime_checkable
class TaskRepository(Protocol):
    """Async port for task persistence."""

    async def get(self, task_id: TaskId) -> Task | None: ...

    async def save(self, task: Task) -> None: ...

    async def list_by_status(
        self, statuses: set[TaskStatus], *, limit: int | None = None
    ) -> list[Task]: ...

    async def insert(self, new_task: NewTask) -> Task: ...

    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]: ...

    async def update_status(self, task_id: TaskId, status: TaskStatus) -> None: ...

    async def list_ids_by_node_id_and_status(
        self, node_id: NodeId, status: TaskStatus
    ) -> list[TaskId]: ...

    async def count_by_status(self) -> Mapping[TaskStatus, int]: ...


@runtime_checkable
class NodeRepository(Protocol):
    """Async port for node persistence."""

    async def get_by_id(self, node_id: NodeId) -> Node | None: ...

    async def get_by_ids(self, node_ids: list[NodeId]) -> dict[NodeId, Node]: ...

    async def list_enabled(self) -> list[Node]: ...

    async def list_disabled(self) -> list[Node]: ...

    async def insert(self, new_node: NewNode) -> Node: ...

    async def update(self, node: Node) -> None: ...

    async def enable(self, node_id: NodeId) -> None: ...

    async def disable(self, node_id: NodeId) -> None: ...

    async def remove(self, node_id: NodeId) -> None: ...

    async def list_all(self) -> list[Node]: ...

    async def count_by_status(self) -> Mapping[bool, int]: ...


# START_CONTRACT: CloudConfig
#   PURPOSE: Structural contract for cloud provider config.
#   LINKS: M-DOMAIN-PORTS, M-CLOUD-CONFIGS, M-APPLICATION-DEALLOCATE, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_CONTRACT: CloudConfig
@runtime_checkable
class CloudConfig(Protocol):
    """Cloud provider config contract — minimal surface application consumers read.

    Satisfied by every `ConfigCloud*` DTO in `infra/cloud/cloud_configs.py` —
    the DTOs inherit this Protocol explicitly (typing aid); a DTO outside the
    inheritance tree still satisfies it structurally (PEP 544).
    """

    prefix: str
    max_nodes: int
    idle_tolerance: int
    connect_grace: int
    username: str
    jump_username: str | None
    jump_host: str | None
    jump_port: int


# START_CONTRACT: MachineSession
#   PURPOSE: Connected-machine entity handle — identity, state transitions, connect-time config,
#     adapter-derived accessors, base SSH primitives, and the per-session monitor mechanism.
#     What MachineRepository hands out and tracks by NodeId; what collaborators
#     (TaskDeployer/OutputDownloader/OccupancyChecker) operate on per call.
#   INPUTS: { None - Protocol defines surface only }
#   OUTPUTS: { None - Protocol defines surface only }
#   SIDE_EFFECTS: None at Protocol level; implementations own connection teardown via _close (private to concrete class)
#   LINKS: M-DOMAIN-PORTS, M-SSH-SESSION, M-SSH-REPOSITORY, M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY
# END_CONTRACT: MachineSession
@runtime_checkable
class MachineSession(Protocol):
    """Connected-machine entity handle — identity, state transitions,
    connect-time config, adapter-derived accessors, base SSH primitives,
    and the per-session monitor mechanism.

    Does NOT cover collection lifecycle, queries, or repository keying —
    those are MachineRepository. Does NOT declare _close (private to the
    concrete class; invoked only by SSHMachineRepository.disconnect).

    The Protocol is Engine-agnostic: install_monitor is generic over
    Callable[[], Awaitable[bool]] and Callable[[], None].
    """

    # ---- Domain face ----
    @property
    def hostname(self) -> str: ...

    @property
    def machine(self) -> ConnectedMachine: ...

    @property
    def is_closed(self) -> bool: ...

    def occupy(self) -> None: ...

    def release(self) -> None: ...

    def update(self, machine: ConnectedMachine) -> None: ...

    # ---- Connect-time config (read-only) ----
    @property
    def adapter(self) -> Any: ...  # noqa: ANN401 - infra RemoteMachineAdapter returned through domain Protocol

    @property
    def platforms(self) -> Sequence[str]: ...

    @property
    def data_dir(self) -> PurePath: ...

    @property
    def engines_dir(self) -> PurePath: ...

    @property
    def tasks_dir(self) -> PurePath: ...

    # ---- Adapter-derived accessors (read-only) ----
    @property
    def path(self) -> type[PurePath]: ...

    @property
    def quote(self) -> Callable[[str], str]: ...

    # ---- Base primitives ----
    async def run(self, cmd: str) -> ProcessResult: ...

    async def run_full(self, cmd: str) -> Any: ...  # noqa: ANN401 - infra SSHCompletedProcess returned through domain Protocol

    async def run_bg(self, cmd: str, *, cwd: str | None = None) -> None: ...

    async def upload(self, local: Path, remote: str) -> None: ...

    def open_sftp(self) -> AbstractAsyncContextManager[SFTPClient]: ...

    async def get_cpu_cores(self) -> int: ...

    async def setup_node(self, engines: EngineRepository) -> None: ...

    def pgrep(
        self, pattern: str | Pattern[str], full: bool = True
    ) -> AsyncGenerator[Any, None]: ...  # noqa: ANN401 - yields infra ProcessInfo through domain Protocol

    def list_processes(self) -> AsyncGenerator[Any, None]: ...  # noqa: ANN401 - yields infra ProcessInfo through domain Protocol

    # ---- Monitor mechanism (generic, Engine-agnostic) ----
    def install_monitor(
        self,
        *,
        interval: float,
        check_factory: Callable[[], Awaitable[bool]],
        on_free: Callable[[], None],
    ) -> None: ...

    def cancel_monitor(self) -> None: ...


@runtime_checkable
class MachineRepository(Protocol):
    """Connected-machine collection — lifecycle and queries."""

    # ---- Collection lifecycle ----
    async def connect(
        self,
        node: Node,
        client_keys: Sequence[PurePath] | None,
        *,
        connect_timeout: int | None = None,
        data_dir: PurePath | None = None,
        engines_dir: PurePath | None = None,
        tasks_dir: PurePath | None = None,
    ) -> MachineSession:
        """Open a session to ``node``."""
        ...

    async def disconnect(self, node_id: NodeId) -> None: ...

    async def disconnect_all(self) -> None: ...

    # ---- Queries ----
    def list_free(self, platforms: list[str] | None) -> list[MachineSession]: ...

    def list_connected(self) -> list[MachineSession]: ...

    def get_session(self, node_id: NodeId) -> MachineSession | None: ...

    def contains(self, node_id: NodeId) -> bool: ...

    def __len__(self) -> int: ...

    def __contains__(self, node_id: NodeId) -> bool: ...


@runtime_checkable
class CloudProvisioner(Protocol):
    """Cloud VM provisioning port. ``allocate``/``deallocate`` are async;
    ``select_provider`` is sync (returns ``None`` when no capacity or throttled).
    ``deallocate`` reads ``node.cloud``/``node.hostname`` and no-ops on ``cloud is None``.
    """

    async def allocate(self, provider: str, node: Node) -> Node: ...

    async def deallocate(self, node: Node) -> None: ...

    def select_provider(
        self, platforms: list[str], current_counts: dict[str, int]
    ) -> str | None: ...

    async def stop(self) -> None: ...

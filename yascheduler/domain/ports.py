"""Domain port interfaces: abstract contracts for persistence, machine collection/sessions, and cloud provisioning."""
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

    async def get(self, task_id: TaskId) -> Task | None:
        """Return a task by ``task_id``, or ``None``."""
        ...

    async def save(self, task: Task) -> None:
        """Persist changes to an existing task aggregate."""
        ...

    async def list_by_status(
        self,
        statuses: set[TaskStatus],
        *,
        limit: int | None = None,
    ) -> list[Task]:
        """Return tasks matching the given statuses with optional limit."""
        ...

    async def insert(self, new_task: NewTask) -> Task:
        """Insert a new node and return it with generated identity."""
        ...

    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]:
        """Return tasks matching the given job IDs."""
        ...

    async def update_status(self, task_id: TaskId, status: TaskStatus) -> None:
        """Update the status of a task by ``task_id``."""
        ...

    async def list_ids_by_node_id_and_status(
        self,
        node_id: NodeId,
        status: TaskStatus,
    ) -> list[TaskId]:
        """Return task IDs for a given node and status."""
        ...

    async def count_by_status(self) -> Mapping[TaskStatus, int]:
        """Return task counts grouped by status."""
        ...


@runtime_checkable
class NodeRepository(Protocol):
    """Async port for node persistence."""

    async def get_by_id(self, node_id: NodeId) -> Node | None:
        """Return a node by ``node_id``, or ``None``."""
        ...

    async def get_by_ids(self, node_ids: list[NodeId]) -> dict[NodeId, Node]:
        """Return a dict of nodes keyed by ``node_id`` for the given IDs."""
        ...

    async def list_enabled(self) -> list[Node]:
        """Return all enabled nodes."""
        ...

    async def list_disabled(self) -> list[Node]:
        """Return all disabled nodes."""
        ...

    async def insert(self, new_node: NewNode) -> Node:
        """Insert a new node and return it with generated identity."""
        ...

    async def update(self, node: Node) -> None:
        """Replace the underlying machine state."""
        ...

    async def enable(self, node_id: NodeId) -> None:
        """Mark a node as enabled."""
        ...

    async def disable(self, node_id: NodeId) -> None:
        """Mark a node as disabled."""
        ...

    async def remove(self, node_id: NodeId) -> None:
        """Remove a node by its ID."""
        ...

    async def list_all(self) -> list[Node]:
        """Return all nodes."""
        ...

    async def count_by_status(self) -> Mapping[bool, int]:
        """Return task counts grouped by status."""
        ...


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
    """Connected-machine entity handle — identity, state transitions.

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
    def hostname(self) -> str:
        """Remote machine hostname (immutable after construction)."""
        ...

    @property
    def machine(self) -> ConnectedMachine:
        """Connected machine runtime state."""
        ...

    @property
    def is_closed(self) -> bool:
        """``True`` when the underlying connection is closed."""
        ...

    def occupy(self) -> None:
        """Transition the underlying machine to ``BUSY``."""
        ...

    def release(self) -> None:
        """Transition the underlying machine to ``FREE``."""
        ...

    def update(self, machine: ConnectedMachine) -> None:
        """Replace the underlying machine state."""
        ...

    # ---- Connect-time config (read-only) ----
    @property
    def adapter(self) -> Any:  # noqa: ANN401
        """Platform-specific remote machine adapter (resolved at connect time)."""
        ...

    @property
    def platforms(self) -> Sequence[str]:
        """Platform tags resolved at connect time."""
        ...

    @property
    def data_dir(self) -> PurePath:
        """Remote data directory path configured at connect time."""
        ...

    @property
    def engines_dir(self) -> PurePath:
        """Remote engines directory path configured at connect time."""
        ...

    @property
    def tasks_dir(self) -> PurePath:
        """Remote tasks directory path configured at connect time."""
        ...

    # ---- Adapter-derived accessors (read-only) ----
    @property
    def path(self) -> type[PurePath]:
        """``PurePath`` subclass matching the remote OS path semantics."""
        ...

    @property
    def quote(self) -> Callable[[str], str]:
        """Shell-quoting callable matching the remote OS syntax."""
        ...

    # ---- Base primitives ----
    async def run(self, cmd: str) -> ProcessResult:
        """Run a command on the remote machine and wait for exit."""
        ...

    async def run_full(self, cmd: str) -> Any:  # noqa: ANN401
        """Run a command and return the full ``SSHCompletedProcess``."""
        ...

    async def run_bg(self, cmd: str, *, cwd: str | None = None) -> None:
        """Create a background process on the remote machine."""
        ...

    async def upload(self, local: Path, remote: str) -> None:
        """Upload a local file to a remote path."""
        ...

    def open_sftp(self) -> AbstractAsyncContextManager[SFTPClient]:
        """Open an SFTP client session."""
        ...

    async def get_cpu_cores(self) -> int:
        """Read the number of CPU cores from the remote machine."""
        ...

    async def setup_node(self, engines: EngineRepository) -> None:
        """Install engines and dependencies on the remote machine."""
        ...

    def pgrep(
        self,
        pattern: str | Pattern[str],
        *,
        full: bool = True,
    ) -> AsyncGenerator[Any, None]:
        """Yield remote processes matching a name or command pattern."""
        ...

    def list_processes(self) -> AsyncGenerator[Any, None]:
        """Yield all remote processes with PID, name, and command line."""
        ...

    # ---- Monitor mechanism (generic, Engine-agnostic) ----
    def install_monitor(
        self,
        *,
        interval: float,
        check_factory: Callable[[], Awaitable[bool]],
        on_free: Callable[[], None],
    ) -> None:
        """Install a periodic check on the remote machine to detect task completion."""
        ...

    def cancel_monitor(self) -> None:
        """Cancel the periodic occupancy monitor."""
        ...


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

    async def disconnect(self, node_id: NodeId) -> None:
        """Close and unregister the session for ``node_id``."""
        ...

    async def disconnect_all(self) -> None:
        """Close and unregister all sessions."""
        ...

    # ---- Queries ----
    def list_free(self, platforms: list[str] | None) -> list[MachineSession]:
        """Return free sessions, optionally filtering by platform."""
        ...

    def list_connected(self) -> list[MachineSession]:
        """Return all currently connected sessions."""
        ...

    def get_session(self, node_id: NodeId) -> MachineSession | None:
        """Return the session for ``node_id``, or ``None``."""
        ...

    def contains(self, node_id: NodeId) -> bool:
        """Return ``True`` if ``node_id`` has an active session."""
        ...

    def __len__(self) -> int: ...

    def __contains__(self, node_id: NodeId) -> bool: ...


@runtime_checkable
class CloudProvisioner(Protocol):
    """Cloud VM provisioning port. ``allocate``/``deallocate`` are async.

    ``select_provider`` is sync (returns ``None`` when no capacity or throttled).
    ``deallocate`` reads ``node.cloud``/``node.hostname`` and no-ops on ``cloud is None``.
    """

    async def allocate(self, provider: str, node: Node) -> Node:
        """Provision a cloud node for the given provider and tmp-node."""
        ...

    async def deallocate(self, node: Node) -> None:
        """Delete a cloud VM identified by ``node.cloud``."""
        ...

    def select_provider(
        self,
        platforms: list[str],
        current_counts: dict[str, int],
    ) -> str | None:
        """Return a provider name with available capacity, or ``None``."""
        ...

    async def stop(self) -> None:
        """Shut down all cloud provider sessions."""
        ...

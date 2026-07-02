# FILE: yascheduler/domain/ports.py
# VERSION: 2.14.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain port interfaces: abstract contracts for persistence, machine collection/sessions/operations, and cloud provisioning.
#   SCOPE: TaskRepository, NodeRepository, MachineRepository, MachineSession, MachineOperations, CloudConfig, CloudProvisioner Protocol classes.
#   DEPENDS: M-DOMAIN-MODEL, M-DOMAIN-ENGINE
#   LINKS: M-DOMAIN-MODEL, M-PERSISTENCE-POSTGRES, M-CLOUD-CONFIGS, M-APPLICATION-DEALLOCATE, M-APPLICATION-ORCHESTRATOR, M-APPLICATION-ABANDON-NODE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskRepository - Async port for task persistence (get, save, insert NewTask→Task, list_by_status, list_by_jobs, update_status, list_ids_by_ip_and_status, count_by_status); get/update_status take TaskId, list_ids_by_ip_and_status returns list[TaskId], list_by_jobs takes list[TaskId]
#   NodeRepository - Async port for node persistence (insert NewNode→Node, get_by_id, full CRUD lifecycle, list_all, get_by_ips, count_by_status); mutators enable/disable/remove take NodeId, update takes Node (keys on node_id); lookups get/get_by_ips/list_* remain ip-keyed / unkeyed
#   CloudConfig - Structural Protocol for cloud provider config (7-field surface application consumers read: prefix, max_nodes, idle_tolerance, connect_grace, username, jump_username, jump_host)
#   MachineRepository - Async port for the connected-machine collection (lifecycle, queries); returns MachineSession; no state transitions/accessors/monitor (moved to MachineSession)
#   MachineSession - Connected-machine entity handle (identity, state transitions, connect-time config, adapter-derived accessors, base primitives, monitor mechanism); Engine-agnostic
#   MachineOperations - Async port for operations on a single machine; methods take session: MachineSession (use-case methods + facade pass-throughs)
#   CloudProvisioner - Async port for cloud node provisioning (allocate returns NewNode, deallocate, select_provider)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.14.0 - NodeRepository mutators rekeyed from ip to node_id (node-id-keyed-mutators): enable(node_id: NodeId), disable(node_id: NodeId), remove(node_id: NodeId); update(node: Node) signature unchanged (already carries node_id; its SQL keys on node_id). Lookup methods get(ip)/get_by_ips/list_* remain ip-keyed / unkeyed (deferred non-goal).
#   PREVIOUS_CHANGE: v2.13.0 - TaskRepository: insert(task: Task) -> Task → insert(new_task: NewTask) -> Task (sole NewTask→Task conversion); get/update_status take TaskId; list_ids_by_ip_and_status returns list[TaskId]; list_by_jobs takes list[TaskId] (add-task-id-identity). The domain is type-safe end-to-end; the public Yascheduler facade is the sole int/TaskId boundary.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path, PurePath
    from re import Pattern

    from asyncssh.sftp import SFTPClient

    from .engine import Engine, EngineRepository
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
    """Async port for task persistence.

    ``insert(new_task: NewTask) -> Task`` is the sole ``NewTask → Task`` conversion
    site (the DB-generated ``TaskId`` lives on the returned ``Task``). ``get``,
    ``update_status``, ``list_ids_by_ip_and_status`` (return), and ``list_by_jobs``
    (input) use ``TaskId`` — the domain is type-safe end-to-end. The public
    ``Yascheduler`` facade is the sole ``int``/``TaskId`` boundary.
    """

    async def get(self, task_id: TaskId) -> Task | None: ...

    async def save(self, task: Task) -> None: ...

    async def list_by_status(
        self, statuses: set[TaskStatus], *, limit: int | None = None
    ) -> list[Task]: ...

    async def insert(self, new_task: NewTask) -> Task: ...

    async def list_by_jobs(self, job_ids: list[TaskId]) -> list[Task]: ...

    async def update_status(self, task_id: TaskId, status: TaskStatus) -> None: ...

    async def list_ids_by_ip_and_status(
        self, ip: str, status: TaskStatus
    ) -> list[TaskId]: ...

    async def count_by_status(self) -> Mapping[TaskStatus, int]: ...


@runtime_checkable
class NodeRepository(Protocol):
    """Async port for node persistence: full CRUD lifecycle.

    ``insert(new_node: NewNode) -> Node`` is the create method (renamed from
    ``add``); it mirrors ``TaskRepository.insert`` by returning the persisted
    ``Node`` carrying the database-generated ``node_id``. ``get_by_id`` is an
    additive lookup by primary key. The four mutators ``enable``,
    ``disable``, ``remove``, and ``update`` key on ``node_id``:
    ``enable``/``disable``/``remove`` take ``NodeId`` directly; ``update``
    takes a ``Node`` (which carries ``node_id``) and the implementation binds
    ``node.node_id.value`` as the SQL key. The lookup methods ``get(ip)``,
    ``get_by_ips(ips)``, and the ``list_*`` methods remain ip-keyed / unkeyed
    — switching them to ``node_id`` is a deferred non-goal (the ip-keyed
    orchestrator queues that feed them must migrate first).
    """

    async def get(self, ip: str) -> Node | None: ...

    async def get_by_id(self, node_id: NodeId) -> Node | None: ...

    async def list_enabled(self) -> list[Node]: ...

    async def list_disabled(self) -> list[Node]: ...

    async def insert(self, new_node: NewNode) -> Node: ...

    async def add_tmp(self, cloud: str) -> str: ...

    async def update(self, node: Node) -> None: ...

    async def enable(self, node_id: NodeId) -> None: ...

    async def disable(self, node_id: NodeId) -> None: ...

    async def remove(self, node_id: NodeId) -> None: ...

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


# START_CONTRACT: MachineSession
#   PURPOSE: Connected-machine entity handle — the public counterpart to the dissolved private _MachineState.
#     Carries domain identity (ip, mutable machine snapshot), connect-time config (read-only),
#     adapter-derived accessors, base SSH primitives, and the per-session monitor mechanism.
#     What MachineOperations methods operate on; what MachineRepository hands out and tracks by IP.
#   INPUTS: { None - Protocol has no inputs }
#   OUTPUTS: { None - Protocol defines surface only }
#   SIDE_EFFECTS: None at Protocol level; implementations own connection teardown via _close (private to concrete class)
#   LINKS: M-DOMAIN-PORTS, M-SSH-SESSION, M-SSH-REPOSITORY, M-SSH-OPERATIONS
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
    def ip(self) -> str: ...

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

    @property
    def hostname(self) -> str: ...

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
    """Connected-machine collection — lifecycle and queries.

    Returns MachineSession from connect/list_free/list_connected/get_session.
    Does NOT declare state transitions (occupy/release/update), accessor
    getters (get_path/get_quote/get_hostname), the monitor mechanism
    (install_monitor/cancel_monitor), or get_machine_state — those are on
    MachineSession. Callers resolve a session via get_session(ip) and read
    session.machine for the snapshot.
    """

    # ---- Collection lifecycle ----
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
    ) -> MachineSession: ...

    async def disconnect(self, ip: str) -> None: ...

    async def disconnect_all(self) -> None: ...

    # ---- Queries ----
    def list_free(self, platforms: list[str] | None) -> list[MachineSession]: ...

    def list_connected(self) -> list[MachineSession]: ...

    def get_session(self, ip: str) -> MachineSession | None: ...

    def contains(self, ip: str) -> bool: ...

    def __len__(self) -> int: ...

    def __contains__(self, ip: str) -> bool: ...


@runtime_checkable
class MachineOperations(Protocol):
    """Operations on a single connected machine — use-case methods plus
    facade pass-throughs. All machine-reference parameters are typed
    `session: MachineSession` (resolved per-tick by the orchestrator via
    `repository.get_session(ip)`).

    Does NOT declare base primitives (run/run_full/run_bg/upload/
    open_sftp/pgrep/list_processes/get_cpu_cores/setup_node) as abstract —
    those live on MachineSession; the facade pass-throughs below delegate
    to them. Does NOT expose upload/get_sftp/pgrep/list_processes —
    collaborators access them via the session parameter.
    """

    # ---- Use-case methods (forwarded to collaborators) ----
    async def start_task_on_machine(
        self,
        session: MachineSession,
        engine: Engine,
        task: Task,
        ncpus: int,
        engines_dir: PurePath,
    ) -> bool: ...

    async def download_outputs(
        self,
        session: MachineSession,
        remote_dir: str,
        local_dir: Path,
        files: list[str],
        task_id: TaskId | None = None,
    ) -> tuple[
        list[tuple[str, Any]],
        list[tuple[str | None, Exception]],
        list[tuple[str | None, Exception]],
    ]: ...

    async def occupancy_check(
        self, session: MachineSession, config: Engine
    ) -> bool: ...

    def start_occupancy_check(
        self, session: MachineSession, config: Engine
    ) -> None: ...

    # ---- Facade pass-throughs (delegate to session.*) ----
    async def run(self, session: MachineSession, cmd: str) -> ProcessResult: ...

    async def run_full(self, session: MachineSession, cmd: str) -> Any: ...  # noqa: ANN401 - infra SSHCompletedProcess returned through domain Protocol

    async def run_bg(
        self, session: MachineSession, cmd: str, *, cwd: str | None = None
    ) -> None: ...

    async def get_cpu_cores(self, session: MachineSession) -> int: ...

    async def setup_node(
        self, session: MachineSession, engines: EngineRepository
    ) -> None: ...


@runtime_checkable
class CloudProvisioner(Protocol):
    """Port for cloud node provisioning.

    ``allocate`` returns a ``NewNode`` (pre-persistence) — a freshly-built VM that
    has NOT been written to ``yascheduler_nodes``. The caller (``allocate_task``)
    persists it via ``NodeRepository.insert(new_node) -> Node``. Provider selection
    is sync (no I/O); ``allocate``/``deallocate`` are async. ``select_provider``
    returns None when no provider has capacity OR when the selected provider is
    throttled (op semaphore locked).
    """

    async def allocate(self, provider: str) -> NewNode: ...

    async def deallocate(self, cloud: str, ip: str) -> None: ...

    def select_provider(
        self, platforms: list[str], current_counts: dict[str, int]
    ) -> str | None: ...

    async def stop(self) -> None: ...

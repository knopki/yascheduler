# FILE: yascheduler/domain/model.py
# VERSION: 1.24.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain entities.
#   SCOPE: Lifecycle state enums, task/node identity and value types, and the public surface consumed by application/infra layers.
#   DEPENDS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE
#   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskStatus - IntEnum: TO_DO=0, RUNNING=1, DONE=2
#   MachineState - Enum: FREE, BUSY
#   NodeStatus - StrEnum: OTHER (placeholder)
#   ProcessResult - Exit code and captured output from remote execution
#   TaskId - Task primary-key value object (frozen dataclass wrapping int; validates >0; __str__ renders bare int)
#   NewTask - Pre-persistence task record
#   Task - Post-persistence task entity
#   materialize_task - Free function attaching TaskCreated to a freshly-inserted Task's events
#   NodeId - Node primary-key value object
#   NewNode - Pre-persistence node record
#   Node - Post-persistence node record
#   ConnectedMachine - Runtime connected machine with state transitions
#   EngineRepository - Frozen collection of engines (re-exported from M-DOMAIN-ENGINE)
#   LocalFilesDeploy / LocalArchiveDeploy / RemoteArchiveDeploy / Deploy - Deploy strategies (re-exported from M-DOMAIN-ENGINE)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.24.0 - Node-rename-and-fields: add NodeStatus(StrEnum) with OTHER value; rename ip→hostname on Node/NewNode/ConnectedMachine; add jump_* / external_id / status / created_at / updated_at fields to Node and NewNode; add node_id to MachineBusyError in occupy(). ConnectedMachine: node_id is first field; MachineBusyError(self.node_id, self.hostname).
#   PREVIOUS_CHANGE: v1.23.0 - Task lifecycle rewritten as five atomic transition methods that each validate the source state, set all changed fields, and emit the matching event inline. Renamed _events -> events. Added materialize_task free function. complete/fail/abandon now set local_folder/remote_folder; reject/fail emit TaskFailed; abandon emits TaskAbandoned only when node_id is not None.
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, IntEnum, unique

from yascheduler.shared import StrEnum

from .engine import (
    Deploy,
    Engine,
    EngineRepository,
    LocalArchiveDeploy,
    LocalFilesDeploy,
    RemoteArchiveDeploy,
)
from .events import (
    DomainEvent,
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from .exceptions import (
    MachineBusyError,
    TaskNotRunningError,
    TaskNotTodoError,
)

# Re-exports from .engine for the canonical import path.
__all__ = [
    "Deploy",
    "Engine",
    "EngineRepository",
    "LocalArchiveDeploy",
    "LocalFilesDeploy",
    "RemoteArchiveDeploy",
]


@unique
class TaskStatus(IntEnum):
    """Task lifecycle states: TO_DO, RUNNING, DONE."""

    TO_DO = 0
    RUNNING = 1
    DONE = 2


@unique
class MachineState(Enum):
    """Machine occupancy states: FREE, BUSY."""

    FREE = 1
    BUSY = 2


@unique
class NodeStatus(StrEnum):
    """Node lifecycle states: OTHER (placeholder for future states)."""

    OTHER = "OTHER"


@dataclass(frozen=True)
class ProcessResult:
    """Exit code and captured output from a remote process execution."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""


# START_CONTRACT: TaskId
#   PURPOSE: Task primary-key value object — frozen dataclass wrapping int; validates >0; __str__ renders bare int.
#   INPUTS: { value: int - the database-generated task_id (SERIAL starts at 1) }
#   OUTPUTS: { None - raises ValueError in __post_init__ when value <= 0 }
#   SIDE_EFFECTS: None
#   RAISES: ValueError - when value <= 0 (a non-positive id indicates a bug)
#   LINKS: M-DOMAIN-MODEL
# END_CONTRACT: TaskId
@dataclass(frozen=True)
class TaskId:
    """Task primary-key value object.

    Wraps a single ``value: int`` (the DB-generated ``task_id``). ``__post_init__``
    enforces ``value > 0`` (SERIAL starts at 1, so a non-positive value indicates a
    bug). ``__str__`` returns the bare integer string so CLI rendering and logging
    produce ``5``, not ``TaskId(value=5)``. Frozen → hashable → usable as a dict key.
    Intentionally NOT equal to a bare ``int`` (``TaskId(5) == 5`` is ``False``) — the
    type-safety point of a dedicated value object; callers must unwrap ``.value``
    explicitly at external boundaries (pg8000 params, JSON, argparse).
    """

    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError(f"TaskId must be > 0, got {self.value}")

    def __str__(self) -> str:
        return str(self.value)


# START_CONTRACT: NewTask
#   PURPOSE: Pre-persistence task record — no identity yet; converted to Task only by TaskRepository.insert.
#   INPUTS: { label: str, engine: str, local_folder: str | None, webhook_url: str | None, webhook_custom_params: dict, extra: dict, status: TaskStatus, allocated_node_id: NodeId | None }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: TaskRepository.insert
# END_CONTRACT: NewTask
@dataclass(frozen=True)
class NewTask:
    """Pre-persistence task record — no identity yet.

    A caller builds a ``NewTask`` to prepare a task for insertion.
    It is a pure data carrier with no lifecycle methods.
    """

    engine: str
    label: str = ""
    local_folder: str | None = None
    webhook_url: str | None = None
    webhook_custom_params: dict[str, object] = field(default_factory=dict)
    extra: dict[str, object] = field(default_factory=dict)


# START_CONTRACT: Task
#   PURPOSE: Post-persistence task entity — always carries its database-generated task_id and a status lifecycle expressed as atomic transition methods.
#   INPUTS: { task_id: TaskId, label: str, engine: str, remote_folder: str | None, local_folder: str | None, webhook_url: str | None, webhook_custom_params: dict, error: str | None, extra: dict, created_at: datetime, updated_at: datetime, status: TaskStatus, allocated_node_id: NodeId | None, events: tuple }
#   OUTPUTS: { None }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS, M-DOMAIN-EVENTS, M-DOMAIN-EXCEPTIONS
# END_CONTRACT: Task
@dataclass(frozen=True)
class Task:
    """Post-persistence task entity with atomic lifecycle transitions.

    Every state change happens through one of transition methods
    that validates the source state, sets all fields that
    change, constructs and appends the matching :class:`DomainEvent` to
    ``events``, and returns a new ``Task`` via :func:`replace`. No method
    leaves the entity in a semantically-empty intermediate state.

    ``allocated_node_id`` is the sole allocation signal: it is ``None`` for
    unallocated tasks (TO_DO with no node bound) and for tasks whose node was
    deleted.

    ``events`` is a public field; the UoW reads it directly.
    ``remote_folder`` is ``None`` on a freshly-inserted
    TO_DO task; it is set by :meth:`run` when the task transitions to RUNNING.
    ``local_folder`` is ``None`` until :meth:`complete` or :meth:`fail` sets it
    from the download results. ``error`` is ``None`` until :meth:`reject`,
    :meth:`fail`, or :meth:`abandon` sets it.

    ``created_at``/``updated_at`` default to ``datetime.now()`` mirroring the
    DB schema (``DEFAULT NOW()``.
    The DB always overrides them via RETURNING on insert and on every read.
    """

    task_id: TaskId
    engine: str
    created_at: datetime = field(default_factory=lambda: datetime.now())
    updated_at: datetime = field(default_factory=lambda: datetime.now())
    label: str = ""
    local_folder: str | None = None
    remote_folder: str | None = None
    webhook_url: str | None = None
    webhook_custom_params: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    status: TaskStatus = TaskStatus.TO_DO
    extra: dict[str, object] = field(default_factory=dict)
    allocated_node_id: NodeId | None = None
    events: tuple[DomainEvent, ...] = field(default=(), repr=True)

    # START_CONTRACT: Task.run
    #   PURPOSE: Transition TO_DO→RUNNING, bind to a node, set remote_folder, and emit TaskAllocated inline.
    #   INPUTS: { node_id: NodeId - the node to bind, remote_folder: str - the remote execution path }
    #   OUTPUTS: { Task - new Task  }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotTodoError - if status is not TO_DO
    #   LINKS: M-DOMAIN-EXCEPTIONS: TaskNotTodoError, M-DOMAIN-EVENTS: TaskAllocated
    # END_CONTRACT: Task.run
    def run(self, node_id: NodeId, remote_folder: str) -> Task:
        """Transition TO_DO→RUNNING, binding the node and setting remote_folder."""
        # START_BLOCK_VALIDATE_TODO
        if self.status != TaskStatus.TO_DO:
            raise TaskNotTodoError(self.task_id)
        # END_BLOCK_VALIDATE_TODO
        # START_BLOCK_APPLY_RUN
        event = TaskAllocated(
            task_id=self.task_id,
            webhook_url=self.webhook_url,
            webhook_custom_params=self.webhook_custom_params,
            node_id=node_id,
            engine_name=self.engine,
        )
        return replace(
            self,
            allocated_node_id=node_id,
            remote_folder=remote_folder,
            status=TaskStatus.RUNNING,
            events=self.events + (event,),
        )
        # END_BLOCK_APPLY_RUN

    # START_CONTRACT: Task.reject
    #   PURPOSE: Transition TO_DO→DONE with an error reason and emit TaskFailed inline.
    #   INPUTS: { reason: str - rejection description }
    #   OUTPUTS: { Task - new Task with status=DONE, error set, and TaskFailed appended to events }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotTodoError - if status is not TO_DO
    #   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS
    # END_CONTRACT: Task.reject
    def reject(self, reason: str) -> Task:
        """Transition TO_DO→DONE with an error reason (e.g. unsupported engine)."""
        # START_BLOCK_VALIDATE_TODO
        if self.status != TaskStatus.TO_DO:
            raise TaskNotTodoError(self.task_id)
        # END_BLOCK_VALIDATE_TODO
        # START_BLOCK_APPLY_REJECT
        event = TaskFailed(
            task_id=self.task_id,
            webhook_url=self.webhook_url,
            webhook_custom_params=self.webhook_custom_params,
            reason=reason,
        )
        return replace(
            self,
            status=TaskStatus.DONE,
            error=reason,
            events=self.events + (event,),
        )
        # END_BLOCK_APPLY_REJECT

    # START_CONTRACT: Task.complete
    #   PURPOSE: Transition RUNNING→DONE with download folders and emit TaskCompleted inline.
    #   INPUTS: { local_folder: str - local output path (keyword-only), remote_folder: str - remote output path (keyword-only) }
    #   OUTPUTS: { Task - new Task with status=DONE, local_folder and remote_folder set, and TaskCompleted appended to events }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotRunningError - if status is not RUNNING
    #   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS
    # END_CONTRACT: Task.complete
    def complete(self, *, local_folder: str, remote_folder: str) -> Task:
        """Transition RUNNING→DONE on successful completion, setting folders."""
        # START_BLOCK_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_VALIDATE_RUNNING
        # START_BLOCK_APPLY_COMPLETE
        event = TaskCompleted(
            task_id=self.task_id,
            webhook_url=self.webhook_url,
            webhook_custom_params=self.webhook_custom_params,
            local_folder=local_folder,
        )
        return replace(
            self,
            status=TaskStatus.DONE,
            local_folder=local_folder,
            remote_folder=remote_folder,
            events=self.events + (event,),
        )
        # END_BLOCK_APPLY_COMPLETE

    # START_CONTRACT: Task.fail
    #   PURPOSE: Transition RUNNING→DONE with an error reason and partial download folders, emitting TaskFailed.
    #   INPUTS: { reason: str - failure description, local_folder: str - local output path (keyword-only), remote_folder: str - remote output path (keyword-only) }
    #   OUTPUTS: { Task - new Task with status=DONE, error/local_folder/remote_folder set, and TaskFailed appended to events }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotRunningError - if status is not RUNNING
    #   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS
    # END_CONTRACT: Task.fail
    def fail(self, reason: str, *, local_folder: str, remote_folder: str) -> Task:
        """Transition RUNNING→DONE on failure, setting error and partial folders."""
        # START_BLOCK_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_VALIDATE_RUNNING
        # START_BLOCK_APPLY_FAIL
        event = TaskFailed(
            task_id=self.task_id,
            webhook_url=self.webhook_url,
            webhook_custom_params=self.webhook_custom_params,
            reason=reason,
        )
        return replace(
            self,
            status=TaskStatus.DONE,
            error=reason,
            local_folder=local_folder,
            remote_folder=remote_folder,
            events=self.events + (event,),
        )
        # END_BLOCK_APPLY_FAIL

    # START_CONTRACT: Task.abandon
    #   PURPOSE: Transition RUNNING→DONE with an error when the node disappeared, emitting TaskAbandoned only when node_id is not None.
    #   INPUTS: { node_id: NodeId | None - the node to abandon, error: str - failure description }
    #   OUTPUTS: { Task - new Task }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotRunningError - if status is not RUNNING
    #   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS
    # END_CONTRACT: Task.abandon
    def abandon(self, node_id: NodeId | None, error: str = "node is gone") -> Task:
        """Transition RUNNING→DONE when the node disappeared."""
        # START_BLOCK_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_VALIDATE_RUNNING
        # START_BLOCK_APPLY_ABANDON
        new_events = self.events
        if node_id is not None:
            event = TaskAbandoned(
                task_id=self.task_id,
                webhook_url=self.webhook_url,
                webhook_custom_params=self.webhook_custom_params,
                node_id=node_id,
            )
            new_events = new_events + (event,)
        return replace(
            self,
            status=TaskStatus.DONE,
            error=error,
            events=new_events,
        )
        # END_BLOCK_APPLY_ABANDON


# START_CONTRACT: materialize_task
#   PURPOSE: Attach a TaskCreated event to a freshly-inserted Task's events.
#   INPUTS: { task: Task - the freshly-inserted Task }
#   OUTPUTS: { Task - new Task with one TaskCreated }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-PORTS
# END_CONTRACT: materialize_task
def materialize_task(task: Task) -> Task:
    """Return a Task with a TaskCreated event appended to events."""
    event = TaskCreated(
        task_id=task.task_id,
        webhook_url=task.webhook_url,
        webhook_custom_params=task.webhook_custom_params,
        engine_name=task.engine,
    )
    return replace(task, events=(event,))


# START_CONTRACT: NodeId
#   PURPOSE: Node primary-key value object — frozen dataclass wrapping int; validates >0; __str__ renders bare int.
#   INPUTS: { value: int - the database-generated node_id (SERIAL starts at 1) }
#   OUTPUTS: { None - raises ValueError in __post_init__ when value <= 0 }
#   SIDE_EFFECTS: None
#   RAISES: ValueError - when value <= 0 (a non-positive id indicates a bug)
#   LINKS: M-DOMAIN-MODEL
# END_CONTRACT: NodeId
@dataclass(frozen=True)
class NodeId:
    """Node primary-key value object.

    Wraps a single ``value: int`` (the DB-generated ``node_id``). ``__post_init__``
    enforces ``value > 0`` (SERIAL starts at 1, so a non-positive value indicates a
    bug). ``__str__`` returns the bare integer string so CLI rendering and logging
    produce ``5``, not ``NodeId(value=5)``. Frozen → hashable → usable as a dict key.
    Intentionally NOT equal to a bare ``int`` (``NodeId(5) == 5`` is ``False``) — the
    type-safety point of a dedicated value object; callers must unwrap ``.value``
    explicitly at external boundaries (pg8000 params, JSON, argparse).
    """

    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError(f"NodeId must be > 0, got {self.value}")

    def __str__(self) -> str:
        return str(self.value)


# START_CONTRACT: NewNode
#   PURPOSE: Pre-persistence node record — no identity yet; converted to Node only by NodeRepository.insert.
#   INPUTS: { hostname, ncpus, enabled, cloud, username, port, jump_host, jump_port, jump_username, external_id, status }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: NodeRepository.insert
# END_CONTRACT: NewNode
@dataclass(frozen=True)
class NewNode:
    """Pre-persistence node record — no identity yet. Mirrors :class:`Node`
    minus ``node_id``.
    """

    enabled: bool = True
    status: NodeStatus = NodeStatus.OTHER
    hostname: str = ""
    username: str = "root"
    port: int = 22
    jump_host: str | None = None
    jump_port: int = 22
    jump_username: str = "root"
    ncpus: int = 0
    cloud: str | None = None
    external_id: str | None = None


# START_CONTRACT: Node
#   PURPOSE: Post-persistence node record — always carries its database-generated node_id (identity-first).
#   INPUTS: { node_id: NodeId, hostname: str, ncpus: int, enabled: bool, cloud: str | None, username: str, port: int, jump_host: str | None, jump_port: int, jump_username: str, external_id: str | None, status: NodeStatus, created_at: datetime, updated_at: datetime }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: NodeRepository.insert (the only NewNode→Node conversion site)
# END_CONTRACT: Node
@dataclass(frozen=True)
class Node:
    """Post-persistence node record — always carries its identity.

    ``node_id`` is the FIRST field (identity first); a ``Node`` only ever comes from
    the database.
    """

    node_id: NodeId
    hostname: str
    ncpus: int
    created_at: datetime = field(default_factory=lambda: datetime.now())
    updated_at: datetime = field(default_factory=lambda: datetime.now())
    username: str = "root"
    port: int = 22
    jump_host: str | None = None
    jump_port: int = 22
    jump_username: str = "root"
    enabled: bool = True
    status: NodeStatus = NodeStatus.OTHER
    cloud: str | None = None
    external_id: str | None = None


@dataclass(frozen=True)
class ConnectedMachine:
    """Runtime connected machine with state and platform info.

    ``node_id`` identifies which :class:`Node` this connected machine represents.
    """

    node_id: NodeId
    hostname: str
    platform: str
    ncpus: int
    state: MachineState = MachineState.FREE
    free_since: float | None = None

    # START_CONTRACT: ConnectedMachine.is_compatible
    #   PURPOSE: Check if machine is FREE and its platform matches one of the given platforms.
    #   INPUTS: { platforms - Supported platform identifiers }
    #   OUTPUTS: { bool - True if FREE and platform matches, False otherwise }
    #   SIDE_EFFECTS: None
    #   LINKS:
    # END_CONTRACT: ConnectedMachine.is_compatible
    def is_compatible(self, platforms: tuple[str, ...]) -> bool:
        """Check if machine is FREE and platform matches given platforms."""
        return self.state == MachineState.FREE and self.platform in platforms

    # START_CONTRACT: ConnectedMachine.occupy
    #   PURPOSE: Transition machine state to BUSY if currently FREE.
    #   INPUTS: { None }
    #   OUTPUTS: { ConnectedMachine - New instance with state=BUSY }
    #   SIDE_EFFECTS: None
    #   RAISES: MachineBusyError - if already BUSY
    #   LINKS: M-DOMAIN-EXCEPTIONS: MachineBusyError
    # END_CONTRACT: ConnectedMachine.occupy
    def occupy(self) -> ConnectedMachine:
        """Transition machine state to BUSY if currently FREE."""
        # START_BLOCK_VALIDATE_FREE
        if self.state == MachineState.BUSY:
            raise MachineBusyError(self.node_id, self.hostname)
        # END_BLOCK_VALIDATE_FREE
        # START_BLOCK_SET_BUSY
        return replace(self, state=MachineState.BUSY)
        # END_BLOCK_SET_BUSY

    # START_CONTRACT: ConnectedMachine.release
    #   PURPOSE: Transition machine state to FREE and record release timestamp.
    #   INPUTS: { None }
    #   OUTPUTS: { ConnectedMachine - New instance with state=FREE and free_since set }
    #   SIDE_EFFECTS: None
    #   LINKS:
    # END_CONTRACT: ConnectedMachine.release
    def release(self) -> ConnectedMachine:
        """Transition machine state to FREE and record release timestamp."""
        return replace(self, state=MachineState.FREE, free_since=time.monotonic())

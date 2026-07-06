# FILE: yascheduler/domain/model.py
# VERSION: 1.22.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain entities.
#   SCOPE: TaskStatus, MachineState enums; ProcessResult value object; TaskId, NewTask, Task, NewNode, Node, NodeId, ConnectedMachine entities; re-export Engine, EngineRepository, Deploy* from .engine for backward compatibility.
#   DEPENDS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE
#   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskStatus - IntEnum: TO_DO=0, RUNNING=1, DONE=2
#   MachineState - Enum: FREE, BUSY
#   ProcessResult - Exit code and captured output from remote execution
#   TaskId - Task primary-key value object (frozen dataclass wrapping int; validates >0; __str__ renders bare int)
#   NewTask - Pre-persistence task record
#   Task - Post-persistence task entity
#   NodeId - Node primary-key value object
#   NewNode - Pre-persistence node record
#   Node - Post-persistence node record
#   ConnectedMachine - Runtime connected machine with state transitions
#   EngineRepository - Frozen collection of engines (re-exported from M-DOMAIN-ENGINE)
#   LocalFilesDeploy / LocalArchiveDeploy / RemoteArchiveDeploy / Deploy - Deploy strategies (re-exported from M-DOMAIN-ENGINE)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.22.0 - drop-task-context-entity: TaskContext / TaskContextOverrides; typed fields folded onto Task / NewTask; Task.fail/reject simplified to direct replace(status=DONE, error=reason); new Task.with_remote_folder and Task.with_download_results methods; with_event reads self.webhook_url / self.webhook_custom_params directly.
#   PREVIOUS_CHANGE: v1.21.0 - task-schema-and-entity-cleanup: Task/NewTask drop allocated_ip; Task gains created_at/updated_at: datetime
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, IntEnum, unique
from typing import TypeVar, overload

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
    TaskAlreadyAllocatedError,
    TaskNotAllocatedError,
    TaskNotRunningError,
    TaskNotTodoError,
)

# Re-exports from .engine for backward compatibility with
# `from yascheduler.domain.model import Engine` / EngineRepository / Deploy*.
__all__ = [
    "Deploy",
    "Engine",
    "EngineRepository",
    "LocalArchiveDeploy",
    "LocalFilesDeploy",
    "RemoteArchiveDeploy",
]

_E = TypeVar("_E", bound=DomainEvent)


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
#   PURPOSE: Post-persistence task entity — always carries its database-generated task_id (identity-first) and a status lifecycle.
#   INPUTS: { task_id: TaskId, label: str, engine: str, remote_folder: str | None, local_folder: str | None, webhook_url: str | None, webhook_custom_params: dict, error: str | None, extra: dict, created_at: datetime, updated_at: datetime, status: TaskStatus, allocated_node_id: NodeId | None, _events: tuple }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: TaskRepository.insert (the only NewTask→Task conversion site)
# END_CONTRACT: Task
@dataclass(frozen=True)
class Task:
    """Post-persistence task entity with lifecycle methods and allocation state.

    ``allocated_node_id`` is the sole allocation signal: it is ``None`` for
    unallocated tasks (TO_DO with no node bound) and for tasks whose node was
    deleted (the DB FK is ``ON DELETE SET NULL``). It is set by
    :meth:`allocate_to`.

    ``created_at``/``updated_at`` default to ``datetime.now()`` mirroring the
    DB schema (``DEFAULT NOW()``; ``updated_at`` is advanced by the
    ``yascheduler_tasks_touch_updated_at`` BEFORE UPDATE trigger).
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
    _events: tuple[DomainEvent, ...] = field(default=(), repr=False)

    # START_CONTRACT: Task.allocate_to
    #   PURPOSE: Bind task to a Node if not already allocated — sets allocated_node_id in one replace() call.
    #   INPUTS: { node: Node - the node to bind (carries node_id) }
    #   OUTPUTS: { Task - new Task with allocated_node_id set }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskAlreadyAllocatedError - if already allocated (guard checks self.allocated_node_id is not None)
    #   LINKS: M-DOMAIN-EXCEPTIONS: TaskAlreadyAllocatedError
    # END_CONTRACT: Task.allocate_to
    def allocate_to(self, node: Node) -> Task:
        """Bind task to a node, raising TaskAlreadyAllocatedError if already allocated."""
        # START_BLOCK_VALIDATE_NOT_ALLOCATED
        if self.allocated_node_id is not None:
            raise TaskAlreadyAllocatedError(self.task_id)
        # END_BLOCK_VALIDATE_NOT_ALLOCATED
        # START_BLOCK_APPLY_ALLOCATION
        return replace(self, allocated_node_id=node.node_id)
        # END_BLOCK_APPLY_ALLOCATION

    # START_CONTRACT: Task.mark_running
    #   PURPOSE: Transition task status to RUNNING.
    #   INPUTS: { None }
    #   OUTPUTS: { Task - New Task instance with status=RUNNING }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotAllocatedError - if not yet allocated to a node; TaskNotTodoError - if status is not TO_DO
    #   LINKS:
    # END_CONTRACT: Task.mark_running
    def mark_running(self) -> Task:
        """Transition task status to RUNNING."""
        # START_BLOCK_VALIDATE_STATE
        if self.allocated_node_id is None:
            raise TaskNotAllocatedError(self.task_id)
        if self.status != TaskStatus.TO_DO:
            raise TaskNotTodoError(self.task_id)
        # END_BLOCK_VALIDATE_STATE
        return replace(self, status=TaskStatus.RUNNING)

    # START_CONTRACT: Task.complete
    #   PURPOSE: Mark task as DONE if currently RUNNING.
    #   INPUTS: { None }
    #   OUTPUTS: { Task - New Task instance with status=DONE }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-EXCEPTIONS: TaskNotRunningError
    # END_CONTRACT: Task.complete
    def complete(self) -> Task:
        """Mark task as DONE if currently RUNNING."""
        # START_BLOCK_COMPLETE_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_COMPLETE_VALIDATE_RUNNING
        return replace(self, status=TaskStatus.DONE)

    # START_CONTRACT: Task.fail
    #   PURPOSE: Mark task as DONE with error reason if currently RUNNING.
    #   INPUTS: { reason: str - Failure description }
    #   OUTPUTS: { Task - New Task instance with status=DONE and error set }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotRunningError - if not RUNNING
    #   LINKS: M-DOMAIN-EXCEPTIONS: TaskNotRunningError
    # END_CONTRACT: Task.fail
    def fail(self, reason: str) -> Task:
        """Mark task as DONE with error reason if currently RUNNING."""
        # START_BLOCK_FAIL_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_FAIL_VALIDATE_RUNNING
        # START_BLOCK_MARK_FAILED
        return replace(self, status=TaskStatus.DONE, error=reason)
        # END_BLOCK_MARK_FAILED

    # START_CONTRACT: Task.reject
    #   PURPOSE: Mark a TO_DO task as DONE with error reason (e.g. unsupported engine).
    #   INPUTS: { reason: str - Rejection description }
    #   OUTPUTS: { Task - New Task instance with status=DONE and error set }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskNotTodoError - if not TO_DO
    #   LINKS: M-DOMAIN-EXCEPTIONS: TaskNotTodoError
    # END_CONTRACT: Task.reject
    def reject(self, reason: str) -> Task:
        """Mark a TO_DO task as DONE with error reason."""
        # START_BLOCK_VALIDATE_TODO
        if self.status != TaskStatus.TO_DO:
            raise TaskNotTodoError(self.task_id)
        # END_BLOCK_VALIDATE_TODO
        # START_BLOCK_MARK_REJECTED
        return replace(self, status=TaskStatus.DONE, error=reason)
        # END_BLOCK_MARK_REJECTED

    # START_CONTRACT: Task.record_event
    #   PURPOSE: Append a domain event to the task's event tuple, returning a new Task.
    #   INPUTS: { event: DomainEvent }
    #   OUTPUTS: { Task - New instance with event appended to _events }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-EVENTS
    # END_CONTRACT: Task.record_event
    def record_event(self, event: DomainEvent) -> Task:
        return replace(self, _events=self._events + (event,))

    # START_CONTRACT: Task.with_remote_folder
    #   PURPOSE: Set remote_folder post-insert
    #   INPUTS: { remote_folder: str - the remote path assigned to the task }
    #   OUTPUTS: { Task - new Task with remote_folder set }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-MODEL
    # END_CONTRACT: Task.with_remote_folder
    def with_remote_folder(self, remote_folder: str) -> Task:
        """Return a new Task with remote_folder set (submit-time copy-with)."""
        return replace(self, remote_folder=remote_folder)

    # START_CONTRACT: Task.with_download_results
    #   PURPOSE: Set local_folder and remote_folder post-download.
    #   INPUTS: { local_folder: str - local output path (keyword-only), remote_folder: str - remote output path (keyword-only) }
    #   OUTPUTS: { Task - new Task with local_folder and remote_folder set }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-MODEL
    # END_CONTRACT: Task.with_download_results
    def with_download_results(self, *, local_folder: str, remote_folder: str) -> Task:
        """Return a new Task with local_folder and remote_folder set"""
        return replace(self, local_folder=local_folder, remote_folder=remote_folder)

    # START_CONTRACT: Task.with_event
    #   PURPOSE: Construct an event of the given type with base fields (task_id, webhook_url, webhook_custom_params) populated from the typed task fields and subclass-specific fields from the caller, then append via record_event.
    #   INPUTS: {
    #     event_type: type[E] - Concrete event subclass to construct,
    #     **fields: object - Subclass-specific fields (keyword-only via overloads); any base fields passed are silently dropped
    #   }
    #   OUTPUTS: { Task - New instance with the constructed event appended to _events }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-EVENTS
    # END_CONTRACT: Task.with_event
    @overload
    def with_event(
        self, event_type: type[TaskCreated], *, engine_name: str
    ) -> Task: ...
    @overload
    def with_event(
        self, event_type: type[TaskAllocated], *, node_id: NodeId, engine_name: str
    ) -> Task: ...
    @overload
    def with_event(
        self, event_type: type[TaskCompleted], *, local_folder: str, has_errors: bool
    ) -> Task: ...
    @overload
    def with_event(self, event_type: type[TaskFailed], *, reason: str) -> Task: ...
    @overload
    def with_event(
        self, event_type: type[TaskAbandoned], *, node_id: NodeId
    ) -> Task: ...
    def with_event(self, event_type: type[_E], **fields: object) -> Task:
        # START_BLOCK_DROP_BASE_FIELDS
        fields.pop("task_id", None)
        fields.pop("webhook_url", None)
        fields.pop("webhook_custom_params", None)
        # END_BLOCK_DROP_BASE_FIELDS
        # START_BLOCK_CONSTRUCT_AND_RECORD
        event = event_type(
            task_id=self.task_id,
            webhook_url=self.webhook_url,
            webhook_custom_params=self.webhook_custom_params,
            **fields,
        )
        return self.record_event(event)
        # END_BLOCK_CONSTRUCT_AND_RECORD

    # START_CONTRACT: Task.pull_events
    #   PURPOSE: Extract accumulated events, returning a clean Task and the event tuple.
    #   INPUTS: { None }
    #   OUTPUTS: { tuple[Task, tuple[DomainEvent, ...]] - (clean_task, collected_events) }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-EVENTS
    # END_CONTRACT: Task.pull_events
    def pull_events(self) -> tuple[Task, tuple[DomainEvent, ...]]:
        return replace(self, _events=()), self._events


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
#   INPUTS: { ip: str = "", ncpus: int = 0, enabled: bool = True, cloud: str | None = None, username: str = "root", port: int = 22 }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: NodeRepository.insert
# END_CONTRACT: NewNode
@dataclass(frozen=True)
class NewNode:
    """Pre-persistence node record — no identity yet. Mirrors :class:`Node`
    minus ``node_id``. ``ip``/``ncpus`` default so the tmp-reservation call
    site omits them; converted to :class:`Node` only by
    :meth:`NodeRepository.insert`.
    """

    ip: str = ""
    ncpus: int = 0
    enabled: bool = True  # FIXME: should be False
    cloud: str | None = None
    username: str = "root"
    port: int = 22


# START_CONTRACT: Node
#   PURPOSE: Post-persistence node record — always carries its database-generated node_id (identity-first).
#   INPUTS: { node_id: NodeId, ip: str, ncpus: int, enabled: bool, cloud: str | None, username: str, port: int }
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
    ip: str
    ncpus: int
    enabled: bool = True
    cloud: str | None = None
    username: str = "root"
    port: int = 22


@dataclass(frozen=True)
class ConnectedMachine:
    """Runtime connected machine with state and platform info.

    ``node_id`` is the FIRST field (identity first); it identifies which
    :class:`Node` this connected machine represents. ``occupy``/``release``/
    ``replace()`` carry ``node_id`` through automatically (frozen dataclass —
    ``replace(self, state=…)`` preserves all non-overridden fields, including
    ``node_id``). The construction site is ``SSHMachineRepository._connect_impl``,
    which passes ``node_id=node.node_id`` from the ``Node`` parameter of
    ``connect``.

    ``ip`` is the transport address (the asyncssh host), NOT the identity — two
    instances sharing an ``ip`` but with different ``node_id`` are distinct (the
    dup-IP configuration behind different jump hosts).
    """

    node_id: NodeId
    # FIXME: why ip is here but not port, username, etc? maybe ip is not needed?
    ip: str
    platform: str
    ncpus: int
    state: MachineState = MachineState.FREE
    free_since: float | None = None

    # START_CONTRACT: ConnectedMachine.is_compatible
    #   PURPOSE: Check if machine is FREE and its platform matches one of the given platforms.
    #   INPUTS: { platforms: tuple[str, ...] - Supported platform identifiers }
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
            raise MachineBusyError(self.ip)
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

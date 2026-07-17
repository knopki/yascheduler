"""Domain entities."""
# region MODULE_CONTRACT
# PURPOSE: Encode the scheduler's core vocabulary — task and node entities, lifecycle state, and value objects — as immutable data with atomic transitions, so business rules are enforced in one place and shared safely across async components.
# SCOPE:
# - Lifecycle enums (TaskStatus, MachineState, NodeStatus) and ProcessResult; identity value objects TaskId/NodeId; pre/post-persistence records NewTask/Task, NewNode/Node; the ConnectedMachine runtime entity.
# - NOT: persistence ports (domain.ports), events (domain.events), or exceptions (domain.exceptions).
# INVARIANTS: Entities are frozen; every state change happens through transition methods that validate the source state, mutate via replace, and append the matching DomainEvent to events.
# RATIONALE:
# - Q: Why dedicated value objects (TaskId/NodeId) instead of bare int?
#   A: Type safety — callers must unwrap .value at external boundaries (pg8000, JSON, argparse), preventing accidental mixing of ids with plain ints.
# - Q: Why frozen dataclasses with replace-based transitions?
#   A: Async-safe sharing — a task aggregate can be handed to concurrent coroutines without locks, since every change produces a new instance.
# KEYWORDS: task, node, machine, lifecycle, value object, entity, allocation, ConnectedMachine
# endregion MODULE_CONTRACT

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

# Module public API: own entities/value objects + engine re-exports for the canonical import path.
__all__ = [
    "ConnectedMachine",
    "Deploy",
    "Engine",
    "EngineRepository",
    "LocalArchiveDeploy",
    "LocalFilesDeploy",
    "MachineState",
    "NewNode",
    "NewTask",
    "Node",
    "NodeId",
    "NodeStatus",
    "ProcessResult",
    "RemoteArchiveDeploy",
    "Task",
    "TaskId",
    "TaskStatus",
    "materialize_task",
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


# region CLASS_TaskId
# PURPOSE: Wrap the database task id in a dedicated value object so transport/serialization boundaries must unwrap it explicitly, preventing accidental mixing with bare ints.
# INVARIANTS: value > 0; frozen and hashable; not equal to a bare int.
# RATIONALE:
# - Q: Why a dedicated type instead of bare int, NewType('TaskId', int), or int subclass?
#   A: A frozen dataclass wrapper enforces explicit .value unwrapping at every external boundary, preventing accidental id/int mixing that NewType wouldn't catch at runtime and an int subclass wouldn't prevent.
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
            msg = f"TaskId must be > 0, got {self.value}"
            raise ValueError(msg)

    def __str__(self) -> str:
        return str(self.value)


# endregion CLASS_TaskId


# region CLASS_NewTask
# PURPOSE: Carry the fields needed to insert a task before it has a database id, with no lifecycle methods — a pure data carrier.
# INVARIANTS: No identity (task_id absent); no events, status, allocated_node_id, remote_folder, error, created_at/updated_at — these are all supplied post-insert by the DB or by Task transition methods.
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


# endregion CLASS_NewTask


# region CLASS_Task
# PURPOSE: Represent a persisted task as an immutable aggregate whose status only changes through atomic transition methods, so invariants and event emission stay centralized.
# INVARIANTS: Every transition validates the source status, returns a new Task via replace, and appends the matching DomainEvent to events; allocated_node_id is the sole allocation signal. No intermediate-state mutators exist.
# RATIONALE:
# - Q: Why does allocated_node_id cover both "unallocated" and "node was deleted"?
#   A: Both states mean "no node currently assigned" — the distinction is irrelevant at the entity level; the node-resolved transport address comes from NodeRepository, not from Task.
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
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
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

    # region METHOD_run
    # PURPOSE: Bind the task to a node and begin remote execution, recording the allocation as an event.
    # REQUIRES: status is TO_DO.
    def run(self, node_id: NodeId, remote_folder: str) -> Task:
        """Transition TO_DO→RUNNING, binding the node and setting remote_folder."""
        if self.status != TaskStatus.TO_DO:
            raise TaskNotTodoError(self.task_id)
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
            events=(*self.events, event),
        )

    # endregion METHOD_run

    # region METHOD_reject
    # PURPOSE: Terminate a not-yet-started task with a reason (e.g. unsupported engine) without ever running it.
    # REQUIRES: status is TO_DO.
    def reject(self, reason: str) -> Task:
        """Transition TO_DO→DONE with an error reason (e.g. unsupported engine)."""
        if self.status != TaskStatus.TO_DO:
            raise TaskNotTodoError(self.task_id)
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
            events=(*self.events, event),
        )

    # endregion METHOD_reject

    # region METHOD_complete
    # PURPOSE: Finalize a running task on success, capturing output folders and emitting TaskCompleted.
    # REQUIRES: status is RUNNING.
    def complete(self, *, local_folder: str, remote_folder: str) -> Task:
        """Transition RUNNING→DONE on successful completion, setting folders."""
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
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
            events=(*self.events, event),
        )

    # endregion METHOD_complete

    # region METHOD_fail
    # PURPOSE: End a running task on failure, recording the reason and whatever partial output was downloaded.
    # REQUIRES: status is RUNNING.
    def fail(self, reason: str, *, local_folder: str, remote_folder: str) -> Task:
        """Transition RUNNING→DONE on failure, setting error and partial folders."""
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
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
            events=(*self.events, event),
        )

    # endregion METHOD_fail

    # region METHOD_abandon
    # PURPOSE: Stop a running task whose node disappeared, emitting TaskAbandoned only when a concrete node_id is supplied.
    # REQUIRES: status is RUNNING.
    def abandon(self, node_id: NodeId | None, error: str = "node is gone") -> Task:
        """Transition RUNNING→DONE when the node disappeared."""
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        new_events = self.events
        if node_id is not None:
            event = TaskAbandoned(
                task_id=self.task_id,
                webhook_url=self.webhook_url,
                webhook_custom_params=self.webhook_custom_params,
                node_id=node_id,
            )
            new_events = (*new_events, event)
        return replace(
            self,
            status=TaskStatus.DONE,
            error=error,
            events=new_events,
        )

    # endregion METHOD_abandon


# endregion CLASS_Task


# region FUNC_materialize_task
# PURPOSE: Attach the TaskCreated event to a freshly-inserted Task so the UoW dispatches it on commit.
# RATIONALE:
# - Q: Why a dedicated function instead of calling TaskCreated inside insert?
#   A: Keeps the domain event construction in the domain layer and the SQL/ORM concern in the repository. The infrastructure layer never imports TaskCreated directly.
def materialize_task(task: Task) -> Task:
    """Return a Task with a TaskCreated event appended to events."""
    event = TaskCreated(
        task_id=task.task_id,
        webhook_url=task.webhook_url,
        webhook_custom_params=task.webhook_custom_params,
        engine_name=task.engine,
    )
    return replace(task, events=(event,))


# endregion FUNC_materialize_task


# region CLASS_NodeId
# PURPOSE: Wrap the database node id in a dedicated value object so transport/serialization boundaries must unwrap it explicitly, preventing accidental mixing with bare ints.
# INVARIANTS: value > 0; frozen and hashable; not equal to a bare int.
# RATIONALE:
# - Q: Why a dedicated type instead of bare int, NewType('NodeId', int), or int subclass?
#   A: A frozen dataclass wrapper enforces explicit .value unwrapping at every external boundary, preventing accidental id/int mixing.
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
            msg = f"NodeId must be > 0, got {self.value}"
            raise ValueError(msg)

    def __str__(self) -> str:
        return str(self.value)


# endregion CLASS_NodeId


# region CLASS_NewNode
# PURPOSE: Carry the fields needed to insert a node before it has a database id, mirroring Node minus identity.
# INVARIANTS: No node_id field (absent by design). hostname="" is the empty-string sentinel for tmp rows. ncpus=None means no operator-set limit (discovered at spawn).
@dataclass(frozen=True)
class NewNode:
    """Pre-persistence node record — no identity yet; mirrors :class:`Node`.

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
    ncpus: int | None = None
    cloud: str | None = None
    external_id: str | None = None


# endregion CLASS_NewNode


# region CLASS_Node
# PURPOSE: Represent a persisted node, carrying its database identity as the first field so a Node instance always proves it was read from (or returned by) the database.
# INVARIANTS: ncpus > 0. external_id is None for static nodes.
# RATIONALE:
# - Q: Why do created_at/updated_at default to datetime.now()?
#   A: Mirrors the DB schema convention; the DB always overrides via RETURNING on insert/read.
@dataclass(frozen=True)
class Node:
    """Post-persistence node record — always carries its identity.

    ``node_id`` is the FIRST field (identity first); a ``Node`` only ever comes from
    the database.
    """

    node_id: NodeId
    hostname: str
    ncpus: int | None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    username: str = "root"
    port: int = 22
    jump_host: str | None = None
    jump_port: int = 22
    jump_username: str = "root"
    enabled: bool = True
    status: NodeStatus = NodeStatus.OTHER
    cloud: str | None = None
    external_id: str | None = None


# endregion CLASS_Node


# region CLASS_ConnectedMachine
# PURPOSE: Track a runtime-connected machine's occupancy state with atomic FREE/BUSY transitions so allocation and release are concurrency-safe.
# INVARIANTS: Frozen; state changes return new instances via replace; free_since is set on every transition to FREE. Platform is runtime-discovered.
# RATIONALE:
# - Q: Why is platform on ConnectedMachine instead of Node?
#   A: It is runtime-discovered at connect time via the platform-package detector, not a persistent attribute of the node record. It feeds the is_compatible(engine.platforms) check and is meaningless outside a live connection.
@dataclass(frozen=True)
class ConnectedMachine:
    """Runtime connected machine.

    ``node_id`` identifies which :class:`Node` this connected machine represents.
    """

    node_id: NodeId
    platform: str
    state: MachineState = MachineState.FREE
    free_since: float | None = None

    # region METHOD_is_compatible
    # PURPOSE: Tell whether this machine can accept a task, i.e. is free and on a supported platform.
    def is_compatible(self, platforms: tuple[str, ...]) -> bool:
        """Check if machine is FREE and platform matches given platforms."""
        return self.state == MachineState.FREE and self.platform in platforms

    # endregion METHOD_is_compatible

    # region METHOD_occupy
    # PURPOSE: Claim the machine for a task, refusing double-assignment.
    # REQUIRES: state is FREE.
    def occupy(self) -> ConnectedMachine:
        """Transition machine state to BUSY if currently FREE."""
        if self.state == MachineState.BUSY:
            raise MachineBusyError(self.node_id)
        return replace(self, state=MachineState.BUSY)

    # endregion METHOD_occupy

    # region METHOD_release
    # PURPOSE: Return the machine to the free pool and stamp when it became available.
    def release(self) -> ConnectedMachine:
        """Transition machine state to FREE and record release timestamp."""
        return replace(self, state=MachineState.FREE, free_since=time.monotonic())

    # endregion METHOD_release


# endregion CLASS_ConnectedMachine

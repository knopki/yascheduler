# FILE: yascheduler/domain/model.py
# VERSION: 1.17.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain entities.
#   SCOPE: TaskStatus, MachineState enums; ProcessResult, TaskContext value objects; TaskId, NewTask, Task, NewNode, Node, NodeId, ConnectedMachine entities; re-export Engine, EngineRepository, Deploy* from .engine for backward compatibility.
#   DEPENDS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE
#   LINKS: M-DOMAIN-EXCEPTIONS, M-DOMAIN-EVENTS, M-DOMAIN-ENGINE
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskStatus - IntEnum: TO_DO=0, RUNNING=1, DONE=2
#   MachineState - Enum: FREE, BUSY
#   ProcessResult - Exit code and captured output from remote execution
#   TaskContext - Typed task metadata with arbitrary extras; .replace() typed copy-with
#   TaskContextOverrides - TypedDict (total=False) of overridable TaskContext fields: remote_folder, local_folder, error, extra
#   TaskId - Task primary-key value object (frozen dataclass wrapping int; validates >0; __str__ renders bare int)
#   NewTask - Pre-persistence task record (no task_id)
#   Task - Post-persistence task entity; always carries task_id: TaskId (first field, identity-first); allocate_to, mark_running, complete, fail, reject lifecycle, record_event, with_event, with_context, pull_events
#   NodeId - Node primary-key value object (frozen dataclass wrapping int; validates >0; __str__ renders bare int)
#   NewNode - Pre-persistence node record (no node_id)
#   Node - Post-persistence node record; always carries node_id: NodeId (first field, identity-first)
#   ConnectedMachine - Runtime connected machine with state transitions
#   Engine - Calculation engine value object (re-exported from M-DOMAIN-ENGINE; see domain/engine.py)
#   EngineRepository - Frozen collection of engines (re-exported from M-DOMAIN-ENGINE)
#   LocalFilesDeploy / LocalArchiveDeploy / RemoteArchiveDeploy / Deploy - Deploy strategies (re-exported from M-DOMAIN-ENGINE)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.17.0 - Add TaskId value object (frozen dataclass wrapping int, validates >0, __str__ renders bare int) and NewTask pre-persistence record; Task gains task_id: TaskId as first field (post-persistence shape). Conversion NewTask→Task happens only in TaskRepository.insert (add-task-id-identity).
#   PREVIOUS_CHANGE: v1.16.0 - Add NodeId value object (frozen dataclass wrapping int, validates >0, __str__ renders bare int) and NewNode pre-persistence record; Node gains node_id: NodeId as first field (post-persistence shape). Conversion NewNode→Node happens only in NodeRepository.insert (add-node-id-identity).
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, fields, replace
from enum import Enum, IntEnum, unique
from typing import TYPE_CHECKING, TypedDict, TypeVar, overload

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

if TYPE_CHECKING:
    from collections.abc import Mapping

    from yascheduler.shared import Self, Unpack

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


class TaskContextOverrides(TypedDict, total=False):
    """Overridable TaskContext fields.

    Only fields actually replaced somewhere in the codebase are listed.
    """

    remote_folder: str | None
    local_folder: str | None
    error: str | None
    extra: dict[str, object]


# START_CONTRACT: _get_opt_str
#   PURPOSE: Narrow a JSONB metadata value to str | None at the deserialization boundary; raise TypeError on any other type.
#   INPUTS: { metadata: Mapping[str, object] - JSONB flat dict, key: str - the str|None field name }
#   OUTPUTS: { str | None - the str value, or None if the key is missing/None }
#   SIDE_EFFECTS: None
#   RAISES: TypeError - if the value is neither str nor None (upstream JSONB corruption)
#   LINKS: M-DOMAIN-MODEL
# END_CONTRACT: _get_opt_str
def _get_opt_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None or isinstance(value, str):
        return value
    raise TypeError(
        f"TaskContext JSONB field {key!r} expected str or None, "
        f"got {type(value).__name__}"
    )


@dataclass(frozen=True)
class TaskContext:
    """Typed task metadata with engine name, paths, webhook, and arbitrary extras."""

    engine: str
    remote_folder: str | None = None
    local_folder: str | None = None
    webhook_url: str | None = None
    webhook_custom_params: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def to_metadata(self) -> dict[str, object]:
        """Serialize to flat dict for JSONB storage."""

        def factory(items: list[tuple[str, object]]) -> dict[str, object]:
            return {k: v for k, v in items if v is not None and k != "extra"}

        result = asdict(self, dict_factory=factory)
        # Domain fields take precedence — merge extra only for non-colliding keys
        for k, v in self.extra.items():
            if k not in result:
                result[k] = v
        return result

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> TaskContext:
        """Deserialize from a flat dict produced by to_metadata()."""
        extra: dict[str, object] = {}
        keys = [field.name for field in fields(cls) if field.name != "extra"]
        for key, value in metadata.items():
            if key not in keys:
                extra[key] = value

        wcp = metadata.get("webhook_custom_params")
        webhook_custom_params = wcp if isinstance(wcp, dict) else {}
        return cls(
            engine=str(metadata.get("engine", "")),
            remote_folder=_get_opt_str(metadata, "remote_folder"),
            local_folder=_get_opt_str(metadata, "local_folder"),
            webhook_url=_get_opt_str(metadata, "webhook_url"),
            webhook_custom_params=webhook_custom_params,
            error=_get_opt_str(metadata, "error"),
            extra=extra,
        )

    # START_CONTRACT: TaskContext.replace
    #   PURPOSE: Typed copy-with returning a new TaskContext
    #   INPUTS: { **overrides: Unpack[TaskContextOverrides] - subset of fields to override }
    #   OUTPUTS: { Self - new TaskContext instance with overrides applied }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-MODEL
    # END_CONTRACT: TaskContext.replace
    def replace(self, **overrides: Unpack[TaskContextOverrides]) -> Self:
        """Return a new TaskContext with the given overrides applied."""
        return replace(self, **overrides)


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
#   INPUTS: { label: str, context: TaskContext, status: TaskStatus, allocated_ip: str | None }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: TaskRepository.insert
# END_CONTRACT: NewTask
@dataclass(frozen=True)
class NewTask:
    """Pre-persistence task record — no identity yet.

    Mirrors the non-``task_id``/non-``_events`` fields of :class:`Task` with identical
    defaults. A caller builds a ``NewTask`` to prepare a task for insertion; the
    conversion to :class:`Task` happens in exactly one place: ``TaskRepository.insert``.
    It is a pure data carrier with no lifecycle methods (those are nonsensical on an
    unpersisted task and stay on ``Task``).
    """

    label: str
    context: TaskContext
    status: TaskStatus = TaskStatus.TO_DO
    allocated_ip: str | None = None


# START_CONTRACT: Task
#   PURPOSE: Post-persistence task entity — always carries its database-generated task_id (identity-first) and a status lifecycle.
#   INPUTS: { task_id: TaskId, label: str, context: TaskContext, status: TaskStatus, allocated_ip: str | None }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: TaskRepository.insert (the only NewTask→Task conversion site)
# END_CONTRACT: Task
@dataclass(frozen=True)
class Task:
    """Post-persistence task entity with lifecycle methods and allocation state.

    ``task_id`` is the FIRST field (identity first); a ``Task`` only ever comes from
    the database (via ``_row_to_task``) or from ``TaskRepository.insert``'s return.
    The ``task_id=0`` sentinel is unrepresentable: ``Task``'s ``task_id: TaskId`` field
    is required, and ``TaskId(0)`` raises ``ValueError``.
    """

    task_id: TaskId
    label: str
    context: TaskContext
    status: TaskStatus = TaskStatus.TO_DO
    allocated_ip: str | None = None
    _events: tuple[DomainEvent, ...] = field(default=(), repr=False)

    # START_CONTRACT: Task.allocate_to
    #   PURPOSE: Bind task to a node IP if not already allocated.
    #   INPUTS: { ip: str - Node IP address }
    #   OUTPUTS: { Task - New Task instance with allocated_ip set }
    #   SIDE_EFFECTS: None
    #   RAISES: TaskAlreadyAllocatedError - if already allocated
    #   LINKS: M-DOMAIN-EXCEPTIONS: TaskAlreadyAllocatedError
    # END_CONTRACT: Task.allocate_to
    def allocate_to(self, ip: str) -> Task:
        """Bind task to a node IP, raising TaskAlreadyAllocatedError if already allocated."""
        # START_BLOCK_VALIDATE_NOT_ALLOCATED
        if self.allocated_ip is not None:
            raise TaskAlreadyAllocatedError(self.task_id)
        # END_BLOCK_VALIDATE_NOT_ALLOCATED
        # START_BLOCK_APPLY_ALLOCATION
        return replace(self, allocated_ip=ip)
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
        if self.allocated_ip is None:
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
    #   OUTPUTS: { Task - New Task instance with status=DONE and context.error set }
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
        return replace(
            self,
            status=TaskStatus.DONE,
            context=self.context.replace(error=reason),
        )
        # END_BLOCK_MARK_FAILED

    # START_CONTRACT: Task.reject
    #   PURPOSE: Mark a TO_DO task as DONE with error reason (e.g. unsupported engine).
    #   INPUTS: { reason: str - Rejection description }
    #   OUTPUTS: { Task - New Task instance with status=DONE and context.error set }
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
        return replace(
            self,
            status=TaskStatus.DONE,
            context=self.context.replace(error=reason),
        )
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

    # START_CONTRACT: Task.with_context
    #   PURPOSE: Wholesale-replace the task's context, returning a new Task.
    #   INPUTS: { context: TaskContext - new context to wholesale-replace }
    #   OUTPUTS: { Task - new instance with context replaced, all other fields preserved }
    #   SIDE_EFFECTS: None
    #   LINKS: M-DOMAIN-MODEL
    # END_CONTRACT: Task.with_context
    def with_context(self, context: TaskContext) -> Task:
        return replace(self, context=context)

    # START_CONTRACT: Task.with_event
    #   PURPOSE: Construct an event of the given type with base fields (task_id, webhook_url, webhook_custom_params) populated from self.context and subclass-specific fields from the caller, then append via record_event.
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
        self, event_type: type[TaskAllocated], *, node_ip: str, engine_name: str
    ) -> Task: ...
    @overload
    def with_event(
        self, event_type: type[TaskCompleted], *, local_folder: str, has_errors: bool
    ) -> Task: ...
    @overload
    def with_event(self, event_type: type[TaskFailed], *, reason: str) -> Task: ...
    @overload
    def with_event(self, event_type: type[TaskAbandoned], *, node_ip: str) -> Task: ...
    def with_event(self, event_type: type[_E], **fields: object) -> Task:
        # START_BLOCK_DROP_BASE_FIELDS
        fields.pop("task_id", None)
        fields.pop("webhook_url", None)
        fields.pop("webhook_custom_params", None)
        # END_BLOCK_DROP_BASE_FIELDS
        # START_BLOCK_CONSTRUCT_AND_RECORD
        event = event_type(
            task_id=self.task_id,
            webhook_url=self.context.webhook_url,
            webhook_custom_params=self.context.webhook_custom_params,
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
#   INPUTS: { ip: str, ncpus: int, enabled: bool, cloud: str | None, username: str, port: int }
#   OUTPUTS: { None - dataclass }
#   SIDE_EFFECTS: None
#   LINKS: M-DOMAIN-MODEL, M-DOMAIN-PORTS: NodeRepository.insert
# END_CONTRACT: NewNode
@dataclass(frozen=True)
class NewNode:
    """Pre-persistence node record — no identity yet.

    Mirrors the non-``node_id`` fields of :class:`Node` with identical defaults. A
    caller builds a ``NewNode`` to prepare a node for insertion; the conversion to
    :class:`Node` happens in exactly one place: ``NodeRepository.insert``.
    ``CloudProvisioner.allocate`` returns a ``NewNode`` (a freshly-built VM that has
    not been persisted).
    """

    ip: str
    ncpus: int
    enabled: bool = True
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
    the database (via ``_row_to_node``) or from ``NodeRepository.insert``'s return.
    The ``ip``-based identity legacy is deliberately not removed in this change:
    ``ip`` remains ``UNIQUE`` and remains the key for ip-keyed ``NodeRepository``
    mutators; ``node_id`` is carried alongside ``ip``, not swapped for it.
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
    """Runtime connected machine with state and platform info."""

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

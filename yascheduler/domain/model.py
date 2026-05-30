# FILE: yascheduler/domain/model.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain entities.
#   SCOPE: TaskStatus, MachineState enums; ProcessResult, TaskContext, Engine value objects; Task, Node, ConnectedMachine entities.
#   DEPENDS: M-DOMAIN-EXCEPTIONS
#   LINKS: M-DOMAIN-EXCEPTIONS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   TaskStatus - IntEnum: TO_DO=0, RUNNING=1, DONE=2
#   MachineState - Enum: FREE, BUSY
#   ProcessResult - Exit code and captured output from remote execution
#   TaskContext - Typed task metadata with arbitrary extras
#   Engine - Calculation engine specification with platform support
#   Task - Task entity with allocate_to, mark_running, complete, fail lifecycle
#   Node - Persistent compute node record
#   ConnectedMachine - Runtime connected machine with state transitions
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.7.0 - TaskContext.to_metadata/from_metadata for JSONB serialization
#   PREVIOUS_CHANGE: v1.6.0 - Create domain entities for Hexagonal + DDD migration.
# END_CHANGE_SUMMARY

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from enum import Enum, IntEnum, unique

from .exceptions import (
    MachineBusyError,
    MissingInputFileError,
    TaskAlreadyAllocatedError,
    TaskNotAllocatedError,
    TaskNotRunningError,
    TaskNotTodoError,
)


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

        def factory(items):
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
            remote_folder=metadata.get("remote_folder"),  # type: ignore[arg-type]
            local_folder=metadata.get("local_folder"),  # type: ignore[arg-type]
            webhook_url=metadata.get("webhook_url"),  # type: ignore[arg-type]
            webhook_custom_params=webhook_custom_params,  # type: ignore[arg-type]
            error=metadata.get("error"),  # type: ignore[arg-type]
            extra=extra,
        )


@dataclass(frozen=True)
class Engine:
    """Calculation engine specification with spawn command and platform support."""

    name: str
    spawn: str
    input_files: tuple[str, ...] = ()
    output_files: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()
    check_cmd: str | None = None
    check_pname: str | None = None

    # START_CONTRACT: Engine.validate_inputs
    #   PURPOSE: Validate that all required input files exist in the task context.
    #   INPUTS: { ctx: TaskContext - Task metadata containing input file data in ctx.extra }
    #   OUTPUTS: { None }
    #   SIDE_EFFECTS: None
    #   RAISES: MissingInputFileError - if any input_file is missing from ctx.extra
    #   LINKS: M-DOMAIN-EXCEPTIONS: MissingInputFileError
    # END_CONTRACT: Engine.validate_inputs
    def validate_inputs(self, ctx: TaskContext) -> None:
        """Verify all required engine input files exist in the task context."""
        for filename in self.input_files:
            if filename not in ctx.extra:
                raise MissingInputFileError(self.name, filename)


@dataclass(frozen=True)
class Task:
    """Schedulable task entity with lifecycle methods and allocation state."""

    task_id: int
    label: str
    context: TaskContext
    status: TaskStatus = TaskStatus.TO_DO
    allocated_ip: str | None = None

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
    #   RAISES: TaskNotAllocatedError - if not RUNNING
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
        # START_BLOCK_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_VALIDATE_RUNNING
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
        # START_BLOCK_VALIDATE_RUNNING
        if self.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(self.task_id)
        # END_BLOCK_VALIDATE_RUNNING
        # START_BLOCK_MARK_FAILED
        return replace(
            self,
            status=TaskStatus.DONE,
            context=replace(self.context, error=reason),
        )
        # END_BLOCK_MARK_FAILED


@dataclass(frozen=True)
class Node:
    """Persistent compute node record with connection details."""

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

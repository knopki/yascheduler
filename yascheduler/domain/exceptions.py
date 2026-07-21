"""Domain exception hierarchy for business-level error handling."""
# region MODULE_CONTRACT
# PURPOSE: Give the scheduler one typed error vocabulary so callers catch specific business failures instead of parsing messages.
# SCOPE:
# - DomainError root plus validation, task-lifecycle, machine-state, scheduling, and cloud sub-hierarchies.
# - NOT: error rendering, exit codes, or retry policy.
# INVARIANTS: Every domain error subclasses DomainError; messages are stable and human-readable.
# RATIONALE:
# - Q: Why is CloudCapacityExhaustedError under SchedulingError, not CloudError?
#   A: Capacity planning is a domain scheduling rule (no provider can serve the request), whereas CloudError covers operational provider failures (VM creation, SSH, setup). Keeping them apart lets the allocator retry/throttle differently from handling provider outages.
# KEYWORDS: domain error, exception, validation, task lifecycle, machine busy, scheduling, cloud error
# endregion MODULE_CONTRACT

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import NodeId, TaskId

__all__ = [
    "CloudAllocateError",
    "CloudCapacityExhaustedError",
    "CloudError",
    "CloudSetupError",
    "DomainError",
    "MachineBusyError",
    "MachineConnectionError",
    "MissingInputFileError",
    "NoCompatibleNodeError",
    "SchedulingError",
    "TaskError",
    "TaskNotRunningError",
    "TaskNotTodoError",
    "UnsupportedEngineError",
    "ValidationError",
]


class DomainError(Exception):
    """Base class for all domain exceptions."""


class ValidationError(DomainError):
    """Input validation errors."""


class UnsupportedEngineError(ValidationError):
    """Unknown calculation engine requested."""

    def __init__(self, engine_name: str) -> None:
        self.engine_name = engine_name
        super().__init__(f"unsupported engine: {engine_name}")


class MissingInputFileError(ValidationError):
    """Required engine input file not provided."""

    def __init__(self, engine_name: str, filename: str) -> None:
        self.engine_name = engine_name
        self.filename = filename
        super().__init__(f"missing input file '{filename}' for engine: {engine_name}")


class TaskError(DomainError):
    """Task lifecycle errors."""


class TaskNotTodoError(TaskError):
    """Task not in TODO status."""

    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is not in TODO status")


class TaskNotRunningError(TaskError):
    """Task not running."""

    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is not in running status")


class MachineBusyError(DomainError):
    """Operation attempted on a busy machine."""

    def __init__(self, node_id: NodeId) -> None:
        self.node_id = node_id
        super().__init__(f"machine ({node_id}) is busy")


class MachineConnectionError(DomainError):
    """SSH connection failure when establishing a connection to a remote machine."""

    def __init__(self, node_id: NodeId, hostname: str, reason: str) -> None:
        self.node_id = node_id
        self.hostname = hostname
        self.reason = reason
        super().__init__(
            f"cannot connect to machine ({node_id}) at {hostname}: {reason}",
        )


class SchedulingError(DomainError):
    """Scheduling/allocation errors."""


class NoCompatibleNodeError(SchedulingError):
    """No matching node found for task."""

    def __init__(self, task_id: TaskId, platforms: list[str]) -> None:
        self.task_id = task_id
        self.platforms = platforms
        super().__init__(
            f"no compatible node found for task {task_id} on platforms: {platforms}",
        )


class CloudCapacityExhaustedError(SchedulingError):
    """Cloud provider at capacity."""

    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"cloud capacity exhausted for task {task_id}")


class CloudError(DomainError):
    """Operational cloud-provider failures."""


class CloudAllocateError(CloudError):
    """Cloud node allocation error — provider selection or VM creation failed."""


class CloudSetupError(CloudError):
    """Cloud node setup error — SSH / cloud-init / engine installation failed."""

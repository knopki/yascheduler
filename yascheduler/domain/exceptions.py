# FILE: yascheduler/domain/exceptions.py
# VERSION: 1.10.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain exception hierarchy for business-level error handling.
#   SCOPE: Domain error hierarchy: DomainError base class and sub-hierarchies for validation, task lifecycle, machine state, scheduling, and cloud provider errors.
#   DEPENDS: none
#   LINKS: M-DOMAIN-MODEL
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DomainError - Base class for all domain exceptions
#   ValidationError - Input validation errors
#   UnsupportedEngineError - Unknown calculation engine requested
#   MissingInputFileError - Required engine input file not provided
#   TaskError - Task lifecycle errors
#   TaskAlreadyAllocatedError - Task already bound to a node
#   TaskNotAllocatedError - Task not yet allocated to a node
#   TaskNotTodoError - Task not in TODO status
#   TaskNotRunningError - Task not in RUNNING status
#   MachineBusyError - Operation attempted on a busy machine
#   MachineConnectionError - SSH connection failure carrying ip and reason
#   SchedulingError - Scheduling/allocation errors
#   NoCompatibleNodeError - No matching node found for task
#   CloudCapacityExhaustedError - Cloud provider at capacity
#   CloudError - Cloud provider operational errors
#   CloudAllocateError - Cloud node allocation error
#   CloudSetupError - Cloud node setup error
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.10.0 - The 6 task-keyed exceptions take task_id: TaskId; f-string messages render the bare integer via TaskId.__str__. Added `from __future__ import annotations` and import TaskId under TYPE_CHECKING to break the model↔exceptions runtime import cycle.
#   PREVIOUS_CHANGE: v1.9.0 - Add CloudError(DomainError) intermediate root; reparent CloudAllocateError/CloudSetupError under it.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import TaskId


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


class TaskAlreadyAllocatedError(TaskError):
    """Task already bound to a node."""

    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is already allocated to a node")


class TaskNotAllocatedError(TaskError):
    """Task not yet allocated to a node."""

    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is not allocated to any node")


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

    def __init__(self, ip: str) -> None:
        self.ip = ip
        super().__init__(f"machine at {ip} is busy")


class MachineConnectionError(DomainError):
    """SSH connection failure when establishing a connection to a remote machine."""

    def __init__(self, ip: str, reason: str) -> None:
        self.ip = ip
        self.reason = reason
        super().__init__(f"cannot connect to {ip}: {reason}")


class SchedulingError(DomainError):
    """Scheduling/allocation errors."""


class NoCompatibleNodeError(SchedulingError):
    """No matching node found for task."""

    def __init__(self, task_id: TaskId, platforms: list[str]) -> None:
        self.task_id = task_id
        self.platforms = platforms
        super().__init__(
            f"no compatible node found for task {task_id} on platforms: {platforms}"
        )


class CloudCapacityExhaustedError(SchedulingError):
    """Cloud provider at capacity."""

    def __init__(self, task_id: TaskId) -> None:
        self.task_id = task_id
        super().__init__(f"cloud capacity exhausted for task {task_id}")


class CloudError(DomainError):
    """Operational cloud-provider failures: provider selection, VM creation, SSH/cloud-init/engine setup.

    Cloud capacity planning is a distinct concern and lives under
    `SchedulingError` as `CloudCapacityExhaustedError` — it is a domain
    scheduling rule, not an operational provider failure.
    """


class CloudAllocateError(CloudError):
    """Cloud node allocation error — provider selection or VM creation failed."""


class CloudSetupError(CloudError):
    """Cloud node setup error — SSH / cloud-init / engine installation failed."""

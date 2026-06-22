# FILE: yascheduler/domain/exceptions.py
# VERSION: 1.8.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain exception hierarchy for business-level error handling.
#   SCOPE: DomainError base class and sub-hierarchies: validation, task lifecycle, machine state, scheduling, connection.
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
#   CloudAllocateError - Cloud node allocation error
#   CloudSetupError - Cloud node setup error
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.8.0 - Add CloudAllocateError, CloudSetupError relocated from adapters/cloud/manager.py (cloud-provisioner-pure).
#   PREVIOUS_CHANGE: v1.7.0 - Add MachineConnectionError for SSH connection failures (gateway-port-cleanup).
# END_CHANGE_SUMMARY


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

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is already allocated to a node")


class TaskNotAllocatedError(TaskError):
    """Task not yet allocated to a node."""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is not allocated to any node")


class TaskNotTodoError(TaskError):
    """Task not in TODO status."""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"task {task_id} is not in TODO status")


class TaskNotRunningError(TaskError):
    """Task not running."""

    def __init__(self, task_id: int) -> None:
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

    def __init__(self, task_id: int, platforms: list[str]) -> None:
        self.task_id = task_id
        self.platforms = platforms
        super().__init__(
            f"no compatible node found for task {task_id} on platforms: {platforms}"
        )


class CloudCapacityExhaustedError(SchedulingError):
    """Cloud provider at capacity."""

    def __init__(self, task_id: int) -> None:
        self.task_id = task_id
        super().__init__(f"cloud capacity exhausted for task {task_id}")


class CloudAllocateError(Exception):
    """Cloud node allocation error — provider selection or VM creation failed."""


class CloudSetupError(Exception):
    """Cloud node setup error — SSH / cloud-init / engine installation failed."""

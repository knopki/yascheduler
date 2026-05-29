# FILE: yascheduler/domain/exceptions.py
# VERSION: 1.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain exception hierarchy for business-level error handling.
#   SCOPE: DomainError base class and sub-hierarchies: validation, task lifecycle, machine state, scheduling.
#   DEPENDS: none
#   LINKS:
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
#   MachineBusyError - Operation attempted on a busy machine
#   SchedulingError - Scheduling/allocation errors
#   NoCompatibleNodeError - No matching node found for task
#   CloudCapacityExhaustedError - Cloud provider at capacity
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.6.0 - Create domain exception hierarchy for Hexagonal + DDD migration.
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


class MachineBusyError(DomainError):
    """Operation attempted on a busy machine."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        super().__init__(f"machine at {ip} is busy")


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

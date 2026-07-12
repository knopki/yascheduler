# FILE: yascheduler/domain/exceptions.py
# VERSION: 1.12.0
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
#   TaskNotTodoError - Task not in TODO status
#   TaskNotRunningError - Task not in RUNNING status
#   MachineBusyError - Operation attempted on a busy machine
#   MachineConnectionError - SSH connection failure carrying node_id, hostname, and reason
#   SchedulingError - Scheduling/allocation errors
#   NoCompatibleNodeError - No matching node found for task
#   CloudCapacityExhaustedError - Cloud provider at capacity
#   CloudError - Cloud provider operational errors
#   CloudAllocateError - Cloud node allocation error
#   CloudSetupError - Cloud node setup error
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v1.13.0 - ConnectedMachine-runtime-only: MachineBusyError(node_id) — drop hostname param. MachineConnectionError UNCHANGED.
#   PREVIOUS_CHANGE: v1.12.0 - MachineBusyError/MachineConnectionError gain node_id first arg, hostname replaces ip. MachineBusyError(node_id, hostname), MachineConnectionError(node_id, hostname, reason). Node-rename-and-fields change.
# END_CHANGE_SUMMARY

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yascheduler.domain.model import NodeId, TaskId


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
            f"cannot connect to machine ({node_id}) at {hostname}: {reason}"
        )


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

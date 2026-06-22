# FILE: yascheduler/domain/__init__.py
# VERSION: 2.1.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain layer entry point — re-exports events, model entities, exception hierarchy, and port interfaces.
#   SCOPE: Re-exports domain events from .events, domain entities from .model, exception tree from .exceptions, and port Protocols from .ports.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS
# END_MODULE_CONTRACT
#
# START_MODULE_MAP
#   DomainEvent - Base frozen dataclass for all task lifecycle events
#   TaskCreated - Task submitted event
#   TaskAllocated - Task assigned to node event
#   TaskCompleted - Task finished event
#   TaskFailed - Task failed event
#   TaskAbandoned - Task abandoned on lost node event
#   Event - Union type alias of all event types
#   TaskStatus - IntEnum: TO_DO=0, RUNNING=1, DONE=2
#   MachineState - Enum: FREE, BUSY
#   ProcessResult - Exit code and captured output from remote execution
#   TaskContext - Typed task metadata with arbitrary extras
#   Engine - Calculation engine specification with platform support
#   Task - Task entity with lifecycle methods
#   Node - Persistent compute node record
#   ConnectedMachine - Runtime connected machine with state transitions
#   ProviderSelection - Selected cloud provider value object (name, username)
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
#   TaskRepository - Async port for task persistence
#   NodeRepository - Async port for node persistence
#   MachineGateway - Async port for remote machine operations
#   OccupancyConfig - Minimal structural contract for occupancy check configuration
#   TaskExecutionEngine - Engine contract for task deployment (superset of OccupancyConfig)
#   CloudProvisioner - Async port for cloud node provisioning
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.1.0 - Add CloudError re-export (cloud-error-hierarchy).
#   PREVIOUS_CHANGE: v2.0.0 - Add ProviderSelection, CloudAllocateError, CloudSetupError re-exports (cloud-provisioner-pure).
# END_CHANGE_SUMMARY

__all__ = [
    # Events
    "DomainEvent",
    "Event",
    "TaskAbandoned",
    "TaskAllocated",
    "TaskCompleted",
    "TaskCreated",
    "TaskFailed",
    # Model
    "TaskStatus",
    "MachineState",
    "ProcessResult",
    "TaskContext",
    "Engine",
    "Task",
    "Node",
    "ConnectedMachine",
    "ProviderSelection",
    # Exceptions
    "DomainError",
    "ValidationError",
    "UnsupportedEngineError",
    "MissingInputFileError",
    "TaskError",
    "TaskAlreadyAllocatedError",
    "TaskNotAllocatedError",
    "TaskNotTodoError",
    "TaskNotRunningError",
    "MachineBusyError",
    "MachineConnectionError",
    "SchedulingError",
    "NoCompatibleNodeError",
    "CloudCapacityExhaustedError",
    "CloudError",
    "CloudAllocateError",
    "CloudSetupError",
    # Ports
    "TaskRepository",
    "NodeRepository",
    "MachineGateway",
    "OccupancyConfig",
    "TaskExecutionEngine",
    "CloudProvisioner",
]

from .events import (
    DomainEvent,
    Event,
    TaskAbandoned,
    TaskAllocated,
    TaskCompleted,
    TaskCreated,
    TaskFailed,
)
from .exceptions import (
    CloudAllocateError,
    CloudCapacityExhaustedError,
    CloudError,
    CloudSetupError,
    DomainError,
    MachineBusyError,
    MachineConnectionError,
    MissingInputFileError,
    NoCompatibleNodeError,
    SchedulingError,
    TaskAlreadyAllocatedError,
    TaskError,
    TaskNotAllocatedError,
    TaskNotRunningError,
    TaskNotTodoError,
    UnsupportedEngineError,
    ValidationError,
)
from .model import (
    ConnectedMachine,
    Engine,
    MachineState,
    Node,
    ProcessResult,
    ProviderSelection,
    Task,
    TaskContext,
    TaskStatus,
)
from .ports import (
    CloudProvisioner,
    MachineGateway,
    NodeRepository,
    OccupancyConfig,
    TaskExecutionEngine,
    TaskRepository,
)

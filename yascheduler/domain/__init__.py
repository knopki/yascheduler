# FILE: yascheduler/domain/__init__.py
# VERSION: 2.6.0
# START_MODULE_CONTRACT
#   PURPOSE: Domain layer entry point — re-exports events, model entities, engine types, exception hierarchy, port interfaces, and cross-layer settings.
#   SCOPE: Re-exports domain events from .events, domain entities from .model, engine types from .engine (via .model), exception tree from .exceptions, port Protocols from .ports (including CloudConfig), and LocalSettings/RemoteDefaults from .settings.
#   DEPENDS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-ENGINE, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS, M-DOMAIN-SETTINGS
#   LINKS: M-DOMAIN-EVENTS, M-DOMAIN-MODEL, M-DOMAIN-ENGINE, M-DOMAIN-EXCEPTIONS, M-DOMAIN-PORTS, M-DOMAIN-SETTINGS
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
#   Engine - Calculation engine value object (from M-DOMAIN-ENGINE)
#   EngineRepository - Frozen collection of engines (from M-DOMAIN-ENGINE)
#   LocalFilesDeploy / LocalArchiveDeploy / RemoteArchiveDeploy / Deploy - Deploy strategies (from M-DOMAIN-ENGINE)
#   Task - Task entity with lifecycle methods
#   Node - Persistent compute node record
#   ConnectedMachine - Runtime connected machine with state transitions
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
#   CloudConfig - Structural contract for cloud provider config (6-field surface application consumers read)
#   CloudProvisioner - Async port for cloud node provisioning
#   LocalSettings - Frozen dataclass: local daemon settings (paths, webhook, concurrency limits)
#   RemoteDefaults - Frozen dataclass: remote SSH defaults (paths, username, jump host)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.6.0 - Drop OccupancyConfig and TaskExecutionEngine from __all__, .ports re-export, and MODULE_MAP (resolve-engine-protocol-debt); the Protocols were deleted from ports.py and the MachineGateway methods now type against the concrete Engine.
#   PREVIOUS_CHANGE: v2.5.0 - Re-export LocalSettings, RemoteDefaults from .settings (config-aggregate-to-entrypoints / P4); cross-layer application settings relocated from yascheduler.config to yascheduler.domain.
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
    "EngineRepository",
    "LocalFilesDeploy",
    "LocalArchiveDeploy",
    "RemoteArchiveDeploy",
    "Deploy",
    "Task",
    "Node",
    "ConnectedMachine",
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
    "CloudConfig",
    "CloudProvisioner",
    # Settings
    "LocalSettings",
    "RemoteDefaults",
]

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
    MachineState,
    Node,
    ProcessResult,
    Task,
    TaskContext,
    TaskStatus,
)
from .ports import (
    CloudConfig,
    CloudProvisioner,
    MachineGateway,
    NodeRepository,
    TaskRepository,
)
from .settings import LocalSettings, RemoteDefaults

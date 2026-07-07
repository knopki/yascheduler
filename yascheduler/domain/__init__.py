# FILE: yascheduler/domain/__init__.py
# VERSION: 2.11.0
# START_MODULE_CONTRACT
#   PURPOSE: Re-export domain symbols for cross-layer consumption.
#   SCOPE: Public domain surface: entities, value objects, ports, events, exceptions, and cross-layer settings — re-exported for application/infra consumers.
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
#   Engine - Calculation engine value object (from M-DOMAIN-ENGINE)
#   EngineRepository - Frozen collection of engines (from M-DOMAIN-ENGINE)
#   LocalFilesDeploy / LocalArchiveDeploy / RemoteArchiveDeploy / Deploy - Deploy strategies (from M-DOMAIN-ENGINE)
#   Task - Task entity with typed fields (engine, remote_folder, local_folder, webhook_url, webhook_custom_params, error, extra) and lifecycle methods
#   TaskId - Task primary-key value object (frozen dataclass wrapping int)
#   NewTask - Pre-persistence task record (no task_id, no remote_folder, no error)
#   NodeId - Node primary-key value object (frozen dataclass wrapping int)
#   NewNode - Pre-persistence node record (no node_id)
#   Node - Post-persistence node record; carries node_id: NodeId
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
#   MachineRepository - Async port for the connected-machine collection (lifecycle, queries)
#   MachineSession - Connected-machine entity handle (identity, state transitions, connect-time config, adapter-derived accessors, base primitives, monitor mechanism)
#   MachineOperations - Async port for operations on a single machine (deploy, download, occupancy, facade pass-throughs)
#   CloudConfig - Structural contract for cloud provider config (7-field surface application consumers read)
#   CloudProvisioner - Async port for cloud node provisioning
#   LocalSettings - Frozen dataclass: local daemon settings (paths, webhook, concurrency limits)
#   RemoteDefaults - Frozen dataclass: remote SSH defaults (paths, username, jump host)
# END_MODULE_MAP
#
# START_CHANGE_SUMMARY
#   LAST_CHANGE: v2.11.0 - Remove TaskContext / TaskContextOverrides re-exports (folded into Task / NewTask typed fields).
#   PREVIOUS_CHANGE: v2.10.0 - Re-export NewTask and TaskId from .model; DomainEvent.task_id and task-keyed exceptions now carry TaskId.
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
    "Engine",
    "EngineRepository",
    "LocalFilesDeploy",
    "LocalArchiveDeploy",
    "RemoteArchiveDeploy",
    "Deploy",
    "TaskId",
    "NewTask",
    "Task",
    "NodeId",
    "NewNode",
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
    "MachineRepository",
    "MachineSession",
    "MachineOperations",
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
    NewNode,
    NewTask,
    Node,
    NodeId,
    ProcessResult,
    Task,
    TaskId,
    TaskStatus,
)
from .ports import (
    CloudConfig,
    CloudProvisioner,
    MachineOperations,
    MachineRepository,
    MachineSession,
    NodeRepository,
    TaskRepository,
)
from .settings import LocalSettings, RemoteDefaults

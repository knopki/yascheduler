"""Re-export domain symbols for cross-layer consumption."""
# region MODULE_CONTRACT
# PURPOSE: Expose the domain layer's public surface from one import path so upper layers depend on yascheduler.domain, not internal modules.
# SCOPE:
# - Re-export entities, value objects, ports, events, exceptions, engine types, and settings.
# - NOT: new definitions (this module adds nothing to the domain).
# INVARIANTS: __all__ lists every re-exported symbol.
# KEYWORDS: domain facade, public api, re-export, entities, ports, events, exceptions, settings
# endregion MODULE_CONTRACT

__all__ = [
    "CloudAllocateError",
    "CloudCapacityExhaustedError",
    "CloudConfig",
    "CloudError",
    "CloudProvisioner",
    "CloudSetupError",
    "ConnectedMachine",
    "Deploy",
    # Exceptions
    "DomainError",
    # Events
    "DomainEvent",
    "Engine",
    "EngineRepository",
    "Event",
    "LocalArchiveDeploy",
    "LocalFilesDeploy",
    # Settings
    "LocalSettings",
    "MachineBusyError",
    "MachineConnectionError",
    "MachineRepository",
    "MachineSession",
    "MachineState",
    "MissingInputFileError",
    "NewNode",
    "NewTask",
    "NoCompatibleNodeError",
    "Node",
    "NodeId",
    "NodeRepository",
    "NodeRowNotFoundError",
    "NodeStatus",
    "ProcessResult",
    "RemoteArchiveDeploy",
    "RemoteDefaults",
    "SchedulingError",
    "Task",
    "TaskAbandoned",
    "TaskAllocated",
    "TaskCompleted",
    "TaskCreated",
    "TaskError",
    "TaskFailed",
    "TaskId",
    "TaskNotRunningError",
    "TaskNotTodoError",
    # Ports
    "TaskRepository",
    # Model
    "TaskStatus",
    "UnsupportedEngineError",
    "ValidationError",
    "materialize_task",
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
    NodeRowNotFoundError,
    SchedulingError,
    TaskError,
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
    NodeStatus,
    ProcessResult,
    Task,
    TaskId,
    TaskStatus,
    materialize_task,
)
from .ports import (
    CloudConfig,
    CloudProvisioner,
    MachineRepository,
    MachineSession,
    NodeRepository,
    TaskRepository,
)
from .settings import LocalSettings, RemoteDefaults

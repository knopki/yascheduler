## Purpose

Define one typed error vocabulary for domain failures. Callers catch
specific business errors instead of parsing messages.

## Requirements

### Requirement: Single hierarchy root

The system SHALL expose one root exception for every domain failure.
Every domain exception SHALL descend from that root, so a caller
catches the full set with a single handler.

#### Scenario: every domain failure is catchable via the root

- **WHEN** any domain exception is raised
- **THEN** a handler on the domain root catches it

### Requirement: Exception catalog

The system SHALL expose the domain exceptions below. Each exception
SHALL carry the identity listed in the third column and pass it to the
caller. For task and node failures, the message SHALL contain the bare
integer identity.

| Exception | Failure mode | Carried identity |
| --- | --- | --- |
| UnsupportedEngineError | Requested engine is unknown. | `engine_name` |
| MissingInputFileError | Required engine input file is absent. | `engine_name`, `filename` |
| TaskNotTodoError | Task is not in TODO status. | `task_id` |
| TaskNotRunningError | Task is not in RUNNING status. | `task_id` |
| MachineBusyError | Operation targets a busy machine. | `node_id` only |
| MachineConnectionError | SSH connection to a machine failed. | `node_id`, `hostname`, `reason` |
| NoCompatibleNodeError | No node matches the task. | `task_id`, `platforms` |
| CloudCapacityExhaustedError | No cloud provider has capacity. | `task_id` |
| CloudAllocateError | Provider selection or VM creation failed. | free-form message |
| CloudSetupError | VM setup (SSH, cloud-init, engine install) failed. | free-form message |

#### Scenario: identity survives to the caller

- **WHEN** a domain exception listed in the catalog is raised
- **THEN** the caller reads each carried identity attribute named in the catalog, and the message carries the bare integer form of any task or node identity

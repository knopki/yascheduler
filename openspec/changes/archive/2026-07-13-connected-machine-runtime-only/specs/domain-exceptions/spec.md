## MODIFIED Requirements

### Requirement: MachineBusyError

The system SHALL provide `MachineBusyError(DomainError)` for operations
attempted on a busy machine. The constructor SHALL take
`node_id: NodeId` as the sole argument and store it as an instance attribute.

The exception message format SHALL be:
`f"machine ({node_id}) is busy"`.

The exception SHALL NOT carry a `hostname` attribute. `node_id` is the stable
identity; operators resolve the node's transport address via `yanodes` or the
DB. (Contrast with `MachineConnectionError`, which retains its `hostname`
attribute because the exception is raised at the transport layer where the
machine does not yet exist and `node.hostname` is the operator-recognizable
address.)

#### Scenario: MachineBusyError carries node_id only

- **WHEN** `MachineBusyError(NodeId(1))` is raised
- **THEN** `e.node_id == NodeId(1)`, the exception message contains the bare integer `"1"` (NOT `"NodeId(value=1)"`), the exception does NOT have a `hostname` attribute, and the message format is `"machine (1) is busy"`

#### Scenario: MachineBusyError is catchable as DomainError

- **WHEN** a `MachineBusyError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

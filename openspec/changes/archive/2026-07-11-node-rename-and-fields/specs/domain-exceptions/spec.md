## MODIFIED Requirements

### Requirement: MachineBusyError

The system SHALL provide `MachineBusyError(DomainError)` for operations
attempted on a busy machine. The constructor SHALL take
`node_id: NodeId` as the first argument and `hostname: str` as the second,
storing both as instance attributes.

The exception message format SHALL be:
`f"machine ({node_id}) at {hostname} is busy"`.

#### Scenario: MachineBusyError carries node_id and hostname
- **WHEN** `MachineBusyError(NodeId(1), "10.0.0.1")` is raised
- **THEN** `e.node_id == NodeId(1)`, `e.hostname == "10.0.0.1"`, and the exception message contains both the node_id and hostname

### Requirement: MachineConnectionError

The system SHALL provide `MachineConnectionError(DomainError)` for connection
failures when establishing SSH connections to remote machines. The constructor
SHALL take `node_id: NodeId` as the first argument, `hostname: str` as the
second, and `reason: str` as the third, storing all three as instance
attributes.

The exception message format SHALL be:
`f"cannot connect to machine ({node_id}) at {hostname}: {reason}"`.

#### Scenario: MachineConnectionError carries node_id, hostname, and reason
- **WHEN** `MachineConnectionError(NodeId(1), "10.0.0.1", "Connection refused")` is raised
- **THEN** `e.node_id == NodeId(1)`, `e.hostname == "10.0.0.1"`, `e.reason == "Connection refused"`, and the exception message contains the node_id, hostname, and reason

#### Scenario: MachineConnectionError is catchable as DomainError
- **WHEN** a `MachineConnectionError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`
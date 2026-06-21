## ADDED Requirements

### Requirement: MachineConnectionError

The system SHALL provide `MachineConnectionError(DomainError)` for connection
failures when establishing SSH connections to remote machines.

#### Scenario: MachineConnectionError carries IP and reason
- **WHEN** `MachineConnectionError("10.0.0.1", "Connection refused")` is raised
- **THEN** `e.ip == "10.0.0.1"` and the exception message contains both the IP and reason

#### Scenario: MachineConnectionError is catchable as DomainError
- **WHEN** a `MachineConnectionError` is raised
- **THEN** it is caught by `except DomainError` and `except Exception`

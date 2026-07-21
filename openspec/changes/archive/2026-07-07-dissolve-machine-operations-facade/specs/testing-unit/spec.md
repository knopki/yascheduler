## MODIFIED Requirements

### Requirement: Domain port Protocol conformance

Tests SHALL verify that stub implementations satisfy `@runtime_checkable`
Protocol checks for `TaskRepository`, `NodeRepository`, `MachineRepository`,
`MachineSession`, `CloudProvisioner` from `yascheduler.domain.ports`.
The former `MachineOperations` Protocol is removed (the
`SSHMachineOperations` facade is dissolved); operations-side collaborators
(`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`) are concrete
classes and are not subject to Protocol conformance checks.

#### Scenario: Stub implementations satisfy Protocol checks

- **WHEN** stub classes with matching async method signatures are checked against `TaskRepository`, `NodeRepository`, `MachineRepository`, `MachineSession`, `CloudProvisioner`
- **THEN** `isinstance` returns `True` for each

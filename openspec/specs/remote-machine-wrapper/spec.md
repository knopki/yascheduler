# RemoteMachine Wrapper

## Purpose

Transitional compatibility wrapper that delegated SSH operations from the legacy
RemoteMachine interface to SSHMachineGateway during the migration to
infra/ssh/. The remote_machine/ package and all wrappers are removed; use
SSHMachineGateway or the MachineGateway Protocol from domain/ports.py directly.

## Requirements

### Requirement: Wrapper code removed

The system SHALL delete the `remote_machine/` package and all compatibility
wrappers (RemoteMachine, RemoteMachineRepository). Consumers SHALL use
`SSHMachineGateway` from `infra/ssh/gateway.py` or the `MachineGateway`
Protocol from `domain/ports.py` for SSH operations.

#### Scenario: Import from new location
- **WHEN** SSH operations are needed
- **THEN** SSHMachineGateway is imported from adapters.ssh.gateway

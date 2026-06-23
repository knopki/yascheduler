## MODIFIED Requirements

### Requirement: Wrapper code removed

The system SHALL delete the `remote_machine/` package and all compatibility
wrappers (RemoteMachine, RemoteMachineRepository). Consumers SHALL use
`SSHMachineGateway` from `infra/ssh/gateway.py` or the `MachineGateway`
Protocol from `domain/ports.py` for SSH operations.

#### Scenario: Import from new location
- **WHEN** SSH operations are needed
- **THEN** SSHMachineGateway is imported from infra.ssh.gateway

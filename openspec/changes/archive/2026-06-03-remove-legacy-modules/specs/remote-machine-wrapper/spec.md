## REMOVED Requirements

### Requirement: RemoteMachine delegates to SSHMachineGateway
**Reason**: The `remote_machine/` package is deleted. `SSHMachineGateway` is now the sole SSH adapter. Use cases use the `MachineGateway` port directly.
**Migration**: Use `SSHMachineGateway` or the `MachineGateway` Protocol from `domain/ports.py` instead of `RemoteMachine`.

### Requirement: Wrapper preserves cloud module compatibility
**Reason**: The `clouds/` package is deleted. Cloud provisioning uses `CloudProvisionerImpl` directly.
**Migration**: Use `CloudProvisionerImpl` from `adapters/cloud/manager.py` instead of `CloudAPI`.

### Requirement: RemoteMachineRepository retains filter logic
**Reason**: Machine registry is now maintained by `SSHMachineGateway`. The `RemoteMachineRepository` class is removed.
**Migration**: Use `gateway.list_free(platforms)` for free-machine queries, `gateway.disconnect(ip)` for disconnection, and `gateway.disconnect_all()` for bulk cleanup.

### Requirement: Old imports preserved
**Reason**: The `remote_machine/` package is deleted. No backward-compatible re-exports needed.
**Migration**: Import types from `adapters/ssh/` and `domain/ports.py` instead.

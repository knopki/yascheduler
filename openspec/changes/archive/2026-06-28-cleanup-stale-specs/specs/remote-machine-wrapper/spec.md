## REMOVED Requirements

### Requirement: Wrapper code removed
**Reason**: The `remote_machine/` package and all compatibility wrappers (RemoteMachine, RemoteMachineRepository) were removed in the completed `2026-06-03-remove-legacy-modules` migration. The spec additionally referenced `SSHMachineGateway`, which was itself dissolved by `2026-06-27-decompose-ssh-gateway` into `SSHMachineRepository` + `SSHMachineOperations`. The spec was doubly stale.
**Migration**: Read the new `ssh-infrastructure` capability for the SSH adapter contract (repository + session + operations).
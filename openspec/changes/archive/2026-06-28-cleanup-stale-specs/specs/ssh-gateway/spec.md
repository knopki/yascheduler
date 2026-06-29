## REMOVED Requirements

### Requirement: SSHMachineGateway implements MachineGateway
**Reason**: The `SSHMachineGateway` god-class was dissolved by `2026-06-27-decompose-ssh-gateway` into `SSHMachineRepository` (collection) + `SSHMachineOperations` (operations), and the `MachineGateway` Protocol was removed from `domain/ports.py`. The `2026-06-28-session-based-machine-handle` change further split per-machine state into `SSHMachineSession`. This spec described the dissolved class; its live contracts (download_outputs, start_task_on_machine, occupancy, backoff, connection retry) are consolidated in the new `ssh-infrastructure` capability with session-based signatures.
**Migration**: Read the `ssh-infrastructure` capability for the merged SSH adapter contract. `gateway` parameters are now `repository: MachineRepository` + `operations: MachineOperations` (two ports); per-machine operations take `session: MachineSession`.

### Requirement: start_task_on_machine rolls back gateway BUSY on failure
**Reason**: Merged into `ssh-infrastructure`'s `start_task_on_machine rolls back BUSY on failure` requirement with session-based rollback (`session.release()` instead of `repository.update_machine(state.machine.release())`).
**Migration**: See `ssh-infrastructure` — the rollback now operates on `MachineSession` not on a repository `_MachineState`.

### Requirement: `_write_remote_file` re-raises non-SFTP exceptions
**Reason**: Merged verbatim into `ssh-infrastructure` (module-private helper contract is unchanged by the session migration).
**Migration**: See `ssh-infrastructure` requirement `_write_remote_file re-raises non-SFTP exceptions`.

### Requirement: Backoff on operations methods
**Reason**: Merged into `ssh-infrastructure`'s `Backoff on session methods` requirement — the backoff decorators moved from `SSHMachineOperations` methods to `SSHMachineSession` methods (`run_bg`, `upload`, `get_cpu_cores` are now session primitives).
**Migration**: See `ssh-infrastructure` — backoff applies to session methods, not operations methods.

### Requirement: List free machines with platform filter
**Reason**: Merged into `ssh-infrastructure`'s `MachineRepository port` requirement (the `list_free` query is part of the repository Protocol and already has the platform-filter scenario there).
**Migration**: See `ssh-infrastructure` — `list_free(platforms)` scenario is under `MachineRepository port`.

### Requirement: Disconnect and cleanup
**Reason**: Merged into `ssh-infrastructure`'s `SSHMachineRepository implements MachineRepository` requirement (disconnect scoping, per-IP monitor cancellation, `disconnect_all` idempotency).
**Migration**: See `ssh-infrastructure` — disconnect scenarios are under `SSHMachineRepository implements MachineRepository`.

### Requirement: Occupancy monitoring
**Reason**: Merged into `ssh-infrastructure`'s `Occupancy monitoring` requirement — the monitor mechanism moved from the repository to `SSHMachineSession`; `on_free` calls `session.release()` instead of `repository.release(ip)`.
**Migration**: See `ssh-infrastructure` — occupancy monitor is on `MachineSession`, not on `MachineRepository`.

### Requirement: SSH connection retry
**Reason**: Merged verbatim into `ssh-infrastructure`'s `SSH connection retry` requirement (the two-method `connect` pattern with `_connect_impl` backoff is unchanged).
**Migration**: See `ssh-infrastructure` requirement `SSH connection retry`.
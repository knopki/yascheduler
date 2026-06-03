## Why

Phase 4 (part 1) of the architecture migration. The `remote_machine/` package
mixes domain concepts (`RemoteMachine` tracks busy/free state and platform)
with infrastructure (SSH connection, SFTP, command execution). This violates
the hexagonal architecture — domain entities must not know about SSH.

The `MachineGateway` port (defined in Phase 1) and the orchestrator (Phase 3)
expect a clean adapter. This change splits `RemoteMachine` into a domain
`ConnectedMachine` (already defined) and an `SSHMachineGateway` adapter.

## What Changes

- Create `adapters/ssh/gateway.py` — `SSHMachineGateway` implementing
  `MachineGateway` Protocol. Wraps asyncssh for connection management, command
  execution, SFTP, and occupancy monitoring.
- Move platform-specific code into `adapters/ssh/platform/`: checks,
  adapters, linux_methods, windows_methods, common, protocols.
- `RemoteMachine` becomes a thin compatibility wrapper for existing callers
  that haven't migrated yet (scheduler, clouds module). All SSH logic
  delegates to `SSHMachineGateway`.
- `RemoteMachineRepository` is absorbed into `SSHMachineGateway` — the
  gateway itself maintains the in-memory registry of connected machines
  (concurrent access to the same SSH machine must be managed).
- All callers that now use `MachineGateway` port (orchestrator, use cases)
  switch to `SSHMachineGateway`.

## Capabilities

### New Capabilities
- `ssh-gateway`: `SSHMachineGateway` adapter implementing `MachineGateway`
  Protocol — SSH connection lifecycle, command execution, file transfer,
  occupancy monitoring.
- `platform-adapters`: Platform detection and per-OS command adapters moved
  from `remote_machine/` to `adapters/ssh/platform/`.
- `remote-machine-wrapper`: `RemoteMachine` refactored as a thin compatibility
  wrapper delegating to `SSHMachineGateway` — preserves API for unmigrated
  callers (cloud modules).

### Modified Capabilities
<!-- No existing specs affected. -->

## Impact

- New directory: `adapters/ssh/` with `gateway.py`, `platform/` (6 files moved).
- Modified: `remote_machine/` — `RemoteMachine` becomes thin wrapper;
  `RemoteMachineRepository` absorbed into gateway.
- Modified: `scheduler.py` — switches from `RemoteMachineRepository` to
  `SSHMachineGateway` (via orchestrator/DI).
- Modified: `clouds/` — continues using `RemoteMachine` wrapper (unchanged
  until Phase 4 part 2).
- No new dependencies — asyncssh already in project.
- `docs/knowledge-graph.xml` updated.

## MODIFIED Requirements

### Requirement: Remote machine management

Tests SHALL verify `ConnectedMachine` state transitions (`occupy`/`release`
toggling `free_since` via `MachineSession.occupy()`/`MachineSession.release()`),
and `SSHMachineRepository.list_free(platforms)` filtering (busy exclusion,
platforms filter, oldest-first ordering by `free_since`, original registry
unchanged). The legacy `RemoteMachineMetadata`, `is_free_longer_than`, and
`RemoteMachineRepository.filter` symbols are removed; tests target the
session/repository split defined in the `ssh-infrastructure` capability.

#### Scenario: ConnectedMachine occupy sets state to BUSY

- **WHEN** `session.occupy()` is called on a session whose `machine.state` is FREE
- **THEN** `session.machine.state` becomes BUSY and `session.machine.free_since` remains its prior value (only `release` resets `free_since`)

#### Scenario: ConnectedMachine release resets free_since

- **WHEN** `session.release()` is called on a session whose `machine.state` is BUSY
- **THEN** `session.machine.state` becomes FREE and `session.machine.free_since` is set to `time.monotonic()`

#### Scenario: list_free filters by platform and state

- **WHEN** `repository.list_free(["linux", "debian-12"])` is called on a repository holding FREE linux, BUSY linux, and FREE windows sessions
- **THEN** the returned list contains only the FREE linux session (BUSY excluded, windows excluded by platform filter), sorted oldest-first by `session.machine.free_since`, and the repository's `_sessions` dict is unchanged
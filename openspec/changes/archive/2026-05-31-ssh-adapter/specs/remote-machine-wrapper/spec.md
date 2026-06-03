## ADDED Requirements

### Requirement: RemoteMachine delegates to SSHMachineGateway

The system SHALL refactor RemoteMachine as a thin compatibility wrapper
that delegates all SSH operations to SSHMachineGateway.

#### Scenario: RemoteMachine.run() delegates
- **WHEN** machine.run("ls") is called on a wrapper instance
- **THEN** SSHMachineGateway.run() is called internally

#### Scenario: RemoteMachine.sftp() delegates
- **WHEN** async with machine.sftp() as sftp is used
- **THEN** SSHMachineGateway provides the SFTP session

#### Scenario: RemoteMachine.meta preserved
- **WHEN** a wrapper's meta attribute is accessed
- **THEN** it returns a RemoteMachineMetadata with busy/free state
  synchronized from the gateway's ConnectedMachine

### Requirement: Wrapper preserves cloud module compatibility

The system SHALL ensure RemoteMachine.create() and RemoteMachine.create_ctx()
still work for callers in the clouds/ package.

#### Scenario: Cloud module calls RemoteMachine.create()
- **WHEN** CloudAPI calls RemoteMachine.create(host=..., username=..., ...)
- **THEN** an SSH connection is established via SSHMachineGateway, but the
  caller receives a RemoteMachine wrapper with the familiar API

### Requirement: RemoteMachineRepository retains filter logic

The system SHALL keep RemoteMachineRepository's `filter()` as a self-contained
dict-based operation. It operates on the repository's local `data` dict using
predicate-based filtering (busy, platforms, free_since_gt, reverse_sort).
SSHMachineGateway.list_free() remains available as a separate, simpler
query for FREE machines by platform — used independently by gateway consumers.

#### Scenario: repo.filter() performs dict-based filtering
- **WHEN** code calls repo.filter(busy=False, platforms=["linux"], reverse_sort=True)
- **THEN** the repository filters its local `data` dict by the given predicates
  and returns an evolved copy with matching machines

#### Scenario: gateway.list_free() provides simple FREE-machine query
- **WHEN** code calls gateway.list_free(["linux"])
- **THEN** the gateway returns FREE machines filtered by platform from its internal registry

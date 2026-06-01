# SSH Gateway

## Purpose

Provide an SSHMachineGateway class that satisfies the MachineGateway Protocol
using asyncssh for SSH connections, command execution, and SFTP transfer, with
connection lifecycle, occupancy monitoring, and retry logic.

## Requirements

### Requirement: SSHMachineGateway implements MachineGateway

The system SHALL provide an `SSHMachineGateway` class that satisfies the
`MachineGateway` Protocol using asyncssh for SSH connections, command
execution, and SFTP.

#### Scenario: Connect to machine
- **WHEN** `gateway.connect(ip="10.0.0.1", username="root", client_keys=[...])` is called
- **THEN** an SSH connection is established, platform is detected, and a
  `ConnectedMachine` is registered internally

#### Scenario: Run command on connected machine
- **WHEN** `gateway.run(machine, "echo hello")` is called on a connected machine
- **THEN** returns a `ProcessResult` with the command output

#### Scenario: Upload file
- **WHEN** `gateway.upload(machine, local_path, "/remote/path")` is called
- **THEN** the file is transferred via SFTP to the remote path

#### Scenario: Download file
- **WHEN** `gateway.download(machine, "/remote/path", local_path)` is called
- **THEN** the file is transferred via SFTP to the local path

### Requirement: List free machines with platform filter

The system SHALL return only FREE machines that match the requested platforms.

#### Scenario: Filter by platform
- **WHEN** `gateway.list_free(["linux", "debian-12"])` is called
- **THEN** returns only FREE machines with platform "linux" or "debian-12"

#### Scenario: Empty list when no match
- **WHEN** `gateway.list_free(["windows"])` is called and no Windows machines are connected
- **THEN** returns an empty list

### Requirement: Disconnect and cleanup

The system SHALL support disconnecting specific machines or all machines,
closing SSH connections and removing from the registry.

#### Scenario: Disconnect single machine
- **WHEN** `gateway.disconnect("10.0.0.1")` is called
- **THEN** the SSH connection is closed and the machine is removed from the registry

#### Scenario: Disconnect all
- **WHEN** `gateway.disconnect_all()` is called
- **THEN** all SSH connections are closed and the registry is cleared

### Requirement: Occupancy monitoring

The system SHALL periodically check if an engine process is still running on
a machine and update the machine state to FREE when the process exits.

#### Scenario: Process exits, machine becomes free
- **WHEN** occupancy check detects the engine process has exited
- **THEN** the `ConnectedMachine` state is updated to FREE with `free_since` set

### Requirement: SSH connection retry

The system SHALL retry SSH connections on transient failures using the
`backoff` library with the same exception types as the current
`RemoteMachine.create()`.

#### Scenario: Retry on connection refused
- **WHEN** SSH connection fails with a retryable exception
- **THEN** the connection is retried with exponential backoff up to 60 seconds

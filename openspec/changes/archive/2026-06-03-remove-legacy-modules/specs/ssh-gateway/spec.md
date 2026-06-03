## ADDED Requirements

### Requirement: SSHMachineGateway owns shared SSH infrastructure

The system SHALL provide all SSH infrastructure constants and helpers in
`adapters/ssh/helpers.py`, including `ADAPTERS` registry, `DEFAULT_CONN_OPTS`,
`MySSHClient`, `MAX_SESSIONS`, `my_backoff_exc`, `_detect_platform`,
`_init_paths`, and `_resolve_tunnel`. `SSHMachineGateway` SHALL import these
from `adapters/ssh/helpers.py`, not from `remote_machine/`.

#### Scenario: Gateway imports helpers from own package
- **WHEN** `gateway.py` imports `ADAPTERS`, `DEFAULT_CONN_OPTS`, `_detect_platform`
- **THEN** they are imported from `adapters/ssh/helpers.py`

#### Scenario: Helpers functional equivalence
- **WHEN** `_detect_platform(conn, adapters)` is called from the new location
- **THEN** it returns the same adapter and platform list as the old implementation

## MODIFIED Requirements

### Requirement: SSHMachineGateway implements MachineGateway

The system SHALL provide an `SSHMachineGateway` class that satisfies the
`MachineGateway` Protocol using asyncssh for SSH connections, command
execution, and SFTP. The gateway SHALL be self-contained — it SHALL NOT import
from `remote_machine/` or `clouds/`.

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

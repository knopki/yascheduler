## MODIFIED Requirements

### Requirement: SSHMachineGateway implements MachineGateway

The system SHALL provide an `SSHMachineGateway` class that satisfies the
`MachineGateway` Protocol using asyncssh for SSH connections, command
execution, and SFTP. The gateway SHALL be self-contained — it SHALL NOT import
from `remote_machine/` or `clouds/`.

The gateway SHALL provide a `download_outputs` method that encapsulates SFTP
session management, per-file download with retry, and remote directory cleanup.
The method SHALL return `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]`
containing `(meta_add, sftp_errors)`. The method SHALL catch all exceptions
(including non-retry) and return them in the `sftp_errors` list.

The gateway SHALL provide a `_get_machine_state` method returning `_MachineState | None`
for adapter-internal use (e.g., `check_status.py`), and a `get_machine_state` method
returning `ConnectedMachine | None` for the port contract.

The gateway SHALL provide a `start_task_on_machine(machine, engine, task, ncpus, engines_dir) -> bool`
method that uploads task input files via SFTP and spawns the calculation process
via `run_bg`. The method SHALL encapsulate all SSH-specific operations
(`get_sftp`, `get_path`, `get_quote`, `makedirs`, remote file writes) — no such
operations SHALL remain in the orchestrator. The gateway MAY use private helpers
(`_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
`_safe_b64decode`) to structure the work.

The gateway SHALL provide `pgrep(ip, pattern, full=True) -> AsyncGenerator[ProcessInfo, None]`
and `list_processes(ip) -> AsyncGenerator[ProcessInfo, None]` that delegate to
the platform adapter. `ProcessInfo` is the frozen dataclass from
`infra/ssh/platform/protocol.py` (re-exported via the package
`yascheduler.infra.ssh.platform`). The gateway SHALL NOT reference the `PProcessInfo`
Protocol.

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

#### Scenario: Download task outputs with retry
- **WHEN** `gateway.download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
- **THEN** SFTP session is opened, each file is downloaded with per-file retry,
  remote directory is removed, and `(meta_add, sftp_errors)` is returned

#### Scenario: Download outputs catches all exceptions
- **WHEN** `download_outputs` encounters a non-retryable exception
- **THEN** the exception is caught and returned in `sftp_errors` list, not raised

#### Scenario: List connected machines
- **WHEN** `gateway.list_connected()` is called
- **THEN** returns a list of all `ConnectedMachine` objects currently registered

#### Scenario: Get machine state for port
- **WHEN** `gateway.get_machine_state("10.0.0.1")` is called
- **THEN** returns `ConnectedMachine | None` (domain entity, not adapter internals)

#### Scenario: Get machine state for adapter-internal use
- **WHEN** `gateway._get_machine_state("10.0.0.1")` is called
- **THEN** returns `_MachineState | None` (adapter-internal dataclass)

#### Scenario: pgrep and list_processes return ProcessInfo
- **WHEN** `gateway.pgrep(ip, pattern)` or `gateway.list_processes(ip)` is called on a connected machine
- **THEN** the returned async generator yields `ProcessInfo` objects (the frozen dataclass from `infra/ssh/platform/protocol.py`), and the gateway does not reference `PProcessInfo`
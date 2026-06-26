## MODIFIED Requirements

### Requirement: SSHMachineGateway implements MachineGateway

The system SHALL provide an `SSHMachineGateway` class that satisfies the
`MachineGateway` Protocol using asyncssh for SSH connections, command
execution, and SFTP. The gateway SHALL be self-contained — it SHALL NOT import
from `remote_machine/` or `clouds/`.

The gateway SHALL provide a `download_outputs` method that encapsulates SFTP
session management, per-file download with retry, error classification, and
remote directory cleanup. The method SHALL return
`tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]`
containing `(meta_add, transient_errors, permanent_errors)`. The method SHALL
catch all per-file exceptions (including non-retry) and classify each into
`transient_errors` (instances of `SFTPRetryExc`) or `permanent_errors` (all
other caught exceptions, including `SFTPNoSuchFile`, `SFTPPermissionDenied`,
and bare `OSError` from local filesystem writes). The method SHALL catch all
session-level exceptions and return them in `transient_errors` (a
session-level failure is transient — the remote directory is preserved for
retry). The method SHALL NOT raise.

The method SHALL remove the remote directory tree only when `transient_errors`
is empty after the per-file loop — i.e. on full success or when only permanent
errors occurred. When `transient_errors` is non-empty, the method SHALL NOT
remove the remote directory tree (the undownloaded files must remain available
for the next retry cycle).

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

#### Scenario: Download task outputs with retry and classification
- **WHEN** `gateway.download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
- **THEN** SFTP session is opened, each file is downloaded with per-file retry,
  per-file exceptions are classified into `transient_errors` (instances of
  `SFTPRetryExc`) and `permanent_errors` (all other caught exceptions), and
  `(meta_add, transient_errors, permanent_errors)` is returned

#### Scenario: Remote directory removed on full success or permanent-only errors
- **WHEN** `download_outputs` completes the per-file loop with `transient_errors` empty (full success or only permanent errors)
- **THEN** the remote directory tree is removed via `sftp.rmtree`

#### Scenario: Remote directory preserved on transient errors
- **WHEN** `download_outputs` completes the per-file loop with `transient_errors` non-empty
- **THEN** the remote directory tree is NOT removed (undownloaded files remain available for retry)

#### Scenario: Download outputs catches all exceptions
- **WHEN** `download_outputs` encounters a non-retryable per-file exception
- **THEN** the exception is caught and classified into `permanent_errors`, not raised

#### Scenario: Session-level failure is transient and preserves remote dir
- **WHEN** `download_outputs` encounters a session-level failure (e.g. connection lost before the per-file loop completes)
- **THEN** the exception is caught, recorded in `transient_errors`, the remote directory is NOT removed, and the method returns without raising

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
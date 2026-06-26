# SSH Gateway

## Purpose

Provide an SSHMachineGateway class that satisfies the MachineGateway Protocol
using asyncssh for SSH connections, command execution, and SFTP transfer, with
connection lifecycle, occupancy monitoring, and retry logic.

## Requirements

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

### Requirement: Backoff on gateway methods

The system SHALL apply `@my_backoff_exc()` (fibonacci, max_time=60, SSHRetryExc)
to the following methods: `run_bg`, `get_cpu_cores`. The system SHALL apply
`@my_backoff_sftp()` (fibonacci, max_time=60, SFTPRetryExc) to the following
methods: `upload`, `download`.

#### Scenario: run_bg retries on SSH failure
- **WHEN** `run_bg` fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds

#### Scenario: upload retries on SFTP failure
- **WHEN** `upload` fails with a retryable SFTP exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds

#### Scenario: download retries on SFTP failure
- **WHEN** `download` fails with a retryable SFTP exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds

#### Scenario: get_cpu_cores retries on SSH failure
- **WHEN** `get_cpu_cores` fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60 seconds

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
`backoff` library with fibonacci backoff and `max_time=60`. The gateway
SHALL use a two-method pattern for `connect()`: inner `_connect_impl` with
`@my_backoff_exc()` decorator (retries on `SSHRetryExc`), outer `connect`
translates exhausted `(asyncssh.misc.Error, OSError)` exceptions to `MachineConnectionError`.

#### Scenario: Retry on connection refused
- **WHEN** SSH connection fails with a retryable exception (in `SSHRetryExc`)
- **THEN** the connection is retried with fibonacci backoff up to 60 seconds

#### Scenario: Non-retryable error skips retry
- **WHEN** SSH connection fails with a non-retryable exception (e.g., `PermissionDenied`)
- **THEN** the error is NOT retried and immediately translated to `MachineConnectionError`

#### Scenario: Exhausted retry raises MachineConnectionError
- **WHEN** all retry attempts are exhausted
- **THEN** the outer `connect` method catches `(asyncssh.misc.Error, OSError)` and raises `MachineConnectionError` wrapping the last exception

### Requirement: SSHMachineGateway owns shared SSH infrastructure

The system SHALL provide all SSH infrastructure constants and helpers in
`infra/ssh/helpers.py`, including `ADAPTERS` registry, `DEFAULT_CONN_OPTS`,
`MySSHClient`, `MAX_SESSIONS`, `my_backoff_exc`, `_detect_platform`,
`_init_paths`, and `_resolve_tunnel`. `SSHMachineGateway` SHALL import these
from `infra/ssh/helpers.py`, not from `remote_machine/`.

#### Scenario: Gateway imports helpers from own package
- **WHEN** `gateway.py` imports `ADAPTERS`, `DEFAULT_CONN_OPTS`, `_detect_platform`
- **THEN** they are imported from `infra/ssh/helpers.py`

#### Scenario: Helpers functional equivalence
- **WHEN** `_detect_platform(conn, adapters)` is called from the new location
- **THEN** it returns the same adapter and platform list as the old implementation

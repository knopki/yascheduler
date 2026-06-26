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
closing SSH connections, cancelling that machine's occupancy monitor (if
any), and removing the machine from the registry.

`disconnect(ip)` SHALL be scoped to the targeted IP. It SHALL cancel only
the background occupancy task registered for `ip` (if present) and SHALL
NOT cancel background tasks registered for any other machine. After
`disconnect(ip)` returns, the occupancy monitors for every other still
connected machine SHALL remain alive and uncanceled.

The system SHALL maintain a one-to-one mapping between a connected machine
IP and its occupancy monitor. Re-registering `start_occupancy_check(ip,
config)` for an already-monitored IP SHALL replace the prior monitor;
the replaced monitor SHALL be cancelled before the new one is installed.

`disconnect_all()` SHALL disconnect every currently connected machine by
invoking `disconnect(ip)` once per machine. The observable aggregate result
(all machines disconnected, all occupancy monitors cancelled) is unchanged.

#### Scenario: Disconnect single machine

- **WHEN** `gateway.disconnect("10.0.0.1")` is called on a connected machine
- **THEN** the SSH connection for `10.0.0.1` is closed, the machine is
  removed from the registry, and any occupancy monitor registered for
  `10.0.0.1` is cancelled and awaited

#### Scenario: Disconnect does not touch other machines' monitors

- **WHEN** machines A, B, and C are connected, each has an occupancy monitor
  registered via `start_occupancy_check`, and `gateway.disconnect("B")` is
  called
- **THEN** only the monitor registered for B is cancelled, the monitors for
  A and C remain alive (not cancelled) and remain registered for their
  respective IPs, and machines A and C stay connected

#### Scenario: Disconnect unknown IP

- **WHEN** `gateway.disconnect("10.0.0.99")` is called for an IP with no
  registered machine
- **THEN** no exception is raised, no occupancy monitor for any other IP is
  cancelled, and the registry of connected machines is unchanged

#### Scenario: Disconnect all

- **WHEN** `gateway.disconnect_all()` is called
- **THEN** every connected machine's SSH connection is closed, every
  connected machine is removed from the registry, and every registered
  occupancy monitor is cancelled

#### Scenario: Re-registering occupancy for an IP replaces the prior monitor

- **WHEN** `start_occupancy_check(ip, config)` is called for an IP that
  already has a live occupancy monitor
- **THEN** the prior monitor is cancelled and the new monitor is installed
  under the same IP key, without affecting monitors registered for other IPs

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

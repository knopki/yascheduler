# SSH Gateway

## Purpose

Provide SSH machine infrastructure split across SSHMachineRepository (connected-machine collection lifecycle, queries, state transitions, occupancy-monitor mechanism) and SSHMachineOperations (per-machine command execution, SFTP transfer, process inspection, node setup, task deployment, output download, and occupancy check logic). Both implement the MachineRepository and MachineOperations domain ports respectively using asyncssh for SSH connections and SFTP, with retry logic on idempotent operations.

## Requirements

### Requirement: SSHMachineGateway implements MachineGateway

The system SHALL provide SSH machine operations and connection
management split across two implementation classes:

- `SSHMachineRepository` in `infra/ssh/repository.py` — owns the
  connected-machine collection, implements the `MachineRepository`
  Protocol. Provides `connect`/`disconnect`/`disconnect_all`,
  `list_free`/`list_connected`/`get_machine_state`, `update_machine`/
  `occupy`/`release`, accessor getters, `get_conn` (reconnect), and the
  generic occupancy-monitor mechanism (`install_monitor`/`cancel_monitor`).
- `SSHMachineOperations` in `infra/ssh/operations/` — operates on a
  single machine via the platform adapter and SFTP, implements the
  `MachineOperations` Protocol. Composes `TaskDeployer`,
  `OutputDownloader`, `OccupancyChecker`.

The system SHALL NOT provide a single `SSHMachineGateway` class. The
`MachineGateway` Protocol in `domain/ports.py` SHALL be removed and
replaced by `MachineRepository` + `MachineOperations`.

`SSHMachineOperations.download_outputs(ip, remote_dir, local_dir, files,
task_id)` SHALL return
`tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]],
list[tuple[str | None, Exception]]]` containing `(meta_add,
transient_errors, permanent_errors)`. The method SHALL catch all
per-file exceptions (including non-retry) and classify each into
`transient_errors` (instances of `SFTPRetryExc`) or `permanent_errors`
(all other caught exceptions, including `SFTPNoSuchFile`,
`SFTPPermissionDenied`, and bare `OSError` from local filesystem
writes). The method SHALL catch all session-level exceptions and return
them in `transient_errors` (a session-level failure is transient — the
remote directory is preserved for retry). The method SHALL NOT raise.

The method SHALL open a FRESH SFTP client (`get_sftp(ip)` context) per
file in the per-file loop, so that a dropped SFTP connection on one file
invalidates only that file's retries and does not fail-fast the
remaining files on a dead shared client. The per-file retry
(`file_get_retry`, fibonacci, max_time=60, `SFTPRetryExc`) SHALL wrap
each `sftp.get` call individually.

The method SHALL remove the remote directory tree only ONCE, after the
per-file loop completes, and only when BOTH `transient_errors` AND
`permanent_errors` are empty — i.e. on full success only. When either
list is non-empty, the method SHALL NOT remove the remote directory tree
(any undownloaded file, whether transient or permanent, must remain
available for the next retry cycle or for operator debugging). The
rmtree SHALL use its own separate `get_sftp(ip)` context (not a
per-file client).

The repository SHALL provide a `_get_machine_state` method returning
`_MachineState | None` for adapter-internal use (e.g.,
`check_status.py`), and a `get_machine_state` method returning
`ConnectedMachine | None` for the port contract.

The operations SHALL provide a `start_task_on_machine(machine, engine,
task, ncpus, engines_dir) -> bool` method (forwarding to
`deploy.start_task_on_machine`) that uploads task input files via SFTP
and spawns the calculation process via `run_bg`. The method SHALL
encapsulate all SSH-specific operations (`get_sftp`, `get_path`,
`get_quote`, `makedirs`, remote file writes) — no such operations SHALL
remain in the orchestrator. The implementation MAY use private helpers
(`_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`,
`_safe_b64decode`) within `operations/deployment.py`.

The operations SHALL provide `pgrep(ip, pattern, full=True) ->
AsyncGenerator[ProcessInfo, None]` and `list_processes(ip) ->
AsyncGenerator[ProcessInfo, None]` that delegate to the platform
adapter. `ProcessInfo` is the frozen dataclass from
`infra/ssh/platform/protocol.py`. The operations SHALL NOT reference the
`PProcessInfo` Protocol.

#### Scenario: Connect to machine

- **WHEN** `repository.connect(ip="10.0.0.1", username="root", client_keys=[...])` is called
- **THEN** an SSH connection is established, platform is detected, and a
  `ConnectedMachine` is registered in the repository's `_machines`

#### Scenario: Run command on connected machine

- **WHEN** `operations.run(machine, "echo hello")` is called on a connected machine
- **THEN** returns a `ProcessResult` with the command output

#### Scenario: Upload file

- **WHEN** `operations.upload(machine, local_path, "/remote/path")` is called
- **THEN** the file is transferred via SFTP to the remote path (single attempt, no retry)

#### Scenario: Download file

- **WHEN** `operations.download(machine, "/remote/path", local_path)` is called
- **THEN** the file is transferred via SFTP to the local path (single attempt, no retry)

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `operations.download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each
  file is downloaded with per-file retry (`file_get_retry`,
  fibonacci, max_time=60, `SFTPRetryExc`), per-file exceptions are
  classified into `transient_errors` (instances of `SFTPRetryExc`)
  and `permanent_errors` (all other caught exceptions), and
  `(meta_add, transient_errors, permanent_errors)` is returned

#### Scenario: Remote directory removed only on full success

- **WHEN** `download_outputs` completes the per-file loop with both
  `transient_errors` and `permanent_errors` empty (full success)
- **THEN** the remote directory tree is removed ONCE via `sftp.rmtree`
  using a separate `get_sftp(ip)` context after the loop

#### Scenario: Remote directory preserved on any errors

- **WHEN** `download_outputs` completes the per-file loop with
  `transient_errors` non-empty OR `permanent_errors` non-empty
- **THEN** the remote directory tree is NOT removed (undownloaded
  files — whether transient or permanent — remain available for retry
  or operator debugging)

#### Scenario: Per-file SFTP isolation bounds dead-connection blast radius

- **WHEN** `download_outputs` is downloading files [f1, f2, f3] and the
  SFTP connection drops during f2's transfer
- **THEN** f2's per-file retry exhausts on the dead f2 client and
  classifies f2 as transient, but f3 is downloaded via a FRESH
  `get_sftp(ip)` client and retries normally (not fail-fast on a dead
  shared client)

#### Scenario: Download outputs catches all exceptions

- **WHEN** `download_outputs` encounters a non-retryable per-file exception
- **THEN** the exception is caught and classified into `permanent_errors`, not raised

#### Scenario: Session-level failure is transient and preserves remote dir

- **WHEN** `download_outputs` encounters a session-level failure (e.g.
  `get_sftp(ip)` itself raises before the per-file loop body executes)
- **THEN** the exception is caught by the single outer
  `try/except Exception`, recorded in `transient_errors`, the remote
  directory is NOT removed, and the method returns without raising

#### Scenario: List connected machines

- **WHEN** `repository.list_connected()` is called
- **THEN** returns a list of all `ConnectedMachine` objects currently registered

#### Scenario: Get machine state for port

- **WHEN** `repository.get_machine_state("10.0.0.1")` is called
- **THEN** returns `ConnectedMachine | None` (domain entity, not adapter internals)

#### Scenario: Get machine state for adapter-internal use

- **WHEN** `repository._get_machine_state("10.0.0.1")` is called
- **THEN** returns `_MachineState | None` (adapter-internal dataclass)

#### Scenario: pgrep and list_processes return ProcessInfo

- **WHEN** `operations.pgrep(ip, pattern)` or `operations.list_processes(ip)` is called on a connected machine
- **THEN** the returned async generator yields `ProcessInfo` objects (the frozen dataclass from `infra/ssh/platform/protocol.py`), and the operations object does not reference `PProcessInfo`

### Requirement: start_task_on_machine rolls back gateway BUSY on failure

The `start_task_on_machine` method SHALL roll back the repository-level
BUSY marking on any deploy or spawn failure. The operations'
`start_task_on_machine(machine, engine, task, ncpus,
engines_dir) -> bool` method (implemented in `TaskDeployer`, forwarded
from `SSHMachineOperations`) SHALL roll back the repository-level BUSY
marking on any deploy or spawn failure. The method SHALL mark the
machine BUSY at the repository (via `repository.occupy(machine.ip)`)
before performing the deploy (upload) and spawn
(`_exec_spawn_command` → `run_bg`) steps. If any exception (including
`CancelledError` during daemon shutdown) escapes the deploy or spawn
steps, the method SHALL roll back the repository-level BUSY marking by
calling `repository.update_machine(state.machine.release())` on the
machine registered for `machine.ip`, then re-raise the original
exception. The rollback SHALL run under `except BaseException` so that
`CancelledError` is covered.

The rollback SHALL be defensive against concurrent state changes:

- If the machine is no longer registered for `machine.ip` (e.g.
  `disconnect(ip)` ran concurrently), the method SHALL log a warning
  and re-raise without attempting the rollback.
- If the machine is registered but its state is not `BUSY` (a logic
  error somewhere), the method SHALL log a warning AND still call
  `release()` to enforce the invariant (FREE on failure), then
  re-raise.
- Otherwise the method SHALL log an info line (rollback succeeded) and
  re-raise.

This requirement governs the repository-level occupancy marker only;
the DB task status and the orchestrator's in-memory `mark_running()` are
owned by the caller (`_try_start_on_machine` in
`allocate_task.py:114-144`) and are not affected by this rollback.

#### Scenario: Upload failure rolls back BUSY

- **WHEN** `start_task_on_machine` calls `repository.occupy(machine.ip)`
  marking the machine BUSY, then `_upload_task_data` raises (e.g. an
  `asyncssh.misc.Error` from `sftp.makedirs` or a propagated
  non-SFTP exception from `_write_remote_file`)
- **THEN** the method's `except BaseException` handler calls
  `repository.update_machine(state.machine.release())` on the machine
  registered for `machine.ip`, logging an info line, and re-raises the
  original exception
- **AND** the machine's repository state is `FREE` after the call returns
  (via the raised exception), so the next allocator tick can pick it up

#### Scenario: Spawn failure rolls back BUSY

- **WHEN** `start_task_on_machine` marks the machine BUSY, the upload
  succeeds, then `_exec_spawn_command` → `run_bg` raises (e.g.
  `ChannelOpenError`, no longer retried per the amended Backoff
  requirement)
- **THEN** the method's `except BaseException` handler calls
  `repository.update_machine(state.machine.release())`, logs an info
  line, and re-raises
- **AND** the machine's repository state is `FREE` after the call, and no
  occupancy monitor was installed (it installs only after successful
  spawn)

#### Scenario: CancelledError during deploy rolls back BUSY

- **WHEN** `start_task_on_machine` marks the machine BUSY and the
  daemon is shut down mid-deploy (raising `CancelledError`) before
  spawn completes
- **THEN** the `except BaseException` handler catches the
  `CancelledError`, calls `repository.update_machine(state.machine.release())`,
  logs an info line, and re-raises the `CancelledError`
- **AND** the machine's repository state is `FREE` (not stuck BUSY with
  no owner)

#### Scenario: Concurrent disconnect skips rollback with warning

- **WHEN** `start_task_on_machine` marks the machine BUSY, then
  `repository.disconnect(machine.ip)` runs concurrently and removes the
  machine from the registry, and then the deploy or spawn raises
- **THEN** the rollback handler sees `repository._get_machine_state(machine.ip)`
  is `None`, logs a warning ("machine already disconnected"), and
  re-raises the original exception without attempting `release()`

#### Scenario: Unexpected non-BUSY state still releases and warns

- **WHEN** `start_task_on_machine`'s rollback handler runs and the
  machine registered for `machine.ip` has state other than `BUSY`
  (a logic error somewhere upstream)
- **THEN** the handler logs a warning ("unexpected state <state>,
  expected BUSY"), still calls `repository.update_machine(state.machine.release())`
  to enforce the FREE-on-failure invariant, and re-raises
- **AND** the machine's repository state is `FREE` after the call

### Requirement: `_write_remote_file` re-raises non-SFTP exceptions

The `_write_remote_file` helper SHALL re-raise non-SFTP exceptions.
The deploy module's `_write_remote_file(sftp, path, data, log, mode)`
helper (in `infra/ssh/operations/deployment.py`) SHALL re-raise any
exception that occurs during the SFTP file write. It SHALL NOT swallow
non-SFTP exceptions (e.g. `binascii.Error` from a malformed base64
`fort.9` payload, `TypeError` from a non-string `data`,
`UnicodeEncodeError` on a text-mode write, `KeyError` from a missing
`task.context.extra` key, transient non-SFTP asyncssh errors, or
`OSError`).

The helper MAY catch `asyncssh.misc.Error` specifically to log the
structured SFTP `code` and `reason` fields (which are absent from
`str(err)` at upstream catch sites) and SHALL re-raise it immediately
after logging.

The propagation is the abort signal for `start_task_on_machine`: the
exception surfaces in `_upload_task_data` (which has no `try/except`
around the per-file loop) and then in `start_task_on_machine`'s DEPLOY
block `try/except Exception`, which logs `"Can't upload task_id=N
files: <err>"` (with `task_id`) and re-raises. The engine spawn command
SHALL NOT execute when an input file write has failed.

This requirement governs the module-private helper only; no public
surface (`MachineOperations`/`MachineRepository` Protocol, CLI, INI,
DB schema, AiiDA plugin) changes.

#### Scenario: Non-SFTP exception during write propagates and aborts spawn

- **WHEN** `_write_remote_file` is called and the write raises a non-SFTP
  exception (e.g. `binascii.Error` decoding a malformed `fort.9` base64
  payload, or `TypeError` from `str(non_str)` `data`)
- **THEN** the exception propagates out of `_write_remote_file` without being
  swallowed, propagates through `_upload_task_data` (no `try/except` around
  the per-file loop), and is caught by `start_task_on_machine`'s DEPLOY block
  handler which logs `"Can't upload task_id=N files: <err>"` with the `task_id`
  and re-raises
- **AND** `_exec_spawn_command` is NOT called (the engine spawn command does
  not run, so no calculation proceeds with missing or garbage inputs)

#### Scenario: `asyncssh.misc.Error` is logged with structured code/reason and re-raised

- **WHEN** `_write_remote_file` is called and `sftp.open` or `f.write` raises
  an `asyncssh.misc.Error`
- **THEN** the helper logs `"Write <path> - SFTPError: <reason> (<code>)"`
  with the structured SFTP `code` and `reason` fields
- **AND** re-raises the same exception immediately
- **AND** the exception propagates through `_upload_task_data` and
  `start_task_on_machine` identically to the non-SFTP scenario above (abort,
  no spawn)

#### Scenario: Successful write returns normally

- **WHEN** `_write_remote_file` is called and the write completes without
  raising
- **THEN** the helper returns normally (no exception, no log line)
- **AND** `_upload_task_data` continues to the next input file in the loop

### Requirement: Backoff on operations methods

The system SHALL apply `@my_backoff_exc()` (fibonacci, max_time=60,
`SSHRetryExc`) ONLY to idempotent operations methods — namely
`get_cpu_cores` (a pure read of CPU core count) and the repository's
`_connect_impl` (retried connection establishment). The system SHALL
NOT apply `@my_backoff_exc()` to `run_bg` and SHALL NOT apply
`@my_backoff_sftp()` to `upload` or `download`: these three operations
are non-idempotent (a successful remote side-effect followed by a lost
client confirmation would produce a duplicate side-effect on retry), so
a single attempt with failure-propagation is the correct contract. The
`MachineOperations` Protocol declaration of `run_bg`, `upload`, and
`download` is preserved; only the SSH implementation's retry
decorators are removed.

`download_outputs` SHALL continue to use `my_backoff_sftp()` (defined
in `infra/ssh/operations/download.py`) as the per-file retry wrapper
inside the per-file loop.

#### Scenario: run_bg does not retry on SSH failure

- **WHEN** `run_bg` fails with a retryable SSH exception (e.g.
  `ChannelOpenError`, `ConnectionLost` — both in `SSHRetryExc`)
- **THEN** the operation is NOT retried; the exception propagates
  immediately to the caller (`_exec_spawn_command`, then
  `start_task_on_machine`'s rollback handler, then the orchestrator)
- **AND** no second `asyncssh.create_process` call is made, so no
  duplicate engine process is started for the same task on the same
  machine

#### Scenario: upload does not retry on SFTP failure

- **WHEN** `upload` fails with a retryable SFTP exception (e.g.
  `SFTPConnectionLost` — in `SFTPRetryExc`)
- **THEN** the operation is NOT retried; the exception propagates
  immediately to the caller
- **AND** no second `sftp.put` call is made, so no half-written file
  is left on the remote from a partial retry

#### Scenario: download does not retry on SFTP failure

- **WHEN** `download` fails with a retryable SFTP exception
- **THEN** the operation is NOT retried; the exception propagates
  immediately to the caller
- **AND** no second `sftp.get` call is made, so no half-written file
  is left on the local filesystem from a partial retry

#### Scenario: get_cpu_cores retries on SSH failure

- **WHEN** `get_cpu_cores` fails with a retryable SSH exception
- **THEN** the operation is retried with fibonacci backoff up to 60
  seconds (idempotent read — retry is safe)

### Requirement: List free machines with platform filter

The system SHALL return only FREE machines that match the requested
platforms.

#### Scenario: Filter by platform

- **WHEN** `repository.list_free(["linux", "debian-12"])` is called
- **THEN** returns only FREE machines with platform "linux" or "debian-12"

#### Scenario: Empty list when no match

- **WHEN** `repository.list_free(["windows"])` is called and no Windows machines are connected
- **THEN** returns an empty list

### Requirement: Disconnect and cleanup

The system SHALL support disconnecting specific machines or all
machines, closing SSH connections, cancelling that machine's occupancy
monitor (if any), and removing the machine from the registry.

`repository.disconnect(ip)` SHALL be scoped to the targeted IP. It
SHALL cancel only the background monitor task registered for `ip` (if
present, via `cancel_monitor`) and SHALL NOT cancel monitors
registered for any other machine. After `disconnect(ip)` returns, the
monitors for every other still connected machine SHALL remain alive and
uncanceled.

The system SHALL maintain a one-to-one mapping between a connected
machine IP and its occupancy monitor. Re-registering
`operations.occupancy.start_occupancy_check(ip, config)` for an
already-monitored IP SHALL replace the prior monitor (the new
`install_monitor` call cancels the prior); the replaced monitor SHALL be
cancelled before the new one is installed.

`repository.disconnect_all()` SHALL disconnect every currently
connected machine by invoking `disconnect(ip)` once per machine.

#### Scenario: Disconnect single machine

- **WHEN** `repository.disconnect("10.0.0.1")` is called on a connected machine
- **THEN** the SSH connection for `10.0.0.1` is closed, the machine is
  removed from the registry, and any monitor registered for
  `10.0.0.1` is cancelled and awaited

#### Scenario: Disconnect does not touch other machines' monitors

- **WHEN** machines A, B, and C are connected, each has an occupancy
  monitor installed via `operations.occupancy.start_occupancy_check`,
  and `repository.disconnect("B")` is called
- **THEN** only the monitor registered for B is cancelled, the monitors
  for A and C remain alive (not cancelled) and remain registered for
  their respective IPs, and machines A and C stay connected

#### Scenario: Disconnect unknown IP

- **WHEN** `repository.disconnect("10.0.0.99")` is called for an IP with
  no registered machine
- **THEN** no exception is raised, no monitor for any other IP is
  cancelled, and the registry of connected machines is unchanged

#### Scenario: Disconnect all

- **WHEN** `repository.disconnect_all()` is called
- **THEN** every connected machine's SSH connection is closed, every
  connected machine is removed from the registry, and every registered
  monitor is cancelled

#### Scenario: Re-registering occupancy for an IP replaces the prior monitor

- **WHEN** `operations.occupancy.start_occupancy_check(ip, config)` is
  called for an IP that already has a live occupancy monitor
- **THEN** the prior monitor is cancelled and the new monitor is
  installed under the same IP key, without affecting monitors registered
  for other IPs

### Requirement: Occupancy monitoring

The system SHALL periodically check if an engine process is still
running on a machine and update the machine state to FREE when the
process exits. The check logic (`occupancy_check`,
`_occupancy_by_pgrep`, `_occupancy_by_cmd`) lives in
`infra/ssh/operations/occupancy.py`; the monitor mechanism
(`install_monitor`/`cancel_monitor`) lives in
`infra/ssh/repository.py`.

The `OccupancyChecker.start_occupancy_check(ip, config)` SHALL
additionally call `repository.occupy(ip)` before installing the monitor
(so that `_meta_sync` sees BUSY while the task runs). The monitor's
`on_free` SHALL call `repository.release(ip)`.

#### Scenario: Process exits, machine becomes free

- **WHEN** occupancy check detects the engine process has exited
- **THEN** the `ConnectedMachine` state is updated to FREE with
  `free_since` set (via `repository.release(ip)` invoked as the
  monitor's `on_free`)

### Requirement: SSH connection retry

The system SHALL retry SSH connections on transient failures using
the `backoff` library with fibonacci backoff and `max_time=60`. The
repository SHALL use a two-method pattern for `connect()`: inner
`_connect_impl` with `@my_backoff_exc()` decorator (retries on
`SSHRetryExc`), outer `connect` translates exhausted
`(asyncssh.misc.Error, OSError)` exceptions to
`MachineConnectionError`.

#### Scenario: Retry on connection refused

- **WHEN** SSH connection fails with a retryable exception (in `SSHRetryExc`)
- **THEN** the connection is retried with fibonacci backoff up to 60 seconds

#### Scenario: Non-retryable error skips retry

- **WHEN** SSH connection fails with a non-retryable exception (e.g., `PermissionDenied`)
- **THEN** the error is NOT retried and immediately translated to `MachineConnectionError`

#### Scenario: Exhausted retry raises MachineConnectionError

- **WHEN** all retry attempts are exhausted
- **THEN** the outer `connect` method catches `(asyncssh.misc.Error, OSError)` and raises `MachineConnectionError` wrapping the last exception

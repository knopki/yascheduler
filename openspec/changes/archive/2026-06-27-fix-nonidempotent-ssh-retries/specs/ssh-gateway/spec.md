## MODIFIED Requirements

### Requirement: Backoff on gateway methods

The system SHALL apply `@my_backoff_exc()` (fibonacci, max_time=60,
SSHRetryExc) ONLY to idempotent gateway methods — namely
`get_cpu_cores` (a pure read of CPU core count). The system SHALL NOT
apply `@my_backoff_exc()` to `run_bg` and SHALL NOT apply
`@my_backoff_sftp()` to `upload` or `download`: these three operations
are non-idempotent (a successful remote side-effect followed by a lost
client confirmation would produce a duplicate side-effect on retry),
so a single attempt with failure-propagation is the correct contract.
The `MachineGateway` Protocol declaration of `run_bg`, `upload`, and
`download` is preserved; only the SSH implementation's retry
decorators are removed.

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

### Requirement: SSHMachineGateway implements MachineGateway

The system SHALL provide an `SSHMachineGateway` class that satisfies
the `MachineGateway` Protocol using asyncssh for SSH connections,
command execution, and SFTP. The gateway SHALL be self-contained — it
SHALL NOT import from `remote_machine/` or `clouds/`.

The gateway SHALL provide a `download_outputs` method that encapsulates
SFTP session management, per-file download with retry, error
classification, and remote directory cleanup. The method SHALL return
`tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]`
containing `(meta_add, transient_errors, permanent_errors)`. The method
SHALL catch all per-file exceptions (including non-retry) and classify
each into `transient_errors` (instances of `SFTPRetryExc`) or
`permanent_errors` (all other caught exceptions, including
`SFTPNoSuchFile`, `SFTPPermissionDenied`, and bare `OSError` from local
filesystem writes). The method SHALL catch all session-level exceptions
and return them in `transient_errors` (a session-level failure is
transient — the remote directory is preserved for retry). The method
SHALL NOT raise.

The method SHALL open a FRESH SFTP client (`get_sftp(ip)` context) per
file in the per-file loop, so that a dropped SFTP connection on one
file invalidates only that file's retries and does not fail-fast the
remaining files on a dead shared client. The per-file retry
(`file_get_retry`, fibonacci, max_time=60, `SFTPRetryExc`) SHALL wrap
each `sftp.get` call individually.

The method SHALL remove the remote directory tree only ONCE, after the
per-file loop completes, and only when BOTH `transient_errors` AND
`permanent_errors` are empty — i.e. on full success only. When either
list is non-empty, the method SHALL NOT remove the remote directory
tree (any undownloaded file, whether transient or permanent, must
remain available for the next retry cycle or for operator
debugging). The rmtree SHALL use its own separate `get_sftp(ip)`
context (not a per-file client).

The gateway SHALL provide a `_get_machine_state` method returning
`_MachineState | None` for adapter-internal use (e.g.,
`check_status.py`), and a `get_machine_state` method returning
`ConnectedMachine | None` for the port contract.

The gateway SHALL provide a `start_task_on_machine(machine, engine,
task, ncpus, engines_dir) -> bool` method that uploads task input
files via SFTP and spawns the calculation process via `run_bg`. The
method SHALL encapsulate all SSH-specific operations (`get_sftp`,
`get_path`, `get_quote`, `makedirs`, remote file writes) — no such
operations SHALL remain in the orchestrator. The gateway MAY use
private helpers (`_upload_task_data`, `_exec_spawn_command`,
`_write_remote_file`, `_safe_b64decode`) to structure the work.

The gateway SHALL provide `pgrep(ip, pattern, full=True) ->
AsyncGenerator[ProcessInfo, None]` and `list_processes(ip) ->
AsyncGenerator[ProcessInfo, None]` that delegate to the platform
adapter. `ProcessInfo` is the frozen dataclass from
`infra/ssh/platform/protocol.py` (re-exported via the package
`yascheduler.infra.ssh.platform`). The gateway SHALL NOT reference the
`PProcessInfo` Protocol.

#### Scenario: Connect to machine

- **WHEN** `gateway.connect(ip="10.0.0.1", username="root", client_keys=[...])` is called
- **THEN** an SSH connection is established, platform is detected, and a
  `ConnectedMachine` is registered internally

#### Scenario: Run command on connected machine

- **WHEN** `gateway.run(machine, "echo hello")` is called on a connected machine
- **THEN** returns a `ProcessResult` with the command output

#### Scenario: Upload file

- **WHEN** `gateway.upload(machine, local_path, "/remote/path")` is called
- **THEN** the file is transferred via SFTP to the remote path (single attempt, no retry)

#### Scenario: Download file

- **WHEN** `gateway.download(machine, "/remote/path", local_path)` is called
- **THEN** the file is transferred via SFTP to the local path (single attempt, no retry)

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `gateway.download_outputs(ip, remote_dir, local_dir, files, task_id)` is called
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

## ADDED Requirements

### Requirement: start_task_on_machine rolls back gateway BUSY on failure

The gateway's `start_task_on_machine(machine, engine, task, ncpus, engines_dir) -> bool` method SHALL roll back the gateway-level BUSY marking on any deploy or spawn failure. The method SHALL mark the machine BUSY at the gateway (via `update_machine(machine.occupy())`) before performing the deploy (upload) and spawn (`_exec_spawn_command` → `run_bg`) steps. If any exception (including `CancelledError` during daemon shutdown) escapes the deploy or spawn steps, the method SHALL roll back the gateway-level BUSY marking by calling `update_machine(state.machine.release())` on the machine registered for `machine.ip`, then re-raise the original exception. The rollback SHALL run under `except BaseException` so that `CancelledError` is covered.

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

This requirement governs the gateway-level occupancy marker only; the
DB task status and the orchestrator's in-memory `mark_running()` are
owned by the caller (`_try_start_on_machine` in
`allocate_task.py:114-144`) and are not affected by this rollback
(the task stays TO_DO in the DB on spawn failure, which is correct).

#### Scenario: Upload failure rolls back BUSY

- **WHEN** `start_task_on_machine` calls `update_machine(machine.occupy())`
  marking the machine BUSY, then `_upload_task_data` raises (e.g. an
  `asyncssh.misc.Error` from `sftp.makedirs` or a propagated
  non-SFTP exception from `_write_remote_file`)
- **THEN** the method's `except BaseException` handler calls
  `update_machine(state.machine.release())` on the machine registered
  for `machine.ip`, logging an info line, and re-raises the original
  exception
- **AND** the machine's gateway state is `FREE` after the call returns
  (via the raised exception), so the next allocator tick can pick it up

#### Scenario: Spawn failure rolls back BUSY

- **WHEN** `start_task_on_machine` marks the machine BUSY, the upload
  succeeds, then `_exec_spawn_command` → `run_bg` raises (e.g.
  `ChannelOpenError`, no longer retried per the amended Backoff
  requirement)
- **THEN** the method's `except BaseException` handler calls
  `update_machine(state.machine.release())`, logs an info line, and
  re-raises
- **AND** the machine's gateway state is `FREE` after the call, and no
  occupancy monitor was installed (it installs only after successful
  spawn)

#### Scenario: CancelledError during deploy rolls back BUSY

- **WHEN** `start_task_on_machine` marks the machine BUSY and the
  daemon is shut down mid-deploy (raising `CancelledError`) before
  spawn completes
- **THEN** the `except BaseException` handler catches the
  `CancelledError`, calls `update_machine(state.machine.release())`,
  logs an info line, and re-raises the `CancelledError`
- **AND** the machine's gateway state is `FREE` (not stuck BUSY with
  no owner)

#### Scenario: Concurrent disconnect skips rollback with warning

- **WHEN** `start_task_on_machine` marks the machine BUSY, then
  `disconnect(machine.ip)` runs concurrently and removes the machine
  from the registry, and then the deploy or spawn raises
- **THEN** the rollback handler sees `self._machines.get(machine.ip)`
  is `None`, logs a warning ("machine already disconnected"), and
  re-raises the original exception without attempting `release()`

#### Scenario: Unexpected non-BUSY state still releases and warns

- **WHEN** `start_task_on_machine`'s rollback handler runs and the
  machine registered for `machine.ip` has state other than `BUSY`
  (a logic error somewhere upstream)
- **THEN** the handler logs a warning ("unexpected state <state>,
  expected BUSY"), still calls `update_machine(state.machine.release())`
  to enforce the FREE-on-failure invariant, and re-raises
- **AND** the machine's gateway state is `FREE` after the call
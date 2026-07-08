## REMOVED Requirements

### Requirement: MachineOperations port

**Reason**: The `MachineOperations` Protocol was the type of the dissolved
`SSHMachineOperations` facade. With the facade gone, the Protocol has no
implementations and no consumers. The five facade pass-throughs
(`run`/`run_full`/`run_bg`/`get_cpu_cores`/`setup_node`) are now called
directly on `MachineSession` (every caller already holds a session). The
four use-case forwarders are now called on the corresponding concrete
collaborator (`TaskDeployer.start_task_on_machine`,
`OutputDownloader.download_outputs`,
`OccupancyChecker.occupancy_check`/`start_occupancy_check`).

**Migration**: Drop `MachineOperations` from `yascheduler/domain/ports.py`.
Update importers to take the specific concrete collaborator they need.
No runtime-checkable conformance is lost: the concrete classes work with
`isinstance` directly.

### Requirement: SSHMachineOperations composition

**Reason**: The `SSHMachineOperations` facade class is dissolved. Its only
role was to forward to three stateless collaborators
(`TaskDeployer`/`OutputDownloader`/`OccupancyChecker`) and to delegate
five session pass-throughs. The collaborators are now constructed
directly by `make_daemon` and taken as concrete ports by the orchestrator
and use cases; the pass-throughs are called on the session.

**Migration**: Delete `yascheduler/infra/ssh/operations/base.py`.
Re-export `TaskDeployer`, `OutputDownloader`, `OccupancyChecker` from
`yascheduler/infra/ssh/operations/__init__.py` and `yascheduler/infra`.

## MODIFIED Requirements

### Requirement: download_outputs per-file SFTP isolation and retry

The system SHALL provide `OutputDownloader.download_outputs(session,
remote_dir, local_dir, files, task_id)` returning
`(local_folder: str, remote_folder: str, transient_errors, permanent_errors)`.
The method SHALL catch all per-file exceptions and classify each into
`transient_errors` (instances of `SFTPRetryExc`) or `permanent_errors`
(all other caught exceptions). Session-level failures SHALL be caught and
returned in `transient_errors`. The method SHALL NOT raise.

The method SHALL open a FRESH SFTP client per file in the per-file loop,
so a dropped SFTP connection on one file invalidates only that file's
retries. The per-file retry (`file_get_retry`, fibonacci, max_time=60,
`SFTPRetryExc`) SHALL wrap each `sftp.get` call individually.

The method SHALL remove the remote directory tree only ONCE, after the
per-file loop completes, and only when BOTH error lists are empty. When
either list is non-empty, the remote directory SHALL NOT be removed.

The `local_folder`/`remote_folder` return values are `str(local_dir)` and
`remote_dir` verbatim. The previous `meta_add` return is REMOVED.

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `output_downloader.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each file is downloaded with per-file retry, per-file exceptions are classified into `transient_errors` and `permanent_errors`, and `(local_folder=str(local_dir), remote_folder=remote_dir, transient_errors, permanent_errors)` is returned

### Requirement: start_task_on_machine rolls back BUSY on failure

The `TaskDeployer.start_task_on_machine` method SHALL roll back the
session-level BUSY marking on any deploy or spawn failure. The method
SHALL mark the session BUSY at `session.occupy()` before performing the
deploy and spawn steps. If any exception (including `CancelledError`)
escapes, the method SHALL roll back by calling `session.release()`, then
re-raise the original exception. The rollback SHALL run under
`except BaseException`.

The rollback SHALL be defensive against concurrent state changes:

- If the session is closed (`session.is_closed` is `True`), log a warning and re-raise without rollback.
- If the session is open but not `BUSY`, log a warning, still call `session.release()`, and re-raise.
- Otherwise log an info line and re-raise.

This requirement governs the session-level occupancy marker only; the
DB task status and orchestrator's in-memory `mark_running()` are owned
by the caller and unaffected by this rollback.

#### Scenario: Upload failure rolls back BUSY

- **WHEN** `TaskDeployer.start_task_on_machine` calls `session.occupy()` marking the session BUSY, then the deploy step raises
- **THEN** the `except BaseException` handler calls `session.release()`, logs an info line, and re-raises the original exception
- **AND** the session's `machine.state` is `FREE` after the call returns

### Requirement: Occupancy monitoring

The system SHALL periodically check if an engine process is still
running on a machine and update the machine state to FREE when the
process exits. The check logic (`occupancy_check`,
`_occupancy_by_pgrep`, `_occupancy_by_cmd`) lives in
`infra/ssh/operations/occupancy.py` on the `OccupancyChecker` class; the
monitor mechanism (`install_monitor`/`cancel_monitor`) lives on
`SSHMachineSession` (in `infra/ssh/session.py`).

The `OccupancyChecker.start_occupancy_check(session, config)` SHALL
additionally call `session.occupy()` before installing the monitor
(so that `_meta_sync` sees BUSY while the task runs). The monitor's
`on_free` SHALL call `session.release()`.

#### Scenario: Process exits, machine becomes free

- **WHEN** occupancy check detects the engine process has exited
- **THEN** the `ConnectedMachine` state is updated to FREE with `free_since` set (via `session.release()` invoked as the monitor's `on_free`)

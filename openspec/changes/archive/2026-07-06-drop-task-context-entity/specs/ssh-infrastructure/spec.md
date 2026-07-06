# Spec Delta: ssh-infrastructure

## MODIFIED Requirements

### Requirement: `_write_remote_file` re-raises non-SFTP exceptions

The `_write_remote_file` helper SHALL re-raise non-SFTP exceptions.
The deploy module's `_write_remote_file(sftp, path, data, log, mode)`
helper (in `infra/ssh/operations/deployment.py`) SHALL re-raise any
exception that occurs during the SFTP file write. It SHALL NOT swallow
non-SFTP exceptions (e.g. `binascii.Error` from a malformed base64
`fort.9` payload, `TypeError` from a non-string `data`,
`UnicodeEncodeError` on a text-mode write, `KeyError` from a missing
`task.extra` key (was `task.context.extra`), transient non-SFTP asyncssh
errors, or `OSError`).

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

The `_upload_task_data` helper SHALL read input-file payloads from
`task.extra[input_file]` (was `task.context.extra[input_file]`); the
`extra` dict carries the input-file contents (file names as keys, file
contents as values) per the `domain-entities` delta. The
`start_task_on_machine` method SHALL read `task.remote_folder` (was
`task.context.remote_folder`) for the remote task directory path; the
assertion `assert task.remote_folder is not None` (was `assert
task.context.remote_folder is not None`) guards the read.

This requirement governs the module-private helper and the deploy path
only; no public surface (`MachineOperations`/`MachineRepository` Protocol,
CLI, INI, DB schema, AiiDA plugin) changes.

#### Scenario: Non-SFTP exception during write propagates and aborts spawn

- **WHEN** `_write_remote_file` is called and the write raises a non-SFTP exception (e.g. `binascii.Error` decoding a malformed `fort.9` base64 payload, or `TypeError` from `str(non_str)` `data`)
- **THEN** the exception propagates out of `_write_remote_file` without being swallowed, propagates through `_upload_task_data` (no `try/except` around the per-file loop), and is caught by `start_task_on_machine`'s DEPLOY block handler which logs `"Can't upload task_id=N files: <err>"` with the `task_id` and re-raises
- **AND** `_exec_spawn_command` is NOT called (the engine spawn command does not run, so no calculation proceeds with missing or garbage inputs)

#### Scenario: `asyncssh.misc.Error` is logged with structured code/reason and re-raised

- **WHEN** `_write_remote_file` is called and `sftp.open` or `f.write` raises an `asyncssh.misc.Error`
- **THEN** the helper logs `"Write <path> - SFTPError: <reason> (<code>)"` with the structured SFTP `code` and `reason` fields
- **AND** re-raises the same exception immediately
- **AND** the exception propagates through `_upload_task_data` and `start_task_on_machine` identically to the non-SFTP scenario above (abort, no spawn)

#### Scenario: Successful write returns normally

- **WHEN** `_write_remote_file` is called and the write completes without raising
- **THEN** the helper returns normally (no exception, no log line)
- **AND** `_upload_task_data` continues to the next input file in the loop

#### Scenario: _upload_task_data reads task.extra not task.context.extra
- **WHEN** `_upload_task_data` is inspected for input-file payload reads
- **THEN** it reads `task.extra[input_file]` (was `task.context.extra[input_file]`); no `task.context` reference

#### Scenario: start_task_on_machine reads task.remote_folder not task.context.remote_folder
- **WHEN** `start_task_on_machine` is inspected for the remote folder read
- **THEN** it reads `task.remote_folder` (was `task.context.remote_folder`); the assertion is `assert task.remote_folder is not None`; no `task.context` reference

### Requirement: download_outputs per-file SFTP isolation and retry

The system SHALL provide `SSHMachineOperations.download_outputs(session,
remote_dir, local_dir, files, task_id)` returning
`tuple[str, str, list[tuple[str | None, Exception]], list[tuple[str | None,
Exception]]]` containing `(local_folder, remote_folder, transient_errors,
permanent_errors)`. The method SHALL catch all per-file exceptions (including
non-retry) and classify each into `transient_errors` (instances of
`SFTPRetryExc`) or `permanent_errors` (all other caught exceptions, including
`SFTPNoSuchFile`, `SFTPPermissionDenied`, and bare `OSError` from local
filesystem writes). The method SHALL catch all session-level exceptions and
return them in `transient_errors` (a session-level failure is transient — the
remote directory is preserved for retry). The method SHALL NOT raise.

The method SHALL open a FRESH SFTP client (`session.open_sftp()` context)
per file in the per-file loop, so that a dropped SFTP connection on one
file invalidates only that file's retries and does not fail-fast the
remaining files on a dead shared client. The per-file retry
(`file_get_retry`, fibonacci, max_time=60, `SFTPRetryExc`) SHALL wrap
each `sftp.get` call individually.

The method SHALL remove the remote directory tree only ONCE, after the
per-file loop completes, and only when BOTH `transient_errors` AND
`permanent_errors` are empty — i.e. on full success only. When either
list is non-empty, the method SHALL NOT remove the remote directory tree
(any undownloaded file, whether transient or permanent, must remain
available for the next retry cycle or for operator debugging). The
rmtree SHALL use its own separate `session.open_sftp()` context (not a
per-file client).

`download_outputs` SHALL continue to use `my_backoff_sftp()` (defined
in `infra/ssh/operations/download.py`) as the per-file retry wrapper
inside the per-file loop.

The `local_folder`/`remote_folder` return values are the typed Task
fields the caller needs for `task.with_download_results(...)` (post-
`drop-task-context-entity` cleanup): `local_folder` is `str(local_dir)`
(the local directory received by the method); `remote_folder` is
`remote_dir` verbatim. The previous `meta_add: list[tuple[str, Any]]`
return (a metadata-blob-shaped list-of-pairs that survived only because
the caller re-built a `meta_dict` from it) is REMOVED; `consume_task`
receives the two paths as named values directly, no dict reconstruction.

#### Scenario: Download task outputs with per-file SFTP isolation and retry

- **WHEN** `operations.download_outputs(session, remote_dir, local_dir, files, task_id)` is called
- **THEN** a FRESH SFTP client is opened per file in the loop, each file is downloaded with per-file retry (`file_get_retry`, fibonacci, max_time=60, `SFTPRetryExc`), per-file exceptions are classified into `transient_errors` (instances of `SFTPRetryExc`) and `permanent_errors` (all other caught exceptions), and `(local_folder=str(local_dir), remote_folder=remote_dir, transient_errors, permanent_errors)` is returned

#### Scenario: Remote directory removed only on full success

- **WHEN** `download_outputs` completes the per-file loop with both `transient_errors` and `permanent_errors` empty (full success)
- **THEN** the remote directory tree is removed ONCE via `sftp.rmtree` using a separate `session.open_sftp()` context after the loop

#### Scenario: Remote directory preserved on any errors

- **WHEN** `download_outputs` completes the per-file loop with `transient_errors` non-empty OR `permanent_errors` non-empty
- **THEN** the remote directory tree is NOT removed (undownloaded files — whether transient or permanent — remain available for retry or operator debugging)

#### Scenario: Per-file SFTP isolation bounds dead-connection blast radius

- **WHEN** `download_outputs` is downloading files [f1, f2, f3] and the SFTP connection drops during f2's transfer
- **THEN** f2's per-file retry exhausts on the dead f2 client and classifies f2 as transient, but f3 is downloaded via a FRESH `session.open_sftp()` client and retries normally (not fail-fast on a dead shared client)

#### Scenario: Download outputs catches all exceptions

- **WHEN** `download_outputs` encounters a non-retryable per-file exception
- **THEN** the exception is caught and classified into `permanent_errors`, not raised

#### Scenario: Session-level failure is transient and preserves remote dir

- **WHEN** `download_outputs` encounters a session-level failure (e.g. `session.open_sftp()` itself raises before the per-file loop body executes)
- **THEN** the exception is caught by the single outer `try/except Exception`, recorded in `transient_errors`, the remote directory is NOT removed, and the method returns without raising

#### Scenario: download_outputs returns typed fields not meta_add list

- **WHEN** `download_outputs` returns and a caller inspects the return shape
- **THEN** it is a 4-tuple `(local_folder: str, remote_folder: str, transient_errors, permanent_errors)`; the legacy `meta_add: list[tuple[str, Any]]` first element is REMOVED; `local_folder == str(local_dir)` and `remote_folder == remote_dir`
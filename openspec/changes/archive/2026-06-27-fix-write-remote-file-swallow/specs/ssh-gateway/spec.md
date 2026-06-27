## ADDED Requirements

### Requirement: `_write_remote_file` re-raises non-SFTP exceptions

The gateway's `_write_remote_file(sftp, path, data, log, mode)` helper SHALL
re-raise any exception that occurs during the SFTP file write. It SHALL NOT
swallow non-SFTP exceptions (e.g. `binascii.Error` from a malformed base64
`fort.9` payload, `TypeError` from a non-string `data`, `UnicodeEncodeError`
on a text-mode write, `KeyError` from a missing `task.context.extra` key,
transient non-SFTP asyncssh errors, or `OSError`).

The helper MAY catch `asyncssh.misc.Error` specifically to log the structured
SFTP `code` and `reason` fields (which are absent from `str(err)` at upstream
catch sites) and SHALL re-raise it immediately after logging.

The propagation is the abort signal for `start_task_on_machine`: the
exception surfaces in `_upload_task_data` (which has no `try/except` around
the per-file loop) and then in `start_task_on_machine`'s DEPLOY block
`try/except Exception`, which logs `"Can't upload task_id=N files: <err>"`
(with `task_id`) and re-raises. The engine spawn command SHALL NOT execute
when an input file write has failed.

This requirement governs the module-private helper only; no public surface
(`MachineGateway` Protocol, CLI, INI, DB schema, AiiDA plugin) changes.

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
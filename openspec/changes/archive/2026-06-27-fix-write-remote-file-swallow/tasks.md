# Implementation Tasks: fix-write-remote-file-swallow

## 1. Source fix (variant B — delete the swallowing branch)

- [x] 1.1 In `yascheduler/infra/ssh/gateway.py`, delete the generic
  `except Exception as e:` branch (lines 142-144) inside `_write_remote_file`'s
  `START_BLOCK_WRITE_FILE` block. Keep the `asyncssh.misc.Error` branch
  (lines 134-141) byte-for-byte unchanged — it logs the structured
  `code`/`reason` and re-raises, which is correct and not a swallow.
- [x] 1.2 Bump the `VERSION` header in `yascheduler/infra/ssh/gateway.py` per
  the file's versioning convention; add a `START_CHANGE_SUMMARY` entry
  (LAST_CHANGE: fix-write-remote-file-swallow — remove generic
  `except Exception` swallow in `_write_remote_file`; non-SFTP upload
  failures now propagate and abort `start_task_on_machine` instead of
  silently launching spawn with missing/garbage inputs).
- [x] 1.3 Confirm no other source file needs editing — `_upload_task_data`
  (no `try/except` around the per-file loop) and `start_task_on_machine`'s
  DEPLOY block `try/except Exception` (line 629) already handle the
  now-propagated exceptions identically to the already-propagated
  `asyncssh.misc.Error`. No caller-side change.

## 2. Unit tests (`tests/unit/test_ssh_gateway.py` — covers `SSHMachineGateway`)

- [x] 2.1 Add a test asserting a non-SFTP exception raised inside
  `_write_remote_file` propagates out (not swallowed). Use a fake SFTP
  client whose `open(...).write(data)` raises a `ValueError` (or
  `binascii.Error` via a malformed base64 `fort.9` payload through
  `_safe_b64decode`) and assert the exception reaches the caller. Verify
  the `asyncssh.misc.Error`-branch log line is NOT emitted for this case
  (only the upstream handler logs).
- [x] 2.2 Add a test asserting an `asyncssh.misc.Error` raised inside
  `_write_remote_file` is logged with the structured `code` and `reason`
  fields (`"Write <path> - SFTPError: <reason> (<code>)"`) and re-raised
  (propagates to the caller). This locks D2 against a future accidental
  deletion of the structured-log branch.
- [x] 2.3 Add a test at the `start_task_on_machine` level: when
  `_upload_task_data` fails (e.g. one input file's write raises a non-SFTP
  exception), `_exec_spawn_command` is NOT called and the exception
  propagates to the orchestrator-side caller. Use a fake gateway/adapter
  or a mock that records `run_bg` calls and assert `run_bg` was never
  invoked. This is the end-to-end-behavior lock for the abort contract.
- [x] 2.4 Add a test asserting a successful write returns normally (no
  exception, no error log) and the per-file loop in `_upload_task_data`
  continues to the next file. This locks the success-path scenario from
  the spec.

## 3. Verification

- [x] 3.1 `uv run pytest -m unit` passes (new tests + existing
  `test_ssh_gateway.py` / `test_ssh_gateway_bg_tasks.py` green; no
  regression in the SFTP-error path tests).
- [x] 3.2 `uv run zuban check`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run lint-imports` all pass.
- [x] 3.3 `python3 scripts/grace_check.py` exits 0 (graph + source markup
  consistent; confirm no graph update was needed — private-only change).
- [x] 3.4 `openspec validate fix-write-remote-file-swallow` passes (the
  delta spec `specs/ssh-gateway/spec.md` validates; ADDED requirement with
  3 scenarios in the correct `#### Scenario` format).

> NOTE on 3.3: `grace_check.py` reports a **pre-existing**
> `module-size-hard` error on `gateway.py` (1020 lines vs 1000 hard limit;
> same error is present at HEAD before this change — verified via
> `git stash`). This change reduces the file by 2 lines (deletion of the
> swallow branch) and adds a 3-line CHANGE_SUMMARY entry per the GRACE-lite
> rule; it does not introduce the size violation and addressing it is out of
> scope for this surgical bug fix. No knowledge-graph update was needed
> (private-only change per design D3).
## 1. GRACE-lite Artifacts (top-down)

- [x] 1.1 Update `docs/knowledge-graph.xml` — add `MachineConnectionError` to M-DOMAIN-EXCEPTIONS annotations, add `OccupancyConfig` to M-DOMAIN-PORTS annotations, update M-SSH-GATEWAY annotations (rename `get_machine_state`→`_get_machine_state`, add `download_outputs`, `list_connected`)
- [x] 1.2 Update MODULE_CONTRACT in `domain/ports.py` — add `OccupancyConfig` to MODULE_MAP
- [x] 1.3 Update MODULE_CONTRACT in `domain/exceptions.py` — add `MachineConnectionError` to MODULE_MAP

## 2. Domain Layer — Exceptions

- [x] 2.1 Add `MachineConnectionError(DomainError)` to `domain/exceptions.py` with `ip: str` and `reason: str` attributes
- [x] 2.2 Export `MachineConnectionError` from `domain/__init__.py`

## 3. Domain Layer — Ports

- [x] 3.1 Add `OccupancyConfig` Protocol to `domain/ports.py` with attributes: `name`, `check_pname`, `check_cmd`, `check_cmd_code`, `sleep_interval`
- [x] 3.2 Extend `MachineGateway` Protocol with connection lifecycle methods: `connect`, `disconnect`, `disconnect_all`
- [x] 3.3 Extend `MachineGateway` Protocol with machine query methods: `list_connected`, `contains`, `get_machine_state`, `update_machine`, `__len__`
- [x] 3.4 Extend `MachineGateway` Protocol with command execution methods: `run_bg` (return `None`)
- [x] 3.5 Extend `MachineGateway` Protocol with file transfer method: `download_outputs` with signature `(ip, remote_dir, local_dir, files, task_id=None) -> tuple[list, list]`
- [x] 3.6 Extend `MachineGateway` Protocol with occupancy method: `start_occupancy_check(ip, config: OccupancyConfig)`
- [x] 3.7 Extend `MachineGateway` Protocol with remote info method: `get_cpu_cores`
- [x] 3.8 Export `OccupancyConfig` from `domain/__init__.py`
- [x] 3.9 Update MODULE_MAP in `domain/ports.py`

## 4. Adapter Layer — SSH Gateway

- [x] 4.1 Add `my_backoff_sftp` partial in `gateway.py` (fibonacci, max_time=60, SFTPRetryExc)
- [x] 4.2 Add `@my_backoff_exc()` to `run_bg` method
- [x] 4.3 Add `@my_backoff_sftp()` to `upload` method
- [x] 4.4 Add `@my_backoff_sftp()` to `download` method
- [x] 4.5 Add `@my_backoff_exc()` to `get_cpu_cores` method
- [x] 4.6 Split `connect` into `_connect_impl` (with `@my_backoff_exc()`) and outer `connect` (translates `(asyncssh.misc.Error, OSError)` to `MachineConnectionError`)
- [x] 4.7 Rename `get_machine_state` to `_get_machine_state` (adapter-internal), add new `get_machine_state` returning `ConnectedMachine | None`
- [x] 4.8 Add `list_connected() -> list[ConnectedMachine]` method
- [x] 4.9 Add `download_outputs` method — SFTP session + per-file retry + remote cleanup
- [x] 4.10 Add catch-all exception handling to `download_outputs` — return errors in `sftp_errors` list
- [x] 4.11 Add optional `task_id` parameter to `download_outputs` for log correlation
- [x] 4.12 Update `check_status.py` to use `_get_machine_state` instead of `get_machine_state`

## 5. Application Layer — consume_task

- [x] 5.1 Remove runtime imports: `SFTPRetryExc`, `SFTPError`, `backoff` from `consume_task.py`
- [x] 5.2 Remove `_sftp_download_job` and `_download_task_outputs` functions, replace with `gateway.download_outputs()` call in `consume_task` — receives `(meta_add, sftp_errors)` tuple
- [x] 5.3 Change type annotation from `SSHMachineGateway` to `MachineGateway` Protocol

## 6. Application Layer — allocate_task

- [x] 6.1 Change type annotation from `SSHMachineGateway` to `MachineGateway` Protocol in `allocate_task.py`

## 7. Application Layer — deallocate_nodes

- [x] 7.1 Change type annotation from `SSHMachineGateway` to `MachineGateway` Protocol in `deallocate_nodes.py`
- [x] 7.2 Replace `gateway.keys()` with `gateway.contains(node.ip)` in `deallocate_node`

## 8. Application Layer — orchestrator

- [x] 8.1 Remove runtime imports: `AllSSHRetryExc`, `backoff` from `orchestrator.py` (keep `asyncssh` for deferred helpers)
- [x] 8.2 Remove `@backoff.on_exception` decorator from `_allocator_consumer`
- [x] 8.3 Replace `except asyncssh.misc.Error` with `except MachineConnectionError` in `_connect_machine_consumer`
- [x] 8.4 Replace `gateway.items()` with `gateway.list_connected()` in `_print_stats` — update iteration to use `machine.state` directly
- [x] 8.5 Replace `gateway.items()` with `gateway.list_connected()` in `_deallocator_producer` — update iteration to use `machine.ip` directly
- [x] 8.6 Update `get_machine_state` call sites: remove `state.machine` access, use returned `ConnectedMachine` directly (orchestrator.py:445,470,476,478)
- [x] 8.7 Keep `self._gateway` typed as concrete `SSHMachineGateway` for deferred helpers (D10)

## 9. Tests

- [x] 9.1 Update unit tests for `consume_task` — mock `gateway.download_outputs()` instead of SFTP internals
- [x] 9.2 Update unit tests for `orchestrator` — mock `MachineGateway` Protocol instead of `SSHMachineGateway`
- [x] 9.3 Add unit test for `MachineConnectionError` — verify attributes and inheritance
- [x] 9.4 Add unit test for `download_outputs` — verify catch-all behavior and return type
- [x] 9.5 Add unit test for `connect` two-method pattern — verify retry then translate
- [x] 9.6 Add import hygiene test — verify no adapter runtime imports (`AllSSHRetryExc`, `SFTPRetryExc`, `SFTPError`, `backoff`) in application layer modules

## 10. GRACE-lite Finalization

- [x] 10.1 Update CHANGE_SUMMARY in all modified files
- [x] 10.2 Add `START_CONTRACT:` blocks for new public methods (`download_outputs`, `list_connected`, `OccupancyConfig`)
- [x] 10.3 Run `python3 scripts/grace_check.py` and fix any issues

## 11. Deferred Helpers Migration (scope expansion after D10 revision)

- [x] 11.1 Add `TaskExecutionEngine` Protocol to `domain/ports.py` (extends `OccupancyConfig` with `spawn: str` and `input_files: tuple[str, ...]`)
- [x] 11.2 Export `TaskExecutionEngine` from `domain/__init__.py`
- [x] 11.3 Add `start_task_on_machine(machine, engine, task, ncpus, engines_dir) -> bool` to `MachineGateway` Protocol
- [x] 11.4 Move `_start_task_on_machine`, `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`, `_safe_b64decode` from `orchestrator.py` to `gateway.py` as methods on `SSHMachineGateway` (private helpers) + public `start_task_on_machine`
- [x] 11.5 Update orchestrator's `_start_task_on_machine` to be a thin wrapper: resolve ncpus via UoW (fallback `gateway.get_cpu_cores`), then call `gateway.start_task_on_machine(machine, engine, task, ncpus, engines_dir)`
- [x] 11.6 Type `self._gateway` as `MachineGateway` (Protocol) in orchestrator; remove `# type: ignore[arg-type]` from call sites
- [x] 11.7 Remove `asyncssh`, `base64`, `PurePosixPath` runtime imports from orchestrator (now only in gateway); orchestrator has zero adapter-specific imports
- [x] 11.8 Update `allocate_task` callback type to use `TaskExecutionEngine` instead of `Engine`
- [x] 11.9 Knowledge graph updated: M-SSH-GATEWAY gets `fn-start_task_on_machine`, M-DOMAIN-PORTS gets `class-TaskExecutionEngine`, M-DOMAIN gets `export-TaskExecutionEngine`, CrossLink orchestrator→ports added
- [x] 11.10 Run unit (364), integration (66), e2e (1) tests + zuban, ruff, lint-imports, grace, openspec validate — all pass

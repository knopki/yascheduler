## Why

Application layer imports adapter-specific types (`AllSSHRetryExc`, `SFTPRetryExc`, `asyncssh`) at runtime and manages SSH retry/backoff itself, violating hexagonal architecture dependency rules. The `MachineGateway` Protocol defines only 4 methods while application uses ~15 methods directly on the concrete `SSHMachineGateway` class, bypassing the port entirely.

## What Changes

- **Extend `MachineGateway` Protocol** with methods application actually uses: `connect`, `disconnect`, `disconnect_all`, `list_connected`, `contains`, `run_bg`, `download_outputs`, `get_machine_state`, `update_machine`, `start_occupancy_check`, `get_cpu_cores`
- **Add `MachineConnectionError`** to domain exceptions — gateway wraps `asyncssh.misc.Error` into this domain exception
- **Move backoff into adapter** — `@backoff.on_exception` decorators move from `orchestrator.py` and `consume_task.py` into `SSHMachineGateway` methods
- **Add `download_outputs` method** to gateway — encapsulates SFTP session management, per-file retry, and remote directory cleanup that currently lives in `consume_task.py`
- **Remove adapter imports from application** — `orchestrator.py`: remove `AllSSHRetryExc` (runtime); `consume_task.py`: remove `SFTPRetryExc`, `SFTPError`, `backoff` (runtime). Note: `asyncssh` remains in `orchestrator.py` for deferred `_write_remote_file`/`_upload_task_data` — will be removed when those move to adapter.
- **Replace concrete types with Protocol** — `SSHMachineGateway` type annotations replaced with `MachineGateway` Protocol in application layer

## Considered Alternatives

- **A. Minimal (backoff only)**: Move `@backoff` into adapter, keep port as-is. Rejected — port leakage remains; application still calls `get_sftp()`, `get_path()`, etc. not in Protocol. Backoff is a symptom, not the root cause.
- **C. Split into two Protocols**: `MachineGateway` (connection/lifecycle) + `TaskIOService` (upload/download). Rejected — both implemented by same `SSHMachineGateway` class; artificial split with no second consumer. YAGNI.

## Decisions

- **Backoff parameters**: hardcoded `backoff.fibo, max_time=60` in adapter. Not configurable via `ConfigLocal`.
- **`download_outputs` return type**: `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]` — returns `(meta_add, sftp_errors)` matching current `_download_task_outputs` signature. `meta_add` needed by `_finalize_task` for `task.context` updates. Method catches all exceptions internally.
- **`list_connected()`**: replaces `items()` in port. Returns `list[ConnectedMachine]`.

## Out of Scope (Deferred)

- `_start_task_on_machine`, `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`, `_safe_b64decode` — stay in orchestrator as callback. Isolated behind callback parameter, not a direct port violation.
- `setup_node` — not used by application layer, no port exposure needed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `domain-ports`: MachineGateway Protocol extended with connection lifecycle, occupancy, and I/O methods
- `domain-exceptions`: new `MachineConnectionError(DomainError)` for connection failures
- `ssh-gateway`: backoff decorators added to methods, `download_outputs` method added, `connect` wraps asyncssh errors into `MachineConnectionError`
- `orchestrator`: adapter imports removed, backoff removed from `_allocator_consumer`, `asyncssh.misc.Error` replaced with `MachineConnectionError`, `items()` replaced with `list_connected()`
- `use-cases`: `consume_task` delegates SFTP retry to `gateway.download_outputs()`, adapter imports removed

## Impact

- **Code**: `domain/ports.py`, `domain/exceptions.py`, `adapters/ssh/gateway.py`, `application/orchestrator.py`, `application/consume_task.py`, `application/allocate_task.py`, `application/deallocate_nodes.py`
- **APIs**: `MachineGateway` Protocol gains ~11 new methods (additive, non-breaking for existing implementations)
- **Dependencies**: `backoff` library usage moves from application to adapter layer (no dependency changes in pyproject.toml)
- **Tests**: unit tests for orchestrator and consume_task will need updated mocks (Protocol instead of concrete class)

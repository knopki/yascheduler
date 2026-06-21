## Context

The `MachineGateway` Protocol in `domain/ports.py` defines 4 methods (`list_free`, `run`, `upload`, `download`). The concrete `SSHMachineGateway` has 40+ methods. Application layer bypasses the Protocol and uses the concrete class directly, importing adapter-specific types (`AllSSHRetryExc`, `SFTPRetryExc`, `asyncssh`) at runtime.

Current backoff state in `SSHMachineGateway`:
- `connect()` — already has `@my_backoff_exc()` ✅
- `run_full()` — already has `@my_backoff_exc()` (called by `run()`) ✅
- `run_bg()` — no backoff ❌
- `upload()` — no backoff ❌
- `download()` — no backoff ❌
- `get_cpu_cores()` — no backoff ❌

Application layer backoff (to remove):
- `orchestrator._allocator_consumer` — `@backoff.on_exception(fibo, AllSSHRetryExc, max_time=60)` wrapping entire `allocate_task` call (includes DB ops — wrong scope)
- `consume_task._sftp_download_job` — `backoff.on_exception(fibo, SFTPRetryExc, max_time=60)` per-file
- `consume_task._download_task_outputs` — `backoff.on_exception(fibo, SFTPRetryExc, max_time=60)` wrapping entire SFTP job

## Goals / Non-Goals

**Goals:**
- Application layer has zero runtime imports from `yascheduler.adapters` (exception: `asyncssh` remains for deferred helpers — see Non-Goals)
- Application layer depends only on `MachineGateway` Protocol (not `SSHMachineGateway`) for all non-deferred code paths
- All retry/backoff logic lives inside the adapter
- `MachineGateway` Protocol covers all methods application actually calls (except deferred helpers — see D10)
- `connect()` failures surface as domain `MachineConnectionError`

**Non-Goals:**
- Moving `_start_task_on_machine` / `_upload_task_data` / `_exec_spawn_command` into adapter (deferred — isolated behind callback)
- Changing backoff strategy or parameters (keep `fibo, max_time=60`)
- Adding new retry capabilities to methods that don't need them
- Modifying `CloudProvisioner` port or cloud adapter backoff

## Decisions

### D1: `get_machine_state` returns `ConnectedMachine | None`

**Current**: returns `_MachineState | None` (adapter-internal dataclass with `conn`, `conn_opts`, `adapter`, `platforms`, paths).

**Decision**: port method returns `ConnectedMachine | None`. Concrete `SSHMachineGateway` keeps internal `_get_machine_state() -> _MachineState | None` for adapter-internal use (e.g., `check_status.py`). Port method `get_machine_state()` returns `ConnectedMachine | None` for application layer.

**Refactoring sites in orchestrator**:
- `orchestrator.py:445`: `state = self._gateway.get_machine_state(ip)` → `machine = self._gateway.get_machine_state(ip)`
- `orchestrator.py:470`: `machine = state.machine` → removed (already `ConnectedMachine`)
- `orchestrator.py:476`: `state = self._gateway.get_machine_state(ip)` → `machine = self._gateway.get_machine_state(ip)`
- `orchestrator.py:478`: `machine = state.machine` → removed

**Rationale**: `_MachineState` contains `SSHClientConnection`, `RemoteMachineAdapter` — adapter types that must not leak into the port. Returning `ConnectedMachine` (domain entity) keeps the port clean. Adapter-internal consumers (like `check_status.py`) use the private `_get_machine_state()` method.

### D2: `download_outputs` encapsulates full SFTP job

**Signature**:
```python
async def download_outputs(
    self,
    ip: str,
    remote_dir: str,
    local_dir: Path,
    files: list[str],
    task_id: int | None = None,
) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]:
```

**Returns**: `(meta_add, sftp_errors)` where:
- `meta_add`: `[("remote_folder", remote_dir), ("local_folder", str(local_dir))]` — metadata for `task.context`
- `sftp_errors`: list of `(file_path, exception)` tuples, empty on success

**Responsibilities**: open SFTP session → per-file download with retry → remove remote dir → return metadata and errors. Catches all exceptions (including non-retry) and returns them in `sftp_errors` list, guaranteeing the caller always gets a result rather than an exception.

**Logging**: `task_id` parameter is optional, used for log correlation (`"Cannot download file for task_id=%s ..."`). Preserves operational traceability from current `_sftp_download_job`.

**Rationale**: moves `_sftp_download_job` + `_download_task_outputs` logic from `consume_task.py` into adapter. The two-level backoff (per-file + whole-job) stays inside the adapter method. Return type matches current `_download_task_outputs` signature — `meta_add` is needed by `_finalize_task` to populate `task.context.local_folder/remote_folder/extra`.

### D3: `connect()` wraps asyncssh errors into `MachineConnectionError`

**Problem**: `connect()` already has `@my_backoff_exc()` decorator. Adding `try/except asyncssh.misc.Error` inside the method would catch exceptions before backoff can retry them.

**Solution**: split into two methods — inner method with backoff, outer method with exception translation:

```python
# In SSHMachineGateway:
async def connect(self, ip, username, ...) -> ConnectedMachine:
    """Public API — translates transport errors into domain exceptions."""
    try:
        return await self._connect_impl(ip, username, ...)
    except (asyncssh.misc.Error, OSError) as err:
        raise MachineConnectionError(ip, str(err)) from err

@my_backoff_exc()
async def _connect_impl(self, ip, username, ...) -> ConnectedMachine:
    """Inner implementation with retry — exceptions propagate to backoff decorator."""
    conn, conn_opts = await self._open_connection(...)
    adapter, platforms = await _detect_platform(conn, ADAPTERS)
    ...
    return machine
```

**Exception coverage**: outer `except` catches `(asyncssh.misc.Error, OSError)`:
- `asyncssh.misc.Error` — all asyncssh exceptions (including non-retryable like `PermissionDenied`, `DisconnectError`)
- `OSError` — network-level failures (also in `SSHRetryExc`, caught here after backoff exhaustion)

This ensures ALL connection failures surface as `MachineConnectionError`, not just retryable ones. Non-retryable errors (auth failures, disconnects) skip backoff (correct) but still get translated (correct).

**Rationale**: backoff decorator must see the raw `SSHRetryExc` to retry. Only after backoff exhausts retries does the exception propagate to the outer method, which translates it into `MachineConnectionError`. This preserves retry behavior while providing a clean domain exception to callers.

### D4: Backoff on `run_bg`, `upload`, `download`, `get_cpu_cores`

Add `@my_backoff_exc()` to these methods. `my_backoff_exc` already exists in gateway as `partial(backoff.on_exception, wait_gen=backoff.fibo, max_time=60, exception=SSHRetryExc)`.

For SFTP methods (`upload`, `download`), use `SFTPRetryExc` variant:
```python
my_backoff_sftp = partial(
    backoff.on_exception,
    wait_gen=backoff.fibo,
    max_time=60,
    exception=SFTPRetryExc,
)
```

**`run_bg` port return type**: `None`. Current concrete `run_bg` returns `SSHClientProcess` (adapter type — leaks into port). Orchestrator discards the return value (`orchestrator.py:250`). Port method returns `None`; concrete method keeps returning `SSHClientProcess` for internal use but port contract is `-> None`.

### D5: `list_connected()` replaces `items()` in port

```python
# Protocol
def list_connected(self) -> list[ConnectedMachine]: ...

# SSHMachineGateway
def list_connected(self) -> list[ConnectedMachine]:
    return [s.machine for s in self._machines.values()]
```

**Refactoring sites in orchestrator**:
- `orchestrator.py:323-327` (`_print_stats`): `for s in self._gateway.items(): if s[1].machine.state == MachineState.BUSY` → `for m in self._gateway.list_connected(): if m.state == MachineState.BUSY`
- `orchestrator.py:513-517` (`_deallocator_producer`): `for ip, state in self._gateway.items(): m = state.machine` → `for m in self._gateway.list_connected(): ip = m.ip`

**Rationale**: `items()` returns `ItemsView[str, _MachineState]` — adapter internals. Orchestrator only needs `ConnectedMachine` objects. `list_connected()` is the port-safe equivalent.

### D6: `contains()` added to port

```python
# Protocol
def contains(self, ip: str) -> bool: ...
```

Already exists in `SSHMachineGateway`. Just needs to be in Protocol.

**Note**: `contains()` and `list_connected()` are synchronous methods in the Protocol. This matches the current implementation — they access in-memory state (`self._machines` dict), not remote resources. No async needed.

### D6b: `disconnect` / `disconnect_all` added to port

```python
# Protocol
async def disconnect(self, ip: str) -> None: ...
async def disconnect_all(self) -> None: ...
```

Already exist in `SSHMachineGateway`. Just need to be in Protocol.

**Call sites**: `orchestrator.py:544` (`_deallocator_consumer` calls `disconnect`), `orchestrator.py:546` (fallback `disconnect`), `orchestrator.py:711` (`stop` calls `disconnect_all`).

### D7: `start_occupancy_check` uses `OccupancyConfig` Protocol in domain

`start_occupancy_check(ip, engine)` currently takes `PEngine` — a Protocol defined in `adapters/ssh/platform/protocol.py`. Adding this to `domain/ports.py` would create a domain→adapter import, which is the exact violation this change fixes.

**Problem**: `domain.Engine` does NOT satisfy `PEngine` — it lacks `check_cmd_code`, `sleep_interval`, `deployable`. Only `config.Engine` satisfies `PEngine`, but domain cannot import from config.

**Decision**: create `OccupancyConfig` Protocol in `domain/ports.py` with the minimal contract needed by `start_occupancy_check`:

```python
@runtime_checkable
class OccupancyConfig(Protocol):
    """Minimal contract for occupancy check configuration."""
    name: str
    check_pname: str | None
    check_cmd: str | None
    check_cmd_code: int
    sleep_interval: int
```

`config.Engine` satisfies `OccupancyConfig` structurally. The port method signature becomes:
```python
def start_occupancy_check(self, ip: str, config: OccupancyConfig) -> None: ...
```

**Rationale**: domain layer must not import from adapters or config. `OccupancyConfig` is the minimal structural contract for occupancy monitoring — it captures exactly what the gateway needs without pulling in deployment or platform details. The adapter implementation can continue using `PEngine` internally (which is a superset of `OccupancyConfig`).

### D8: `update_machine` added to port

```python
# Protocol
def update_machine(self, machine: ConnectedMachine) -> None: ...
```

Already exists in `SSHMachineGateway`. Just needs to be in Protocol.

**Rationale**: orchestrator calls `update_machine()` to apply `occupy()`/`release()` transitions. This is a state mutation on the gateway's internal registry — belongs in the port contract.

### D9: `__len__` added to port

```python
# Protocol
def __len__(self) -> int: ...
```

Already exists in `SSHMachineGateway`. Just needs to be in Protocol.

**Rationale**: `orchestrator.py:607` (`_await_first_machine`) calls `len(self._gateway)`. After re-typing `_gateway` as `MachineGateway`, this requires `__len__` in the Protocol.

### D10: Deferred helpers move into the gateway

**Problem**: deferred `_start_task_on_machine`, `_upload_task_data`, `_exec_spawn_command` call non-Protocol methods (`get_quote`, `get_sftp`, `get_hostname`, `get_path`, `run_bg`). Keeping these helpers in the orchestrator forces `self._gateway` to be typed as the concrete `SSHMachineGateway`, defeating the purpose of the `MachineGateway` Protocol.

**Decision**: move the deferred helpers into `SSHMachineGateway` as a single public port method `start_task_on_machine(machine, engine, task, ncpus) -> bool` plus private helpers `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`, `_safe_b64decode`. The orchestrator is left with a thin wrapper that only does the UoW lookup for `ncpus` and delegates to `self._gateway.start_task_on_machine(...)`. The orchestrator's `self._gateway` is now typed as `MachineGateway` (Protocol).

```python
# In Orchestrator.__init__:
self._gateway: MachineGateway  # Protocol type — no concrete adapter reference

# In allocate_task call:
await allocate_task(
    ...
    start_task_on_machine=self._start_task_on_machine,  # thin wrapper
)

# Thin wrapper in Orchestrator (uses only Protocol ops):
async def _start_task_on_machine(self, machine, engine, task) -> bool:
    async with self._uow_factory() as uow:
        node = await uow.nodes.get(task.allocated_ip or "")
    ncpus = (node and node.ncpus) or await self._gateway.get_cpu_cores(machine.ip)
    return await self._gateway.start_task_on_machine(machine, engine, task, ncpus, self._config.remote.engines_dir)
```

**Rationale**: the Protocol now genuinely covers every operation the application layer performs. SSH-specific bits (`get_sftp`, `get_path`, `get_quote`, `run_full`, `makedirs`, SFTP file writes) live entirely inside the adapter. The thin orchestrator wrapper only uses `uow_factory` (application concern) and two Protocol methods (`get_cpu_cores`, `start_task_on_machine`).

**New Protocol surface**: a `TaskExecutionEngine` Protocol is added to `domain/ports.py` — a superset of `OccupancyConfig` capturing the engine fields needed for task deployment (`spawn`, `input_files`, plus OccupancyConfig fields). `config.Engine` structurally satisfies it; no migration needed for callers passing `Engine` instances.

## Risks / Trade-offs

**[Risk] `download_outputs` moves business logic into adapter** → The SFTP download + cleanup is infrastructure concern (retry, session management, remote filesystem). The business logic (which files to download, where to store) stays in `consume_task` which prepares the parameters. Acceptable split.

**[Risk] Port grows to ~15 methods** → All methods are actively used by application layer. This is not speculative — it's documenting what already exists. A smaller port would require deferring more work (which we're already doing with `_start_task_on_machine`).

**[Risk] `_MachineState` no longer accessible from orchestrator** → Orchestrator only used `state.machine` (ConnectedMachine). If future needs require adapter internals, they should go through gateway methods, not direct state access. This is the intended constraint.

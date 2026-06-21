# Explore Brief: gateway-port-cleanup

## Problem

Application layer imports adapter-specific types at runtime and manages SSH retry/backoff itself, violating hexagonal architecture dependency rules.

**Concrete violations:**
- `orchestrator.py`: `from yascheduler.adapters import AllSSHRetryExc` (runtime), `import asyncssh` (runtime), `@backoff.on_exception(backoff.fibo, AllSSHRetryExc, max_time=60)`
- `consume_task.py`: `from yascheduler.adapters import SFTPRetryExc` (runtime), `from asyncssh.sftp import SFTPError` (runtime), two `backoff.on_exception(SFTPRetryExc)` decorators
- `orchestrator.py` uses ~15 methods on `SSHMachineGateway` that are not in the `MachineGateway` Protocol: `get_sftp()`, `get_path()`, `get_quote()`, `get_hostname()`, `get_cpu_cores()`, `get_machine_state()`, `start_occupancy_check()`, `update_machine()`, `items()`, `contains()`, `connect()`, `disconnect()`, `disconnect_all()`, `run_bg()`, `setup_node()`

## Rejected Alternatives

### A. Minimal — move backoff into adapter only
Move `@backoff` decorators into `SSHMachineGateway` methods. Remove retry exception imports from application.

**Rejected because:** port leakage remains. Application still calls `gateway.get_sftp()`, `gateway.get_path()`, etc. — methods not in the `MachineGateway` Protocol. The backoff issue is a symptom of the deeper port bypass.

### C. Split port into two Protocols
Create `MachineGateway` (connection/lifecycle) and `TaskIOService` (upload_task_inputs, download_task_outputs) as separate Protocols.

**Rejected because:** both Protocols would be implemented by the same `SSHMachineGateway` class. The split is artificial when there's one underlying SSH connection. YAGNI — no second consumer that needs only one of the two. Adds DI wiring complexity for no practical gain.

## Chosen Approach: B — Extend MachineGateway Protocol + encapsulate backoff

### What changes

**MachineGateway Protocol** (`domain/ports.py`) — extend with methods application actually uses:

| Method | Purpose | Backoff? |
|---|---|---|
| `connect(ip, username, ...)` | Open SSH connection | Yes (SSHRetryExc) |
| `disconnect(ip)` | Close SSH connection | No |
| `disconnect_all()` | Close all connections | No |
| `list_free(platforms)` | Return FREE machines | No |
| `list_connected()` | All connected machines with state | No |
| `contains(ip)` | Check if machine is connected | No |
| `run(machine, cmd)` | Run command, return ProcessResult | Yes (SSHRetryExc) |
| `run_bg(machine, cmd, cwd)` | Start background process | Yes (SSHRetryExc) |
| `upload(machine, local, remote)` | Upload single file | Yes (SFTPRetryExc) |
| `download(machine, remote, local)` | Download single file | Yes (SFTPRetryExc) |
| `download_outputs(ip, remote_dir, local_dir, files)` | Download multiple files with retry, clean remote dir, return errors | Yes (SFTPRetryExc) |
| `get_machine_state(ip)` | Return machine state (FREE/BUSY) | No |
| `update_machine(machine)` | Replace machine in state | No |
| `start_occupancy_check(ip, engine)` | Start background occupancy monitor | No |
| `get_cpu_cores(ip)` | Read remote CPU count | Yes (SSHRetryExc) |

**Backoff moves into adapter:**
- `SSHMachineGateway.run()` — `@backoff.on_exception(fibo, SSHRetryExc, max_time=60)`
- `SSHMachineGateway.run_bg()` — same
- `SSHMachineGateway.upload()` — `@backoff.on_exception(fibo, SFTPRetryExc, max_time=60)`
- `SSHMachineGateway.download()` — same
- `SSHMachineGateway.download_outputs()` — wraps SFTP session + per-file retry + remote cleanup
- `SSHMachineGateway.connect()` — `@backoff.on_exception(fibo, SSHRetryExc, max_time=60)`
- `SSHMachineGateway.get_cpu_cores()` — `@backoff.on_exception(fibo, SSHRetryExc, max_time=60)`

**Application layer cleanup:**
- `orchestrator.py`: remove `from yascheduler.adapters import AllSSHRetryExc`, remove `import asyncssh`, remove `@backoff.on_exception` from `_allocator_consumer`, use `gateway.download_outputs()` instead of manual SFTP
- `consume_task.py`: remove `from yascheduler.adapters import SFTPRetryExc`, remove `from asyncssh.sftp import SFTPError`, remove both `backoff.on_exception` decorators, call `gateway.download_outputs()`
- All type annotations: `SSHMachineGateway` → `MachineGateway` (Protocol)

### Key cross-module data flows

**Allocate flow (after):**
```
Orchestrator._allocator_consumer(msg)
  → allocate_task(gateway: MachineGateway, ...)
    → _find_free_machines(gateway.list_free)
    → _try_start_on_machine(machine, engine, task, gateway, ...)
      → start_task_on_machine callback (stays in orchestrator — deferred)
      → gateway.start_occupancy_check(ip, engine)
```

**Consume flow (after):**
```
Orchestrator._task_consumer_consumer(msg)
  → gateway.get_machine_state(ip)
  → gateway.start_occupancy_check(ip, engine)
  → consume_task(gateway: MachineGateway, ...)
    → gateway.download_outputs(ip, remote_dir, local_dir, files)
      [backoff + SFTP session + per-file retry + remote cleanup — all inside adapter]
    → _finalize_task(...)
```

**Connect flow (after):**
```
Orchestrator._connect_machine_consumer(msg)
  → gateway.connect(ip, username, ...) [backoff inside adapter]
  → except MachineConnectionError (domain exception, not asyncssh.misc.Error)
```

### Deferred (out of scope)

- `_start_task_on_machine` → `gateway.upload_task_inputs()` — stays as callback in orchestrator for now
- `_upload_task_data`, `_exec_spawn_command`, `_write_remote_file`, `_safe_b64decode` — stay in orchestrator
- These are isolated behind a callback parameter, not a direct port violation

## Decisions

1. **Backoff parameters** — hardcoded `fibo, max_time=60`, same as current. Not configurable via ConfigLocal.
2. **`list_connected()`** — `list_connected() -> list[ConnectedMachine]` in port. Replaces `items()`.
3. **Exception for connect** — new `MachineConnectionError(DomainError)` in `domain/exceptions.py`. Gateway uses two-method pattern: inner `_connect_impl` with backoff, outer `connect` translates exhausted `SSHRetryExc` into `MachineConnectionError`. Orchestrator catches `MachineConnectionError`.
4. **Return type `download_outputs`** — `tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]]]` (meta_add + sftp_errors). Matches current `_download_task_outputs` signature. `meta_add` needed by `_finalize_task` for `task.context`. Method catches all exceptions and returns them in `sftp_errors` list.
5. **`start_occupancy_check` parameter type** — new `OccupancyConfig` Protocol in `domain/ports.py` with minimal contract (`name`, `check_pname`, `check_cmd`, `check_cmd_code`, `sleep_interval`). `domain.Engine` lacks these fields; `config.Engine` satisfies it structurally. Avoids domain→adapter and domain→config imports.
6. **`run_bg` port return type** — `None` in Protocol. Concrete returns `SSHClientProcess` (adapter type) for internal use, but port contract is `-> None`. Orchestrator discards the return value.
7. **Deferred helpers typing** — `_start_task_on_machine` and related helpers receive concrete `SSHMachineGateway` (not Protocol). Callback pattern isolates the violation until these move to adapter in a future change.
8. **`__len__` in Protocol** — added to `MachineGateway` Protocol. `orchestrator.py:607` calls `len(self._gateway)`.

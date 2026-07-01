## ADDED Requirements

### Requirement: Setup-failure disconnects machine_repository session

`CloudProvisionerImpl.allocate` SHALL disconnect the `machine_repository`
session for the failed IP before deleting the VM on the setup-failure
path. Both `except` blocks that follow the `_setup_vm` call (the
`CloudSetupError` handler and the generic `Exception` handler) SHALL
`await self.machine_repository.disconnect(ip_addr)` before
`await adapter.delete_node(...)`.

This complements the existing `CloudProvisionerImpl.stop closes
machine_repository connections` requirement: `stop()` remains the
shutdown drain, but a failed allocation mid-run would otherwise leak a
stale `FREE` session in `_sessions[ip]` pointing at a deleted VM's IP. The
allocator would then pick that session via `list_free()`, attempt
`get_cpu_cores` or `start_task_on_machine` on it, and raise
`asyncssh.misc.ChannelOpenError` — aborting the free-machine loop and
preventing any new node from being provisioned.

`SSHMachineRepository.disconnect` is a safe no-op when the IP is absent
from `_sessions` (it does `self._sessions.pop(ip, None)` and returns if
`None`), so calling `disconnect(ip_addr)` when `_connect_to_vm` itself
failed (and never registered a session) is harmless.

The success path is unchanged: on a successful `_setup_vm`, the session
stays registered so the orchestrator can reuse the connection on the next
tick (after `_persist_node_with_cleanup` flips the DB row to
`enabled=TRUE`). This is the designed behavior — only the failure path
gains a disconnect.

#### Scenario: CloudSetupError disconnects before deleting VM

- **WHEN** `_setup_vm` raises `CloudSetupError` (e.g. cloud-init failed, setup_node failed, or get_cpu_cores failed) after `_connect_to_vm` registered a session in `_sessions[ip]`
- **THEN** the `CloudSetupError` `except` block in `allocate` awaits `machine_repository.disconnect(ip_addr)` (removing the session from `_sessions` and closing the SSH connection) BEFORE awaiting `adapter.delete_node(...)` to delete the cloud VM

#### Scenario: Generic exception disconnects before deleting VM

- **WHEN** `_setup_vm` raises a non-`CloudSetupError` `Exception` after `_connect_to_vm` registered a session in `_sessions[ip]`
- **THEN** the generic `except Exception` block in `allocate` awaits `machine_repository.disconnect(ip_addr)` BEFORE awaiting `adapter.delete_node(...)` and re-raising as `CloudSetupError`

#### Scenario: No stale session leaks after failed allocation

- **WHEN** two consecutive `allocate` calls both fail at the `_setup_vm` stage
- **THEN** after each failure `machine_repository.disconnect(ip)` is called for the failed IP, `MachineRepository._sessions` contains no stale `FREE` entries for those IPs, and a subsequent `list_free()` call returns an empty list (assuming no other connected nodes)

#### Scenario: Disconnect on never-connected IP is a safe no-op

- **WHEN** `_connect_to_vm` itself fails (SSH connect error before `machine_repository.connect` registered a session) and `allocate`'s `except` block calls `machine_repository.disconnect(ip_addr)` for an IP not in `_sessions`
- **THEN** `SSHMachineRepository.disconnect` does `self._sessions.pop(ip, None)`, gets `None`, and returns without raising; `adapter.delete_node` still runs and the cloud VM is deleted

#### Scenario: Success path does not disconnect

- **WHEN** `_setup_vm` returns a `Node` successfully
- **THEN** `allocate` does NOT call `machine_repository.disconnect(ip_addr)`; the session remains registered in `_sessions` for the orchestrator to reuse on the next tick after the DB row is flipped to `enabled=TRUE`

### Requirement: Cloud-init error message includes stdout

The `CloudSetupError` raised by `_setup_vm` on a non-zero `cloud-init status --wait` exit code SHALL include both `stdout` and `stderr` in its message.

`cloud-init status --wait` writes its status line to stdout,
so omitting `stdout` (the previous behavior) yields `stderr=` (typically
empty) with no indication of why cloud-init failed.

The error message format SHALL be:
`cloud-init failed on {ip_addr}: exit={exit_code} stdout={stdout}
stderr={stderr}`.

#### Scenario: Cloud-init failure message contains stdout

- **WHEN** `cloud-init status --wait` returns `exit_code=2` with `stdout="status: error\n"` and `stderr=""` and `_setup_vm` raises `CloudSetupError`
- **THEN** the exception message contains `stdout=status: error` and `stderr=` so the operator can read the cloud-init status line from the daemon log

#### Scenario: Cloud-init timeout message is unchanged

- **WHEN** `cloud-init status --wait` times out (`asyncio.TimeoutError`)
- **THEN** the raised `CloudSetupError` message is `cloud-init status --wait timed out on {ip_addr} after {timeout}s` (the timeout branch does not read `result.stdout`/`result.stderr` and is unchanged)
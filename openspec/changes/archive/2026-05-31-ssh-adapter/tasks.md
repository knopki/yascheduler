## 1. Platform Code Relocation

- [x] 1.1 Create `adapters/ssh/__init__.py` and `adapters/ssh/platform/__init__.py`
- [x] 1.2 Move `remote_machine/checks.py` → `adapters/ssh/platform/checks.py`
- [x] 1.3 Move `remote_machine/adapters.py` → `adapters/ssh/platform/adapters.py`
- [x] 1.4 Move `remote_machine/common.py` → `adapters/ssh/platform/common.py`
- [x] 1.5 Move `remote_machine/linux_methods.py` → `adapters/ssh/platform/linux.py`
- [x] 1.6 Move `remote_machine/windows_methods.py` → `adapters/ssh/platform/windows.py`
- [x] 1.7 Move `remote_machine/protocol.py` → `adapters/ssh/platform/protocol.py`
- [x] 1.8 Move `remote_machine/exc.py` → `adapters/ssh/platform/exc.py`
- [x] 1.9 Update all internal imports in moved files to reflect new package paths
- [x] 1.10 Create re-export modules at old `remote_machine/` locations

## 2. SSHMachineGateway

- [x] 2.1 Create `adapters/ssh/gateway.py` with `SSHMachineGateway` class
- [x] 2.2 Implement `connect(ip, username, client_keys, ...)` — SSH connect with retry
- [x] 2.3 Implement platform detection during connect (run checks, select adapter)
- [x] 2.4 Implement `_machines: dict[str, _MachineState]` internal registry
- [x] 2.5 Implement `list_free(platforms)` — filter by platform and FREE state
- [x] 2.6 Implement `run(machine, cmd)` — execute command via asyncssh
- [x] 2.7 Implement `upload(machine, local, remote)` — SFTP put
- [x] 2.8 Implement `download(machine, remote, local)` — SFTP get
- [x] 2.9 Implement `disconnect(ip)` — close SSH, remove from registry
- [x] 2.10 Implement `disconnect_all()` — close all connections
- [x] 2.11 Implement occupancy monitoring (background task, pgrep/check_cmd)
- [x] 2.12 Implement `setup_node(engines)` — install packages, deploy engines
- [x] 2.13 Add GRACE-lite markup
- [x] 2.14 Write unit tests with mocked asyncssh: connect, run, upload, download, disconnect

## 3. RemoteMachine Wrapper

- [x] 3.1 Refactor `RemoteMachine.__init__` to accept `SSHMachineGateway` reference
- [x] 3.2 Delegate `run()`, `run_bg()` to gateway
- [x] 3.3 Delegate `sftp()` context manager to gateway
- [x] 3.4 Delegate `get_cpu_cores()`, `list_processes()`, `pgrep()` to gateway
- [x] 3.5 Delegate `setup_node()` to gateway
- [x] 3.6 Delegate `occupancy_check()`, `start_occupancy_check()` to gateway
- [x] 3.7 Preserve `meta` (RemoteMachineMetadata) — sync from gateway's ConnectedMachine
- [x] 3.8 Preserve `hostname`, `path`, `quote` properties
- [x] 3.9 Preserve `create()` and `create_ctx()` factory methods — internally use gateway

## 4. RemoteMachineRepository & Gateway separation

- [x] 4.1 Keep `filter()` as self-contained dict-based filtering in RemoteMachineRepository (richer API: busy/platforms/free_since_gt/reverse_sort)
- [x] 4.2 Provide `SSHMachineGateway.list_free()` as simpler FREE-machine query by platform
- [x] 4.3 Absorb `disconnect_many()` into gateway (delegated via RemoteMachine wrapper)
- [x] 4.4 Absorb `disconnect_all()` into gateway (delegated via RemoteMachine wrapper)

## 5. Wiring

- [x] 5.1 Update `di.make_daemon()` to create `SSHMachineGateway` instead of `RemoteMachineRepository`
- [x] 5.2 Update orchestrator `connect_machine_consumer` to use `gateway.connect()`
- [x] 5.3 Keep orchestrator allocator using `repo.filter()` (richer filtering); `gateway.list_free()` available for direct gateway consumers
- [x] 5.4 Update orchestrator consumer to use gateway for occupancy checks
- [x] 5.5 Verify cloud modules still work through `RemoteMachine` wrapper

## 6. Tests

- [x] 6.1 Write unit tests for `SSHMachineGateway` with faked asyncssh
- [x] 6.2 Write integration tests for gateway against Docker SSH server
- [x] 6.3 Write characterization tests: `RemoteMachine` wrapper produces same results as old code
- [x] 6.4 Update `mock_remote_machine.py` fixture to work with gateway

## 7. Verification

- [x] 7.1 Run `grace_check.py` — all files pass
- [x] 7.2 Update `docs/knowledge-graph.xml`
- [x] 7.3 Run `openspec validate --all --json`
- [x] 7.4 Run all unit tests — no regressions in remote_machine tests
- [x] 7.5 Run full test suite
- [x] 7.6 Verify import at old locations still work (no import errors in unmigrated code)

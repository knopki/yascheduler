## Context

Phase 4 part 1 of the architecture migration. `MachineGateway` port is
defined in `domain/ports.py`. `Orchestrator` (Phase 3) expects a
`MachineGateway` implementation. Currently the system uses
`RemoteMachineRepository` + `RemoteMachine` directly — these mix domain
state and SSH operations.

## Goals / Non-Goals

**Goals:**
- Implement `MachineGateway` Protocol with SSH-based adapter.
- Move platform detection and OS-specific code out of `remote_machine/`.
- Absorb `RemoteMachineRepository` registry into the gateway.
- Keep `RemoteMachine` as a compatibility wrapper for cloud modules.
- Wire orchestrator to use `SSHMachineGateway` instead of `RemoteMachineRepository`.

**Non-Goals:**
- No cloud adapter migration (Phase 4 part 2).
- No changes to cloud-init or jump-host logic — those stay in wrapper.
- No connection pooling at the SSH level.

## Decisions

### D1: SSHMachineGateway owns the machine registry

The gateway maintains an in-memory dict `{ip: SSHConnection}` of connected
machines. This replaces `RemoteMachineRepository(UserDict)`. Methods:

```python
class SSHMachineGateway:
    _machines: dict[str, _MachineState]  # ip → SSH conn + ConnectedMachine

    async def connect(self, ip: str, username: str, ...) -> None: ...
    async def disconnect(self, ip: str) -> None: ...
    async def disconnect_all(self) -> None: ...
    async def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]: ...
    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult: ...
    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None: ...
    async def download(self, machine: ConnectedMachine, remote: str, local: Path) -> None: ...
```

### D2: Platform detection at connect time

On `connect()`, the gateway runs platform checks (via asyncssh) and
constructs a `ConnectedMachine` domain object with the detected platform.
The `RemoteMachine.create()` logic moves here:

```
gateway.connect(ip, username, keys, ...)
  → SSH connect (with retry)
  → run platform checks (parallel: check_is_linux, check_is_debian, ...)
  → pick matching adapter
  → construct ConnectedMachine(ip, platform=..., ncpus=..., state=FREE)
```

### D3: Occupancy monitoring as background task

After a task starts on a machine, the gateway launches a background coroutine
that periodically checks if the engine process is still running (via pgrep
or check_cmd). When the process exits, it updates the internal
`ConnectedMachine` state to FREE. This logic moves from
`RemoteMachine.start_occupancy_check()`.

### D4: Platform code moves to adapters/ssh/platform/

All OS-specific files move:
```
remote_machine/adapters.py       → adapters/ssh/platform/adapters.py
remote_machine/checks.py         → adapters/ssh/platform/checks.py
remote_machine/common.py         → adapters/ssh/platform/common.py
remote_machine/linux_methods.py  → adapters/ssh/platform/linux.py
remote_machine/windows_methods.py → adapters/ssh/platform/windows.py
remote_machine/protocol.py       → adapters/ssh/platform/protocol.py
remote_machine/exc.py            → adapters/ssh/platform/exc.py
```

The `remote_machine/` versions become re-export modules during the transition.

### D5: RemoteMachine compatibility wrapper

```python
# remote_machine/remote_machine.py (after refactor)
class RemoteMachine:
    """Compatibility wrapper — delegates to SSHMachineGateway."""
    
    def __init__(self, gateway: SSHMachineGateway, ip: str):
        self._gateway = gateway
        self.ip = ip
        self.meta = RemoteMachineMetadata()  # preserved API
        self.hostname = ip
        # ...
    
    async def run(self, cmd, **kwargs):
        machine = self._gateway._machines[self.ip].domain_obj
        return await self._gateway.run(machine, cmd)
```

This preserves the `RemoteMachine` API for `cloud_api.py` (which creates
`RemoteMachine` instances) until Phase 4 part 2 migrates cloud modules.

### D6: MySSHClient host-key trust unchanged

The gateway inherits the current behavior of trusting all host keys
(`validate_host_public_key` returns True). This is a known security
concern documented in the pain points — not addressed in this PR.

## Risks / Trade-offs

- **Dual code path during transition**: `RemoteMachine` wrapper and
  `SSHMachineGateway` both exist. Risk of divergence. Mitigation: wrapper
  delegates ALL SSH operations to gateway; wrapper is removed after cloud
  migration (Phase 4 part 2).
- **Gateway becomes stateful**: The gateway holds SSH connections in memory.
  This is the same pattern as `RemoteMachineRepository` — no new risk.
- **Platform code relocation may break imports**: `remote_machine/` modules
  are imported by test fixtures (`mock_remote_machine.py`) and cloud modules.
  Mitigation: re-export from old locations with `from adapters.ssh.platform
  import *`.

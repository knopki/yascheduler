## Why

Phase 4 created new adapters (`adapters/ssh/`, `adapters/cloud/`) and rewrote use
cases to use UoW + domain types, but the final step — removing `remote_machine/`
and `clouds/` — was never completed. Three blockers remain:

1. `SSHMachineGateway` imports shared helpers (`ADAPTERS`, `DEFAULT_CONN_OPTS`,
   `_detect_platform`, `_init_paths`, `_resolve_tunnel`) from
   `remote_machine/remote_machine.py` instead of owning them.
2. Use cases and orchestrator import `RemoteMachine`, `RemoteMachineRepository`,
   and retry-exception types from `remote_machine/` instead of using the
   `MachineGateway` port.
3. `CloudAPI` (`clouds/cloud_api.py`) contains real logic (SSH key management,
   cloud-init rendering, node setup) and imports `RemoteMachine` directly — it
   is not a re-export wrapper.

Two parallel module trees now exist for the same concerns, creating confusion
and preventing full hexagonal architecture compliance.

## What Changes

- **Move shared SSH helpers** (`ADAPTERS`, `DEFAULT_CONN_OPTS`, `MySSHClient`,
  `_detect_platform`, `_init_paths`, `_resolve_tunnel`, `MAX_SESSIONS`,
  `my_backoff_exc`) from `remote_machine/remote_machine.py` into
  `adapters/ssh/` so the gateway owns its own infrastructure.
- **Migrate use cases & orchestrator** from `RemoteMachine` /
  `RemoteMachineRepository` to `MachineGateway` port (`SSHMachineGateway`).
  Remove all `from yascheduler.remote_machine` imports from `application/`.
- **Absorb `CloudAPI` logic** into `CloudProvisionerImpl` or dedicated
  `adapters/cloud/` helpers. Eliminate `CloudAPI`'s direct `RemoteMachine`
  dependency.
- **Remove `remote_machine/` and `clouds/` packages** entirely.
- **Update `di.py`** — stop creating `RemoteMachineRepository`; wire
  `SSHMachineGateway` directly.
- **Update tests** — remove fixtures and tests targeting deleted modules;
  add/extend tests against adapter interfaces.

## Capabilities

### New Capabilities

### Modified Capabilities

- `ssh-gateway`: Absorbs shared SSH helpers from `remote_machine/`; becomes self-contained
- `cloud-provisioner`: Absorbs cloud-init rendering and SSH key management from `CloudAPI`
- `orchestrator`: Replaces `RemoteMachineRepository` with `MachineGateway` port
- `use-cases`: Replace `RemoteMachine` / `RemoteMachineRepository` params with `MachineGateway` port
- `dependency-injection`: Wires `SSHMachineGateway` directly instead of `RemoteMachineRepository`
- `remote-machine-wrapper`: **REMOVED** — `remote_machine/` package deleted
- `cloud-wrapper`: **REMOVED** — `clouds/` package deleted
- `platform-adapters`: No spec-level changes, but source path consolidation

## Impact

- **Deleted**: `yascheduler/remote_machine/` (entire package, ~8 files),
  `yascheduler/clouds/` (entire package, ~6 files)
- **Modified**: `adapters/ssh/gateway.py`, `adapters/cloud/manager.py`,
  `application/allocate_task.py`, `application/consume_task.py`,
  `application/deallocate_nodes.py`, `application/orchestrator.py`, `di.py`,
  `scheduler.py`
- **Modified**: `clouds/cloud_api_manager.py` logic moves into
  `adapters/cloud/manager.py`; `cloud_api_manager.py` deleted
- **Tests**: Remove `tests/unit/test_remote_machine.py`,
  `tests/fixtures/mock_remote_machine.py`,
  `tests/unit/test_cloud_api_compat.py`,
  `tests/unit/test_cloud_api_manager.py`; extend adapter-level tests
- **No breaking changes** to CLI commands, `Yascheduler` public API, AiiDA plugin,
  or DB schema
- **No new dependencies**

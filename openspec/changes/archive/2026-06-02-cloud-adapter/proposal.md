## Why

Phase 4 (part 2) of the architecture migration. The `clouds/` package directly
imports `DB` (8 methods) and `RemoteMachine` — violating the hexagonal
architecture. The `CloudProvisioner` port (Phase 1) and `DB` wrapper (Phase 2)
are ready.

This change replaces `CloudAPIManager` with a `CloudProvisioner` adapter
implementing the domain port, moves providers to `adapters/cloud/`, and
switches cloud code from `db.py` to `NodeRepository`.

## What Changes

- Create `adapters/cloud/manager.py` — `CloudProvisionerImpl` implementing
  `CloudProvisioner` Protocol (allocate, deallocate, capacity).
- Move provider implementations into `adapters/cloud/providers/`:
  `az.py`, `hetzner.py`, `upcloud.py`.
- Move support modules: `adapters.py`, `protocols.py`, `utils.py`.
- `CloudAPIManager` / `CloudAPI` become re-export wrappers for backward
  compatibility with unmigrated callers.
- Cloud code switches from `self.db.add_node()` / `self.db.disable_node()`
  to `NodeRepository` (injected via UoW).
- `db.py` wrapper can be retired for cloud code paths.

## Capabilities

### New Capabilities
- `cloud-provisioner`: `CloudProvisionerImpl` adapter implementing
  `CloudProvisioner` Protocol — multi-provider allocation, deallocation,
  capacity reporting.
- `cloud-providers`: Azure, Hetzner, UpCloud VM lifecycle moved to
  `adapters/cloud/providers/`.
- `cloud-wrapper`: `CloudAPIManager` and `CloudAPI` become thin compatibility
  wrappers preserving API for unmigrated callers.

### Modified Capabilities

## Impact

- New directory: `adapters/cloud/` with `manager.py`, `providers/`
  (az, hetzner, upcloud), and support modules.
- Modified: `clouds/` — modules become re-export stubs delegating to
  `adapters/cloud/`.
- Modified: `di.make_daemon()` — creates `CloudProvisionerImpl` instead of
  `CloudAPIManager`.
- Modified: orchestrator — uses `CloudProvisioner` port instead of
  `CloudAPIManager` directly.
- `db.py` wrapper — cloud code paths can be removed from DB wrapper
  (cloud now uses `NodeRepository` directly).
- No new dependencies. Provider SDKs (azure-identity, hcloud, upcloud_api)
  already in project as optional deps.
- `docs/knowledge-graph.xml` updated.

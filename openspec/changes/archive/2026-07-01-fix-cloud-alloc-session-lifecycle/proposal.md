## Why

A real Hetzner cloud run (`docs/CLOUD_BUGS.md`, 2026-06-30) exposed five
symptoms — tasks allocated to not-yet-setup nodes, race pile-on of many tasks
onto the same node, cloud-init failures, no new node creation after two
failed allocations, and orphaned tasks. All trace to one architectural gap
(`SSHMachineRepository` registers a session on `connect` before the DB row
is enabled, so the allocator sees a setup-in-flight node as free) plus two
secondary gaps (SSH session leaks on setup failure; per-session failures
abort the whole free-machine loop). The bugs are reproducible only against
real cloud timing, so the existing unit tests (which mock `list_free`
directly) miss them.

## What Changes

- **Fix A — Gate free-machine selection on DB-enabled nodes.**
  `_find_free_machines` intersects `repository.list_free(platforms)` with
  the set of IPs enabled in `yascheduler_nodes` (read in the same UoW). A
  setup-in-flight tmp-node (`enabled=FALSE`) becomes invisible to the
  allocator. Restores the invariant: a machine is allocatable ONLY after its
  DB row is `enabled=TRUE` (which happens in `_persist_node_with_cleanup`
  after `clouds.allocate` returns, i.e. after setup succeeded). The gate
  lives in the use case, not in `MachineRepository`, so the
  `MachineRepository` Protocol is unchanged — this preserves layering and
  avoids the two-phase `connect`/`register` split (rejected as YAGNI: it
  would change the public Protocol for a class of bug Fix A already makes
  impossible in practice).
- **Fix B — Disconnect the SSH session on setup failure.**
  `CloudProvisionerImpl.allocate` calls `machine_repository.disconnect(ip)`
  before `adapter.delete_node` on both setup-failure `except` paths. Today
  only `stop()` (daemon shutdown) drains connections, so a failed allocation
  mid-run leaks a stale `FREE` session pointing at a dead IP. This adds a
  mid-run drain on the failure path; the success path is unchanged (the
  orchestrator reuses the connection, as designed).
- **Fix C — Isolate per-session failures in the free-machine loop.**
  `_allocate_free_machine` wraps each `_try_start_on_machine` call in
  `try/except Exception`, logs the failure, and continues. Today a single
  stale or transiently-unreachable session's exception propagates out of
  the loop, so the cloud-provisioning branch is never reached and the task
  spins in TO_DO.
- **Fix D — Include `stdout` in the cloud-init error message.**
  `cloud-init status --wait` writes its status line to stdout; the current
  error includes only `stderr=` (empty). Pure diagnosability improvement, no
  behavior change.

No breaking changes. No new public API, no CLI change, no DB schema change.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `cloud-provisioner`: Adds a requirement that a setup-failure during
  `allocate` disconnects the `machine_repository` session for the failed IP
  before the VM is deleted (mid-run cleanup, complementing the existing
  shutdown-only `stop()` drain).
- `orchestrator`: Adds the invariant that a machine is allocatable only if
  its IP is enabled in `yascheduler_nodes` — the free-machine query
  intersects `MachineRepository.list_free` with the DB-enabled node set.

## Impact

- **Code**: `yascheduler/application/allocate_task.py` (Fix A in
  `_find_free_machines`, Fix C in `_allocate_free_machine`);
  `yascheduler/infra/cloud/manager.py` (Fix B in `CloudProvisionerImpl.allocate`,
  Fix D in `_setup_vm` CLOUD_INIT block).
- **Tests**: new unit tests with timing-aware fakes (a `MachineRepository`
  fake that registers a session on `connect` before DB-enable, and a
  `CloudProvisioner` fake that flips the DB row to enabled only on setup
  success) to reproduce the registry-vs-DB desync and regression-guard all
  four fixes.
- **Specs**: delta requirements added to `cloud-provisioner` and
  `orchestrator` (see Capabilities).
- **Knowledge graph**: no structural change (no new modules, no new public
  surface); `CHANGE_SUMMARY` bumps on the two edited modules.
- **No public API change.** No DB schema change. No CLI change. No new
  dependencies.
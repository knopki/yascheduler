## Why

`CloudProvisionerImpl` bypasses the UoW pattern that every other adapter and
use case in the project follows. `di.py` injects `db._node_repo` — a private
field of the legacy `DB` wrapper — directly into the provisioner, which then
writes nodes outside any transaction boundary. This contradicts the original
`cloud-adapter` design (D4), which specified `uow.nodes.add_tmp(...)` /
`uow.commit()` / `uow.nodes.add(...)`. The implementation took a shortcut that
left the cloud adapter coupled to `db.py` and left node persistence hidden
inside an adapter instead of owned by use cases.

## What Changes

- **BREAKING**: `CloudProvisioner` Protocol changes — `allocate(platforms)`
  becomes `allocate(provider: str)` (caller passes selected provider name);
  `deallocate(ip)` becomes `deallocate(cloud, ip)` (caller passes cloud name
  explicitly); `capacity()` removed from the port (becomes use case
  responsibility); new sync `select_provider(platforms, current_counts) ->
  ProviderSelection | None` method added (use case calls port method,
  receives domain value object, never sees adapter types).
- **BREAKING**: `make_daemon` loses its `db: DB | None` parameter. The daemon
  no longer creates a `DB` instance and no longer runs schema migration on
  startup. Operators must run `yainit` before starting the daemon.
- New `domain/model.py` value object `ProviderSelection(name: str,
  username: str)` — returned by `CloudProvisioner.select_provider`,
  consumed by use cases. Keeps adapter types (`CloudAdapter`, `ConfigCloud`)
  out of the application layer.
- `CloudAllocateError` and `CloudSetupError` move from
  `adapters/cloud/manager.py` to `domain/exceptions.py` (re-exported from
  `yascheduler.adapters.cloud` for adapter-internal callers). Application
  layer imports from `domain.exceptions` — no `lint-imports` layer
  violation.
- `CloudProvisionerImpl` becomes a pure cloud-API adapter (create/delete VM,
  setup, SSH keys). All node persistence (`add_tmp`, `add`, `disable`,
  `remove`, `list_all` reads) moves out of the adapter.
- New `application/allocation_tracker.py` — `AllocationTracker` class holding
  the in-memory `on_tasks: set[int]` dedup state plus `add`/`discard`/
  `__contains__` operations. Replaces `mark_task_done` / `on_tasks` previously
  on the provisioner.
- New `adapters/cloud/provider_selection.py` — pure function
  `select_provider_pure(adapters, configs, platforms, current_counts, log) ->
  CloudAdapter | None`. Extracted from `CloudProvisionerImpl._select_best_provider`
  with the DB read removed. Called only from `CloudProvisionerImpl.select_provider`
  (port method implementation) — not visible to application layer.
- `allocate_task` use case takes over: capacity check, provider selection
  (via `clouds.select_provider` port method returning `ProviderSelection`),
  tmp-node insertion, cloud allocation (via `clouds.allocate(provider.name)`),
  final node persistence, tmp-node cleanup on failure.
  `allocate_with_tracking` logic moves here. Use case accepts only port
  types (`CloudProvisioner`) and domain types (`ProviderSelection`, `Node`)
  — no `CloudAdapter` or `ConfigCloud` references.
- `deallocate_nodes` use case takes over node `disable` + `remove` around the
  pure `clouds.deallocate(cloud, ip)` call. Ordering preserved from current
  code: `disable` → `delete_node` → `remove` (disable before cloud delete
  protects against re-selection if delete fails; remove after cloud delete
  ensures the DB row is only dropped once the VM is gone). Two short UoWs
  replace the current autocommit sequence. The per-node wrapper
  `deallocate_node` (singular) owns the disable+remove bracketing; the
  sweep `deallocate_nodes` (plural) remains the idle-disable use case.
- `Orchestrator._clouds_get_capacity` becomes an inline UoW read
  (`uow.nodes.list_all()` + `Counter`) instead of calling into the cloud
  adapter.
- `allocation_lock` (`asyncio.Lock`) moves from the cloud adapter into the
  `allocate_task` use case, preserving current single-process semantics.
  Follow-up (out of scope): DB-level concurrency via `SELECT ... FOR UPDATE`
  on pending tmp-nodes, or partial unique constraint with retry — registered
  as known fragility, addressed in a separate change.
- Removed from `CloudProvisionerImpl`: `node_repo` field,
  `allocate_with_tracking`, `get_capacity`, `_select_best_provider`,
  `_acquire_provider_slot`, `_safe_remove_tmp`, `mark_task_done`, `on_tasks`,
  `apis` property (dead code).
- `di.py` drops the `from .db import DB` import and the `DB.create` call.

## Capabilities

### New Capabilities

- `allocation-tracker`: In-memory dedup of in-flight cloud allocations
  (`on_tasks: set[int]` with `add`/`discard`/`__contains__`), owned by the
  application layer and injected into the allocate/consume use cases.

### Modified Capabilities

- `cloud-provisioner`: `CloudProvisionerImpl` becomes a pure cloud-API adapter.
  Port signature changes (`deallocate(cloud, ip)`, `capacity()` removed).
  Removes DB/repository dependency. Removes `allocate_with_tracking`,
  `get_capacity`, `mark_task_done`, `apis`.
- `domain-ports`: `CloudProvisioner` Protocol updated — `allocate(provider:
  str)`, `deallocate(cloud, ip)`, `capacity` removed, new sync
  `select_provider(platforms, current_counts) -> ProviderSelection | None`.
  New `ProviderSelection` domain value object.
- `use-cases`: `allocate_task` owns tmp-node + capacity + final persist;
  `deallocate_nodes` owns disable+remove around cloud delete.
- `orchestrator`: `_clouds_get_capacity` becomes inline UoW read;
  `_deallocator_consumer` performs disable and remove in two short UoWs
  bracketing `clouds.deallocate(cloud, ip)`.
- `dependency-injection`: `make_daemon` no longer creates `DB`, no longer
  accepts `db` parameter, no longer runs migration. `CloudProvisionerImpl` is
  constructed without `node_repo`.

## Impact

**Code:**
- `yascheduler/adapters/cloud/manager.py` — substantial shrinkage (~250 LOC of
  DB-coupled code removed)
- `yascheduler/adapters/cloud/provider_selection.py` — new (~50 LOC)
- `yascheduler/application/allocation_tracker.py` — new (~25 LOC)
- `yascheduler/application/allocate_task.py` — grows (takes over tmp-node +
  persist + tracking)
- `yascheduler/application/deallocate_nodes.py` — grows (takes over disable +
  remove); `deallocate_node(node, gateway, clouds, uow_factory)` signature
  gains `uow_factory` parameter to perform the two short UoWs bracketing the
  pure cloud delete
- `yascheduler/application/orchestrator.py` — `_clouds_get_capacity` rewritten
  inline; `_deallocator_consumer` updated; constructor gains
  `allocation_tracker`, `active_clouds`, and `allocation_lock` parameters
  (orchestrator-owned, injected into use cases per D4/D7/D8)
- `yascheduler/di.py` — `DB` removed, `make_daemon` simplified
- `yascheduler/domain/ports.py` — `CloudProvisioner` Protocol updated
- `yascheduler/domain/model.py` — new `ProviderSelection` value object
- `yascheduler/domain/exceptions.py` — `CloudAllocateError`,
  `CloudSetupError` relocated here from `adapters/cloud/manager.py`

**Public API stability:**
- CLI commands (`yasubmit`, `yastatus`, `yanodes`, `yasetnode`, `yainit`,
  `yascheduler`) — unchanged
- `class Yascheduler` public API — unchanged
- INI config format — unchanged
- DB schema — unchanged (no migration)
- AiiDA scheduler entrypoint — unchanged

**Tests:**
- `tests/unit/test_cloud_provisioner_impl.py` — substantial shrinkage (mock
  node_repo infrastructure removed; tests focus on pure cloud ops)
- `tests/unit/test_application_use_cases.py` — grows (assertions on node
  persistence via UoW)
- `tests/unit/test_di.py` — `DB.create` assertions removed
- `tests/e2e/test_full_cycle.py` — updated call to `make_daemon` (drops `db=`
  parameter); fixture wiring re-checked since `make_daemon` no longer
  accepts `db=`. The fixture's direct `DB` usage (`from yascheduler.db
  import DB, TaskStatus` at line 29; `db.add_node/get_task/remove_node/
  commit` at lines 67-138) survives — `client.py` DB migration is out of
  scope — but the fixture must construct `DB` independently of `make_daemon`
- New `tests/unit/test_allocation_tracker.py`
- New `tests/unit/test_provider_selection.py`

**Dependencies:** None added or removed.

**Operational:**
- Daemon no longer auto-migrates schema on startup. Operators must run `yainit`
  before first start and after any schema upgrade. Documented in change.

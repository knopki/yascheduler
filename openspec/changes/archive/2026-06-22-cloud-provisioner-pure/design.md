## Context

`CloudProvisionerImpl` (adapters/cloud/manager.py) currently mixes cloud-API
calls with node persistence. `di.py:173` injects `db._node_repo` — a private
field of the legacy `DB` wrapper — directly into the provisioner, which then
writes nodes outside any UoW transaction boundary. Every other adapter and
use case in the project uses the UoW pattern: use cases open UoW at function
scope, adapters are pure external-world clients. `SSHMachineGateway` is the
reference — pure SSH, no DB. The cloud adapter should match.

The original `cloud-adapter` design (D4, archived 2026-06-02) specified
`uow.nodes.add_tmp(...)` / `uow.commit()` / `uow.nodes.add(...)`, but the
implementation took a shortcut. This change completes the original intent by
moving all node persistence out of the adapter and into use cases.

`db.py:28` is already marked `# FIXME: remove this module`. `client.py` still
uses `DB` for query methods — that migration is a separate concern, not
blocked by this change.

## Goals / Non-Goals

**Goals:**
- Make `CloudProvisionerImpl` a pure cloud-API adapter (create/delete VM,
  setup, SSH keys) — no DB access, no `node_repo`, no UoW awareness
- Move all node persistence into use cases, which own UoW as everywhere else
- Remove `DB` from `make_daemon` (composition root no longer creates legacy
  wrapper for the daemon path)
- Extract `select_provider` as a pure function (no `self` state after DB read
  removed)
- Extract in-memory allocation dedup into a dedicated `AllocationTracker`
  class in the application layer
- Preserve the deallocate safety property: `disable` before `delete_node`
  protects against allocator re-selection on cloud-delete failure
- Preserve all public-interface stability guarantees (CLI, `Yascheduler`,
  INI, DB schema, AiiDA entrypoint)

**Non-Goals:**
- No change to cloud providers (Azure, Hetzner, UpCloud SDKs)
- No change to cloud-init templates or SSH key management logic
- No migration of `client.py` off `DB` (separate concern)
- No DB-level concurrency for allocation (single-process `asyncio.Lock`
  preserved; DB-level mechanism is a registered follow-up)
- No schema migration in the daemon path (operator runs `yainit`; variant B)
- No new dependencies
- No change to `schema-migrations` change scope

## Decisions

### D1: Cloud adapter becomes pure cloud — like SSHMachineGateway

`CloudProvisionerImpl` strips all DB code. What remains:
- `allocate(platforms) -> Node` — create VM, wait SSH, cloud-init, setup,
  return Node (no persist)
- `deallocate(cloud, ip)` — delete VM (no DB read/write)
- `stop()` — lifecycle no-op (preserved for orchestrator shutdown)
- `_get_ssh_key`, `_get_cloud_config_data`, `_setup_node`, `_connect_to_vm`
  — pure cloud/SSH helpers

**Alternative considered:** keep DB in adapter, wrap each call in UoW
internally (R1 in brief). Rejected: hides transaction boundaries inside an
adapter, creates connection churn, violates project pattern.

**Alternative considered:** pass active UoW as method parameter (R2 in
brief). Rejected: cloud ops are long (minutes); holding a pg8000 transaction
open for minutes is wrong; cloud ops are independent atomic units, not
composable into use-case transactions.

### D2: `CloudProvisioner` Protocol updated

```python
class CloudProvisioner(Protocol):
    async def allocate(self, provider: str) -> Node: ...
    async def deallocate(self, cloud: str, ip: str) -> None: ...
    def select_provider(
        self, platforms: list[str], current_counts: dict[str, int]
    ) -> ProviderSelection | None: ...
    # capacity() removed — use case responsibility
```

`allocate` takes `provider: str` (the selected provider name), not
`platforms`. Provider selection is now explicit: the use case calls
`select_provider` (sync port method) with the current node counts, gets
back a `ProviderSelection` domain value object (or `None` if no provider
has capacity). The use case then calls `allocate(selection.name)`.

`deallocate` gains explicit `cloud` parameter because the adapter no
longer reads the DB to resolve the provider from `ip`. The caller (use
case) already has the `Node` and passes `node.cloud`.

`capacity()` removed from the port. Capacity counting is a read +
arithmetic concern that belongs to the use case / orchestrator, not the
cloud adapter. The adapter has no DB to count nodes.

`select_provider` is **on the port** (not a free function) so the
application layer never touches adapter types (`CloudAdapter`,
`ConfigCloud`). The pure function `select_provider_pure` (D5) is
adapter-internal, called only from `CloudProvisionerImpl.select_provider`.

The port method is **sync** — it does no I/O. The throttle check
(`adapter.get_op_semaphore().locked()`) returns `None` on overload instead
of raising, so the method stays sync (no `await asyncio.sleep` needed).
The existing `selection is None` branch in the use case handles cleanup
(`tracker.discard`). This matches current caller-visible semantics:
`allocate_with_tracking` returned `None` (did not raise) on throttle.

New domain value object `ProviderSelection(name: str, username: str)` in
`domain/model.py` — primitive-only, no adapter references.

### D3: `allocate_task` use case owns the full cloud-fallback flow

Current `allocate_task` calls `clouds.allocate_with_tracking(on_task=...,
platforms=..., throttle=True)` as a black box. After refactor, the use case
orchestrates:

```
0. Tracker dedup at start:
   if not tracker.add(task_id):
       return False   # already in-flight

1. Capacity + provider selection + tmp-node insertion under allocation_lock
   (single short UoW, committed before lock release so concurrent selectors
   see the tmp-node):
   async with allocation_lock:
       async with uow_factory() as uow:
           nodes = await uow.nodes.list_all()
           counts = Counter(n.cloud for n in nodes if n.cloud)
           selection = clouds.select_provider(platforms, counts)  # PORT
           if selection is None:
               tracker.discard(task_id)
               return False
           tmp_ip = await uow.nodes.add_tmp(selection.name, selection.username)
           await uow.commit()

2. Cloud allocation (pure cloud, no UoW held, outside the lock):
   try:
       node = await clouds.allocate(selection.name)   # PORT, str arg
   except Exception:
       async with uow_factory() as uow:
           await uow.nodes.remove(tmp_ip)
           await uow.commit()
       tracker.discard(task_id)
       raise

3. Final persist + tmp cleanup (short UoW, outside the lock):
   async with uow_factory() as uow:
       await uow.nodes.add(node)
       await uow.nodes.remove(tmp_ip)
       await uow.commit()
```

`tracker.add(task_id)` is called at the START of the cloud-fallback path
with early-return-on-False, preserving the current `allocate_with_tracking`
dedup semantics (manager.py:256-285 checks `on_task in self.on_tasks`
first). On failure (step 2 exception), the use case calls
`tracker.discard(task_id)` after tmp-node cleanup so the task can be
retried on the next allocation cycle.

Implementation note (safety improvement beyond D3 step 3): if step 3
(`uow.nodes.add` / `remove` / `commit`) raises after `clouds.allocate`
succeeded in step 2, the VM is already up and billable with no DB row.
The implementation best-effort calls `clouds.deallocate(cloud_name, ip)`
inside the step-3 `except` (logged not raised) before tmp-node cleanup,
so a persist failure does not leak a billable orphan. `cloud_name` falls
back to `selected_name` when `node.cloud` is `None`. This is the
`_persist_node_with_cleanup` helper in `allocate_task.py`; behaviour is
covered by `test_allocate_task_failure_modes.py::test_step3_*`.

The use case accepts only port types (`CloudProvisioner`) and domain types
(`ProviderSelection`, `Node`) — no `CloudAdapter` or `ConfigCloud`
references. `adapters`/`configs` dicts stay on `CloudProvisionerImpl`,
never injected into the use case.

The `allocate_with_tracking` method on `CloudProvisionerImpl` is removed;
its dedup logic moves to `AllocationTracker` (D4), its allocation logic
moves into the use case body.

**Throttle check relocation:** the throttle check
(`adapter.get_op_semaphore().locked()`) moves INTO the port method
`CloudProvisionerImpl.select_provider` — after the pure
`select_provider_pure` call returns an adapter and before constructing the
`ProviderSelection`. If the provider is overloaded, the port method
returns `None` (does not raise). The use case's existing `selection is
None` branch handles cleanup (`tracker.discard`). This matches current
caller-visible semantics: `allocate_with_tracking` returned `None` (did
not raise) on throttle. The current `await asyncio.sleep(1)` before
raising is dropped — the sync port method cannot `await`, and the caller
retries on the next allocation cycle anyway. The existing
`allocate_with_tracking(throttle=True)` parameter is dead code (the check
lives in `_acquire_provider_slot`, not in `allocate_with_tracking`), so
removing `allocate_with_tracking` does not auto-relocate the throttle
check — it moves into the port method implementation as a `None` return.

**Alternative considered:** keep `allocate_with_tracking` as an
application-layer function. Rejected: it would duplicate the UoW
orchestration that `allocate_task` already needs for capacity check and
final persist. Folding the logic directly into `allocate_task` is simpler
and matches how `consume_task` and `deallocate_nodes` already inline their
persistence.

### D4: `AllocationTracker` — in-memory dedup in application layer

New `application/allocation_tracker.py`:

```python
class AllocationTracker:
    def __init__(self) -> None:
        self._on_tasks: set[int] = set()

    def add(self, task_id: int) -> bool:
        """Returns True if newly added, False if already tracked."""
        if task_id in self._on_tasks:
            return False
        self._on_tasks.add(task_id)
        return True

    def discard(self, task_id: int) -> None:
        self._on_tasks.discard(task_id)

    def __contains__(self, task_id: int) -> bool:
        return task_id in self._on_tasks
```

Replaces `CloudProvisionerImpl.on_tasks` set and `mark_task_done` method.
Injected into `allocate_task` (calls `add`) and `consume_task` (calls
`discard`). Owned by the orchestrator (constructed once, passed to use
cases).

**Alternative considered:** dict on orchestrator. Rejected: orchestrator
already 543 LOC; `allocate_with_tracking` moves to application layer and
needs this object — passing the orchestrator into a use case would invert
the layering (app → orchestrator). A dedicated class is ~25 LOC, testable
in isolation, and keeps the orchestrator cohesive.

### D5: `select_provider_pure` — pure function in `cloud/provider_selection.py`

```python
def select_provider_pure(
    adapters: dict[str, CloudAdapter],
    configs: dict[str, ConfigCloud],
    platforms: list[str],
    current_counts: dict[str, int],
    log: logging.Logger,
) -> CloudAdapter | None:
    ...
```

Extracted from `CloudProvisionerImpl._select_best_provider`. The method is
already pure with respect to `self` — it reads `self.adapters`,
`self.configs`, `self.log` (all config-time frozen) and `self.node_repo`
(being removed). After extraction, `current_counts` is passed in by the
caller.

**This function is adapter-internal.** It is called only from
`CloudProvisionerImpl.select_provider` (the port method implementation),
which wraps the result into a `ProviderSelection` domain value object
(after the throttle check). The application layer never calls
`select_provider_pure` directly — it calls the port method
`clouds.select_provider(platforms, counts)` and receives a
`ProviderSelection | None`.

Priority + capacity + platform-support algorithm preserved verbatim.

**Alternative considered:** expose `select_provider` as a free function
callable from the application layer. Rejected: would require passing
`adapters`/`configs` (adapter types) into the use case, violating
layering. The port method wraps the pure function and returns a domain
value object, keeping the boundary clean.

### D6: `deallocate_node` owns disable+remove bracketing

Current `deallocate_node(node, gateway, clouds)` (in
`application/deallocate_nodes.py`) calls `clouds.deallocate(ip)` as a black
box. After refactor:

```python
async def deallocate_node(
    node: Node,
    gateway: MachineGateway,
    clouds: CloudProvisioner,
    uow_factory: Callable[[], AbstractUnitOfWork],
) -> None:
    if gateway.contains(node.ip):
        await gateway.disconnect(node.ip)
    if node.cloud:
        async with uow_factory() as uow:
            await uow.nodes.disable(node.ip)
            await uow.commit()
        await clouds.deallocate(node.cloud, node.ip)
        async with uow_factory() as uow:
            await uow.nodes.remove(node.ip)
            await uow.commit()
```

Ordering preserved: `disable` → `delete_node` → `remove`. Two short UoWs
bracket the pure cloud delete. Safety property: if `delete_node` fails, the
node is already disabled so the allocator cannot re-select it. If the
second UoW fails, the VM is gone but the row remains disabled — a
reconciliation concern, not a correctness one.

The sweep `deallocate_nodes` (plural) remains the idle-disable use case;
it does not own cloud delete. Naming disambiguation: singular wrapper =
per-node cloud delete + DB bracketing; plural sweep = idle-disable sweep.

### D7: `Orchestrator._clouds_get_capacity` — inline UoW read

```python
async def _clouds_get_capacity(self) -> int:
    async with self._uow_factory() as uow:
        nodes = await uow.nodes.list_all()
    counts = Counter(n.cloud for n in nodes if n.cloud)
    max_nodes = sum(c.max_nodes for c in self._active_clouds)
    current = sum(counts[c.prefix] for c in self._active_clouds)
    return max(0, max_nodes - current)
```

`self._active_clouds` is the filtered list of cloud configs with
`max_nodes > 0` AND a successfully resolved adapter — the same filter
`di.py:154-167` currently applies when building `CloudProvisionerImpl.configs`.
The orchestrator receives this filtered list at construction (replacing the
current `self._clouds.configs` access), preserving the current semantics
exactly. Without this filter, deployments with unresolved adapters (missing
optional deps) or `max_nodes<=0` clouds would over-count `max_nodes`.

Replaces the current call to `self._clouds.get_capacity()`. The orchestrator
no longer reads `self._clouds.configs` — decoupling from cloud adapter
internals.

**Alternative considered:** separate use case
`application/count_cloud_capacity.py`. Rejected: one call site
(`_allocator_producer`), pure read + arithmetic, no domain events or
multi-step orchestration. Matches the existing inline-UoW-read precedent in
`_print_stats` (`orchestrator.py:153-155`). YAGNI.

### D8: `allocation_lock` moves into `allocate_task` use case

The `asyncio.Lock` currently lives on `CloudProvisionerImpl` and protects
`_select_best_provider + add_tmp` from concurrent double-allocation within
a single daemon process. After refactor, the lock is **orchestrator-owned
and injected** into `allocate_task` — matching the D4 `AllocationTracker`
pattern. The orchestrator constructs the lock once (in a running loop) and
passes it to the use case alongside the tracker and `uow_factory`.

Semantics preserved: single-process in-memory lock. Fragility (no
multi-process safety, no protection from external writers) is acknowledged
and registered as a follow-up. `asyncio.Lock()` requires a running loop,
so module-level instantiation is fragile — orchestrator-owned avoids this.

**Follow-up (out of scope):** DB-level concurrency via `SELECT ... FOR
UPDATE` on pending tmp-nodes, or a partial unique constraint on `(cloud, ip
LIKE 'prov-%')` with retry. Either belongs in a separate change.

### D9: `make_daemon` drops `DB` entirely

- Remove `db: DB | None = None` parameter
- Remove `await DB.create(config.db)` call
- Remove `from .db import DB` import
- `CloudProvisionerImpl` constructed without `node_repo`
- No schema migration in daemon path (variant B: operator runs `yainit`)

`schema.sql` already contains the same `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS username / port` statements that `DB.migrate()` runs — verified at
`sql/schema.sql:18-22`. `apply_schema()` (used by CLI `init`) is the
canonical migration path. Daemon relying on auto-migration was duplicating
this.

`client.py` continues to use `DB` for query methods — separate concern,
not blocked.

### D10: `CloudProvisionerImpl` constructor signature

```python
@define(frozen=True)
class CloudProvisionerImpl:
    adapters: dict[str, CloudAdapter]
    configs: dict[str, ConfigCloud]
    machine_gateway: SSHMachineGateway
    local_config: ConfigLocal
    remote_config: ConfigRemote
    engines: EngineRepository
    log: logging.Logger
```

`node_repo` field removed. `allocation_lock` removed (moves to use case).
`on_tasks` removed (moves to `AllocationTracker`).

`adapters` and `configs` stay on the adapter — they are NOT injected into
the orchestrator or use cases. The port method `select_provider` uses them
internally to call `select_provider_pure` and construct `ProviderSelection`.

### D11: `CloudAllocateError` / `CloudSetupError` relocation

`CloudAllocateError` and `CloudSetupError` currently live in
`adapters/cloud/manager.py:59`. After refactor, `allocate_task` (application
layer) catches these exceptions from `clouds.allocate(selection.name)` (VM
creation/setup failure path in D3 step 2) — but the application layer
cannot import from `adapters` at runtime per the `lint-imports` layers
contract (`pyproject.toml:118-130`:
`adapters → application → domain`).

**Fix:** move both exceptions to `yascheduler/domain/exceptions.py`.
Re-export from `yascheduler.adapters.cloud` (and
`yascheduler.adapters.cloud.manager`) for adapter-internal callers and
backwards compatibility. Application layer imports from
`yascheduler.domain.exceptions` — no layering violation.

The exceptions' names, semantics, and inheritance hierarchy are preserved.
Only the defining module changes.

## Risks / Trade-offs

- **[Tmp-node visibility under concurrency]** The `allocation_lock` +
  commit-before-release pattern relies on the tmp-node being visible to
  concurrent selectors after the first UoW commits. → Mitigation: the lock
  serializes the select+add_tmp section within a process; the commit makes
  the tmp-node visible to other transactions immediately. Documented in D8.
  Multi-process safety is a registered follow-up.

- **[Deallocate partial-failure states]** If `clouds.deallocate` succeeds
  but the second UoW (remove) fails, the VM is gone but the DB row remains
  disabled. → Mitigation: the row is disabled so the allocator skips it;
  reconciliation is an operational concern, not a correctness one. Same
  failure mode exists in current code (autocommit `remove` can also fail).

- **[Daemon no longer auto-migrates]** Operators who relied on
  `DB.create(automigrate=True)` running on daemon startup will hit schema
  errors if they upgrade without running `yainit`. → Mitigation: documented
  as BREAKING in proposal; release notes must call this out. The schema
  migration is idempotent (`IF NOT EXISTS`), so running `yainit` on an
  already-current schema is safe.

- **[Connection churn not worsened]** Current code shares one `db.conn` for
  all cloud DB ops. After refactor, each DB op opens a short UoW = new
  pg8000 connection. → Mitigation: this matches how every other use case
  already works (`allocate_task`, `consume_task`, `deallocate_nodes` all
  open multiple short UoWs). The cloud path was the outlier sharing one
  connection; after refactor it is consistent. Connection pooling is a
  separate concern (D6 in archived `cloud-adapter` design noted this as
  Phase 5.5).

- **[Event dispatch on empty event list]** Cloud ops persist Nodes, not
  Tasks, so `uow.commit()` calls `publish_events()` → `bus.dispatch([])`.
  → Mitigation: empty event list is normal; `MessageBus.dispatch` iterates
  an empty list as a no-op. No special handling needed.

- **[`allocate_with_tracking` removal]** Any external caller importing
  `CloudProvisionerImpl.allocate_with_tracking` breaks. → Mitigation:
  grep confirms no external callers — only `allocate_task.py:258` (use
  case, being refactored) and tests (being updated). `CloudProvisionerImpl`
  is not part of the public-interface stability list in AGENTS.md.

## Migration Plan

This is a code-only change with no DB schema migration. Deployment steps:

1. **Before deploying:** operator runs `yainit` to ensure schema is current
   (idempotent — safe on already-current schema).
2. **Deploy:** standard package update. Daemon restart picks up new code.
3. **Rollback:** revert package. Old daemon code re-creates `DB` and
   re-injects `db._node_repo` — no schema change to undo.

No data migration, no config format change, no INI update required.

## Open Questions

None. All three sub-questions from exploration were resolved and captured
in the proposal:
1. `AllocationTracker` class (D4) — chosen over dict on orchestrator
2. Inline capacity in orchestrator (D7) — chosen over separate use case
3. `select_provider` as port method (chosen over free function in
   application layer) — keeps adapter types (`CloudAdapter`, `ConfigCloud`)
   out of the application layer. The pure function `select_provider_pure`
   stays adapter-internal, called only from the port method implementation.
   Returns `ProviderSelection` domain value object or `None` (including on
   throttle overload — `None` return, not raise, matches current
   caller-visible semantics).

## Specs Delta Enumeration

The following spec scenarios require delta updates in the `specs/` batch
(non-exhaustive — full delta content written in the specs batch):

- **`cloud-provisioner/spec.md`:**
  - "Deallocate removes VM and DB record" scenario uses `deallocate("10.0.0.1")`
    (old single-arg) → update to `deallocate(cloud, ip)` two-arg form
  - "Capacity reports available nodes" scenario references removed `capacity()`
    → remove scenario, point to use-case-owned capacity
  - "Concurrent allocation throttling" requirement currently sits on the
    provisioner → move to application layer (AllocationTracker + lock +
    throttle check in D3 critical section)
- **`dependency-injection/spec.md`:**
  - Line 12 hard-codes `db: DB | None = None` in `make_daemon` signature →
    remove `db` parameter
  - Lines 22-24 "make_daemon accepts pre-built dependencies" explicitly
    require the `db=` parameter behavior being removed → update scenario
- **`use-cases/spec.md`:**
  - Line 40 references `cloud.allocate_with_tracking(...)` → replace with
    inline allocate_task flow (D3)
- **`domain-ports/spec.md`:**
  - `CloudProvisioner` Protocol requirement → `deallocate(cloud, ip)` and
    removal of `capacity`

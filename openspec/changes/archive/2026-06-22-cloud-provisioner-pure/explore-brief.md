# Explore Brief: cloud-provisioner-pure

## Problem

`CloudProvisionerImpl` (adapters/cloud/manager.py) bypasses the UoW pattern.
`di.py:173` injects `db._node_repo` (private field of legacy `DB` wrapper) into
the provisioner. The provisioner then writes nodes via this standalone
repository, autocommitting each call, outside any transaction boundary and
outside the UoW used by the calling use case.

This contradicts the original `cloud-adapter` design (D4, archived), which
specified `uow.nodes.add_tmp(...)` / `uow.commit()` / `uow.nodes.add(...)`. The
implementation took a shortcut.

## Rejected Alternatives

### R1: UoW opened inside each cloud adapter method

Replace `node_repo` with `uow_factory` in constructor; each method
(`allocate`, `deallocate`, `capacity`) opens its own UoW internally.

**Rejected because:**
- Hides transaction boundaries inside an adapter (no other adapter does this)
- Creates connection churn: `allocate()` would open 3+ UoWs (select+add_tmp /
  add / remove_tmp) where the legacy approach used one shared connection
- Violates the project pattern: use cases own UoW, adapters are pure
- Architectural mistake — "shoving UoW inside" rather than refactoring

### R2: Pass active UoW as method parameter

`allocate(platforms, uow)`, `deallocate(ip, uow)`. Caller opens UoW, passes it
in. Cloud op runs inside caller's transaction.

**Rejected because:**
- Cloud ops are long (VM creation + SSH wait + cloud-init = minutes)
- Holding a pg8000 transaction open for minutes is wrong
- Cloud ops should not share transactions with use-case logic; they are
  independent atomic units

### R3: Keep DB in make_daemon, only swap node_repo → uow_factory

Minimal change: just replace the injected dependency, leave `DB.create` for
migrations.

**Rejected because:**
- User confirmed `make_daemon` is not public API; DB can be removed cleanly
- `DB.create(automigrate=True)` duplicates `apply_schema()` (schema.sql already
  contains the same ALTER TABLE statements)
- `db.py:28` is already marked `# FIXME: remove this module`
- Keeping DB just for migrations in daemon path is out of scope of
  `schema-migrations` change; user chose variant B (daemon doesn't migrate,
  operator runs `yainit`)

## Final Approach

**Cloud adapter becomes pure cloud-API client — like SSHMachineGateway is pure
SSH.** All node persistence moves up to use cases, which own UoW as everywhere
else in the project.

### Module responsibility changes

| Module                       | Before                                   | After                                              |
| ---------------------------- | ---------------------------------------- | -------------------------------------------------- |
| `adapters/cloud/manager.py`  | Cloud ops + node persistence             | Cloud ops only (create/delete VM, setup, SSH keys) |
| `application/allocate_task.py` | Calls `clouds.allocate_with_tracking`    | Owns tmp-node, capacity check, final persist       |
| `application/deallocate_nodes.py` | Calls `clouds.deallocate(ip)`            | Owns disable+remove around `clouds.deallocate(cloud, ip)` |
| `application/orchestrator.py` | `_clouds_get_capacity` calls cloud DB    | Inline UoW read + arithmetic                       |
| `di.py`                      | Creates `DB`, extracts `_node_repo`      | No `DB`; passes `uow_factory` to use cases only    |

### New modules

| Module                                    | Purpose                                            | Size    |
| ----------------------------------------- | -------------------------------------------------- | ------- |
| `application/allocation_tracker.py`       | In-memory `on_tasks: set[int]` + add/discard/contains | ~25 LOC |
| `adapters/cloud/provider_selection.py`    | Pure function `select_provider_pure(adapters, configs, platforms, current_counts, log) -> CloudAdapter \| None` (adapter-internal, called only from `CloudProvisionerImpl.select_provider` port method) | ~50 LOC |
| `domain/model.py` (addition)              | `ProviderSelection(name: str, username: str)` value object — returned by port method, keeps adapter types out of application layer | ~10 LOC |

### Removed from CloudProvisionerImpl

| Symbol                       | Reason                                                |
| ---------------------------- | ----------------------------------------------------- |
| `node_repo` field            | No DB in adapter                                      |
| `allocate_with_tracking`     | Moves to application layer (use case logic)           |
| `get_capacity`               | Moves to orchestrator inline (UoW read + arithmetic)  |
| `_select_best_provider`      | Moves to `cloud/provider_selection.py` as pure func   |
| `_acquire_provider_slot`     | Dissolved; tmp-node logic moves to use case           |
| `_safe_remove_tmp`           | Dissolved; tmp-node cleanup moves to use case         |
| `mark_task_done` / `on_tasks` | Moves to `AllocationTracker` in application layer     |
| `apis` property              | Dead code (only test caller)                          |

### CloudProvisioner port changes

```python
class CloudProvisioner(Protocol):
    async def allocate(self, provider: str) -> Node: ...  # was platforms
    async def deallocate(self, cloud: str, ip: str) -> None: ...  # cloud explicit
    def select_provider(self, platforms: list[str], current_counts: dict[str, int]) -> ProviderSelection | None: ...  # NEW, sync
    # capacity() removed — use case responsibility
```

New domain value object `ProviderSelection(name: str, username: str)` —
returned by `select_provider`, consumed by use cases. Keeps adapter types
(`CloudAdapter`, `ConfigCloud`) out of the application layer. The pure
function `select_provider_pure` stays adapter-internal, called only from
`CloudProvisionerImpl.select_provider` (port method implementation).

### Exception relocation

`CloudAllocateError` and `CloudSetupError` move from
`adapters/cloud/manager.py` to `domain/exceptions.py` (re-exported from
`yascheduler.adapters.cloud` for adapter-internal callers). Application
layer imports from `domain.exceptions` — no `lint-imports` layer violation.

### Cross-module data flows

**Allocate (cloud fallback):**
```
allocate_task use case:
  if not tracker.add(task_id): return False   # dedup at start
  # Capacity + provider selection + tmp-node (atomic, short tx, under lock)
  async with allocation_lock:
      async with uow_factory() as uow:
          nodes = await uow.nodes.list_all()
          counts = Counter(n.cloud for n in nodes if n.cloud)
          selection = clouds.select_provider(platforms, counts)  # PORT method
          if selection is None: return False
          tmp_ip = await uow.nodes.add_tmp(selection.name, selection.username)
          await uow.commit()          # visible immediately
  # Cloud op (БЕЗ UoW, минуты — но БД не трогается)
  try:
      node = await clouds.allocate(selection.name)   # PORT method, str arg
  except Exception:
      async with uow_factory() as uow:
          await uow.nodes.remove(tmp_ip)
          await uow.commit()
      tracker.discard(task_id)
      raise
  # Persist final node (короткая tx)
  async with uow_factory() as uow:
      await uow.nodes.add(node)
      await uow.nodes.remove(tmp_ip)
      await uow.commit()
```

**Deallocate:**
```
orchestrator._deallocator_consumer:
  async with uow: node = uow.nodes.get(ip)   # already there
  if node: await deallocate_node(node, gateway, clouds)
    # deallocate_node:
    if gateway.contains(node.ip): await gateway.disconnect(node.ip)
    if node.cloud:
      async with uow: uow.nodes.disable(ip); uow.commit()   # mark first
      await clouds.deallocate(node.cloud, node.ip)          # pure cloud, no DB
      async with uow: uow.nodes.remove(ip); uow.commit()    # cleanup after success
```

Ordering rationale: `disable` before `delete_node` protects against allocator
re-selecting the node if `delete_node` fails. `remove` after `delete_node`
ensures the DB row is only dropped once the VM is gone. Two short UoWs instead
of one is the price of preserving this safety property.

**Capacity (allocator producer):**
```
orchestrator._clouds_get_capacity:
  async with uow: nodes = uow.nodes.list_all()
  counts = Counter(n.cloud for n in nodes if n.cloud)
  return max(0, sum(c.max_nodes for c in config.clouds) -
                 sum(counts[c.prefix] for c in config.clouds))
```

### allocation_lock handling

Current: `asyncio.Lock` inside `_acquire_provider_slot` protects
`select_best_provider + add_tmp` from concurrent double-allocation.

Decision: **move lock into use case as-is (Variant 3)**. Preserves current
semantics. Fragility (single-process only) is acknowledged but not addressed
in this change — registered as follow-up.

Follow-up (out of scope): DB-level concurrency via `SELECT ... FOR UPDATE` on
pending tmp-nodes, or partial unique constraint on `(cloud, ip LIKE 'prov-%')`
with retry. Either belongs in a separate change.

### DB removal from make_daemon

- Remove `db: DB | None = None` parameter from `make_daemon`
- Remove `await DB.create(config.db)` call
- Remove `from .db import DB` import (if no other use in di.py)
- No migration replacement in daemon (variant B); operator runs `yainit`
- `client.py` still uses `DB` for queries — separate concern, not blocked

### Event dispatch note

Cloud ops don't record domain events (they persist Nodes, not Tasks).
`uow.commit()` calls `publish_events()` → `bus.dispatch([])`. Empty event list
is normal; no special handling needed.

## Open Questions

None remaining. All three sub-questions from exploration were resolved:
1. `AllocationTracker` class (chosen over dict on orchestrator)
2. Inline capacity in orchestrator (chosen over separate use case)
3. `select_provider` as port method (chosen over free function in
   application layer) — keeps adapter types (`CloudAdapter`, `ConfigCloud`)
   out of the application layer. The pure function `select_provider_pure`
   stays adapter-internal, called only from the port method implementation.
   Returns `ProviderSelection` domain value object or `None` (including on
   throttle overload — `None` return, not raise, matches current
   caller-visible semantics).

# Explore Brief — node-id-keyed-mutators

## Alternatives considered and rejected

1. **Whole-project ip→node_id replacement in one change**: rejected — touches SSH transport (Surface A, ip=dial address) and Task.allocated_ip (Surface C, schema migration + events + 3 use-cases + CLI + webhook). Too big, mixes concerns. Deferred to follow-up changes.

2. **Lookup methods (get/get_by_ips) switched to node_id in this change**: rejected — these are entry points from ip-keyed queues (deallocator `UMessage[str,str]`, `idle_machines: dict[str,float]`). Switching them pulls Surface A in. Deferred (Surface B-3).

3. **add_tmp refactored to return Node, fake-ip removed**: rejected for THIS change — pulls in `insert_tmp.sql`, `_select_and_insert_tmp`/`_cleanup_tmp_node_best_effort`/`_persist_node_with_cleanup` rework, `Node.ip: str → str | None` across 74 call-sites, 3 `"." in ip` echo-filters, migration 003. Separate change (`remove-tmp-node-fake-ip`).

4. **remove stays ip-keyed (variant b)**: initially considered to avoid touching tmp-cleanup. Rejected per user direction — `remove` goes to `node_id` like the other mutators; tmp-cleanup gets a `get(tmp_ip)` lookup before `remove(node.node_id)` (best-effort path, tmp-node just inserted, no TOCTOU risk).

5. **`Union[str, NodeId]` on mutators for test backward-compat**: rejected — `Union` erodes the type-safety that's the whole point. Tests are updated instead.

6. **manage_node helpers accept `(node_id, ip)` pair**: rejected in favor of `(node: Node)` — single key, no risk of ip/node_id desynchronization, validation already has the Node.

## Final approach — labels/dimensions/mapping tables

### Mutator signature mapping (NodeRepository Protocol)

| Method      | Before                | After                      |
| ----------- | --------------------- | -------------------------- |
| `enable`    | `enable(ip: str)`     | `enable(node_id: NodeId)`  |
| `disable`   | `disable(ip: str)`    | `disable(node_id: NodeId)` |
| `remove`    | `remove(ip: str)`     | `remove(node_id: NodeId)`  |
| `update`    | `update(node: Node)`  | `update(node: Node)` (sig unchanged; SQL `WHERE node_id`) |

### SQL mapping

| SQL file                  | Before `WHERE`       | After `WHERE`              |
| ------------------------- | -------------------- | -------------------------- |
| `node/enable.sql`         | `WHERE ip = :ip`     | `WHERE node_id = :node_id` |
| `node/disable.sql`        | `WHERE ip = :ip`     | `WHERE node_id = :node_id` |
| `node/remove.sql`         | `WHERE ip = :ip`     | `WHERE node_id = :node_id` |
| `node/update.sql`         | `WHERE ip = :ip`     | `WHERE node_id = :node_id` |

SQL param: `node_id.value: int` (pg8000 cannot adapt `NodeId` dataclass — same pattern as `get_by_id`).

### Call-site mapping (application)

| Call-site (file)                          | Before                          | After                                       |
| ----------------------------------------- | ------------------------------- | ------------------------------------------- |
| `deallocate_node` disable                 | `disable(node.ip)`              | `disable(node.node_id)`                     |
| `deallocate_node` remove                  | `remove(node.ip)`               | `remove(node.node_id)`                      |
| `deallocate_nodes` disable (loop)         | `disable(ip)` (ip from dict key)| `disable(node.node_id)` (Node from dict val)|
| `abandon_node` remove                     | `remove(node.ip)`               | `remove(node.node_id)`                      |

### Call-site mapping (allocate_task tmp-cleanup — lookup pattern)

| Call-site                                 | Before                         | After                                              |
| ----------------------------------------- | ------------------------------ | -------------------------------------------------- |
| `_cleanup_tmp_node_best_effort`           | `remove(tmp_ip)`               | `node = get(tmp_ip); if node: remove(node.node_id)`|
| `_persist_node_with_cleanup`              | `remove(tmp_ip)`               | `node = get(tmp_ip); if node: remove(node.node_id)`|

### Call-site mapping (CLI manage_node — helper signature)

| Helper             | Before signature                | After signature                  |
| ------------------ | ------------------------------- | -------------------------------- |
| `_remove_node_hard`| `(deps, ip: str)`               | `(deps, node: Node)`             |
| `_remove_node_soft`| `(deps, ip: str)`               | `(deps, node: Node)`             |

Validation UoW resolves `Node` early (both paths):
- node_id path: `get_by_id(target.node_id) → Node`
- host_spec path: `get(spec.host) → Node`

Helpers use `node.node_id` for `nodes.disable/remove`, `node.ip` for `tasks.list_ids_by_ip_and_status` (Surface C, unchanged) and user-facing logs.

### Log mapping

| Where                              | Before          | After                          |
| ---------------------------------- | --------------- | ------------------------------ |
| `deallocate_node` (all log lines)  | `ip=%s`         | `node_id=%s ip=%s`             |
| `abandon_node` (all log lines)     | `ip=%s`         | `node_id=%s ip=%s`             |
| `manage_node` user-facing output   | `ip` only       | `ip` only (node_id not meaningful to operator) |

## Key cross-module data flows

### Flow 1: deallocate_node (app, has Node in hand)

```
orchestrator._deallocator_consumer
  → uow.nodes.get(ip)                    [unchanged, ip-keyed lookup]
  → deallocate_node(node, repository, clouds, uow_factory)
      → repository.contains(node.ip)     [Surface A, unchanged]
      → repository.disconnect(node.ip)   [Surface A, unchanged]
      → uow.nodes.disable(node.node_id)  [CHANGED: was node.ip]
      → clouds.deallocate(node.cloud, node.ip)  [unchanged, ip=cloud host]
      → uow.nodes.remove(node.node_id)   [CHANGED: was node.ip]
```

### Flow 2: tmp-cleanup (app, has only ip — lookup added)

```
_persist_node_with_cleanup(node, clouds, uow_factory, selected_name, tmp_ip, task_id)
  on failure path:
    → uow.nodes.get(tmp_ip)              [NEW lookup, best-effort]
    → if node: uow.nodes.remove(node.node_id)  [CHANGED: was remove(tmp_ip)]
  on success path:
    → uow.nodes.insert(node)             [unchanged]
    → uow.nodes.get(tmp_ip)              [NEW lookup]
    → if node: uow.nodes.remove(node.node_id)  [CHANGED]
```

### Flow 3: manage_node remove (CLI, Node resolved in validation)

```
_manage_node_async(argv)
  → validation UoW:
      node_id path:  get_by_id(target.node_id) → Node
      host_spec path: get(spec.host)           → Node
  → _remove_node_soft/hard(deps, node: Node)
      → uow.tasks.list_ids_by_ip_and_status(node.ip, RUNNING)  [unchanged, Surface C]
      → uow.nodes.disable(node.node_id)  [CHANGED: was node.ip]
      → uow.nodes.remove(node.node_id)   [CHANGED: was node.ip]
      → print(f"Removed host... {node.ip}")  [user-facing, ip stays]
```

## Open questions

All resolved during explore:
1. `update` in scope — yes (free, sig already takes Node).
2. Logs — `node_id=%s ip=%s` together in internal logs; user-facing CLI stays ip-only.
3. `add_tmp` — out of scope (separate change `remove-tmp-node-fake-ip`).
4. `remove` — fully on node_id, tmp-cleanup gets `get(tmp_ip)` lookup.
5. manage_node helpers — take `Node`, not `(node_id, ip)` pair.
6. `list_ids_by_ip_and_status` — stays ip-keyed (Surface C).
7. `get`/`get_by_ips`/`list_*` — out of scope (Surface B-3).
8. SSH layer — out of scope (Surface A).
9. rowcount check on `remove` after lookup — no (matches current no-op-on-0-rows behavior).
10. Test updates — 8 unit asserts + 2 integration calls + new tmp-cleanup lookup tests.
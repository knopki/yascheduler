# Explore Brief — deallocate-node-id-identity

## What we're doing

Rekey the deallocate flow from ip-as-identity to NodeId-as-identity. This is the **only** remaining ip-as-identity surface where NodeId is available on both ends of the handoff, so the rekey is mechanical and locally contained.

## Why this surface and not others

Structural fact: SSH connections open **before** the DB row exists (`connect` → `insert` in both the CLI add-node and CloudProvisionerImpl.allocate flows). So `ConnectedMachine.ip` and `_sessions` cannot be rekeyed to NodeId without reordering the lifecycle and handling orphaned rows on connect failure — that's a separate, much larger change. Likewise `Task.allocated_ip` is a schema field whose removal requires a migration plus cascading through ~6 Task↔Node join sites — another separate surface.

The deallocate flow is the **only** surface where NodeId already exists on both ends:

```
deallocate_nodes() -> list[str]                    # throws Node away, keeps ip
producer: yield UMessage(ip, ip)                    # UniqueQueue[str, str]
consumer:
    node = uow.nodes.get(ip)                       # ip → Node round-trip lookup
    deallocate_node(node, ...)
```

The Node returned by `list_disabled()` already carries `node_id`; we discard it to a bare ip, then reconstruct it via `uow.nodes.get(ip)`. Eliminating the round-trip and carrying Node through the queue is the win.

## Alternatives rejected

- **SSH rekey (Surface A)**: requires reordering `connect`→`insert` in two flows (CLI add-node, CloudProvisionerImpl.allocate) and handling orphaned DB rows when connect fails after insert. Not "one place" — a lifecycle rearchitecture.
- **Task.allocated_ip → allocated_node_id (Surface E)**: schema migration + cascade through `_task_consumer` (`get_session`), `_start_task_on_machine` (`get(allocated_ip)`), `abandon_node` (`allocated_ip == node.ip`), `show_nodes` (`tasks_by_ip.get(node.ip)`), `check_status` (`get_by_ips(ips)`), `_find_free_machines` (`busy_node_ips`). Six join sites.
- **Cloud deallocate host (Surface C)**: `ip` here is the cloud host argument to `adapter.delete_node(host=ip)`; cloud SDK doesn't know NodeId.
- **`idle_machines: dict[ip, float]`**: source is `ConnectedMachine.ip` from `list_connected()` — blocked on SSH rekey.

## The "." in node.ip filter — same lineage, must clean together

`deallocate_nodes` line ~159: `if n.ip not in busy_ips and "." in n.ip and n.cloud`.

The `"." in node.ip` guard is **orphaned** from the fake-ip era:

- **Before migration 003**: tmp-node ip was `prov||<md5hex>` (no dots). `list_disabled` returned tmp rows. The python `"." in node.ip` post-filter excluded them from the deallocate candidate set.
- **After migration 003** (remove-tmp-node-fake-ip, archived): tmp-node ip is `""`. `list_disabled.sql` filters `WHERE ip <> ''` at SQL level. The python `"." in node.ip` guard became **dead code** — it now only "protects" against hypothetical non-ipv4 disabled cloud nodes, which don't exist (all providers return ipv4; schema is `VARCHAR(15)` which can't hold ipv6/long hostnames).

`remove-tmp-node-fake-ip` cleaned the SQL and repository layers but left this caller-side guard in `deallocate_nodes`. It is the same ip-as-identity debt, in the same function we're refactoring — cleaning it together.

## Design — labels / mapping / flows

### Current flow

```
deallocate_nodes(uow_factory, config_clouds, idle_machines) -> list[str]
  busy_ips = {t.allocated_ip for t in running if t.allocated_ip}        # Surface E (stays)
  all_enabled_nodes = {n.ip: n for n in list_enabled()
                       if n.ip not in busy_ips}                         # ip-join with Task (E, stays)
  # phase 1: disable idle cloud nodes
  for node in all_enabled_nodes.values():
      if matches cloud and idle beyond tolerance:
          uow.nodes.disable(node.node_id)                              # already NodeId
  # phase 2: collect free disabled cloud nodes
  free_disabled_nodes = [n for n in list_disabled()
                         if n.ip not in busy_ips
                         and "." in n.ip                               # DEAD (prov era)
                         and n.cloud]
  return [node.ip for node in free_disabled_nodes]                    # throws Node away

orchestrator._deallocator_producer:
  disabled_ips = await deallocate_nodes(...)
  for ip in disabled_ips:
      yield UMessage(ip, ip)                                           # UniqueQueue[str, str]

orchestrator._deallocator_consumer:
  ip = msg.payload
  async with uow_factory() as uow:
      node = await uow.nodes.get(ip)                                   # B-1 round-trip lookup
  if node is not None:
      await deallocate_node(node, repo, clouds, uow_factory)           # deallocate_node already takes Node
  elif repo.contains(ip):
      await repo.disconnect(ip)                                        # Surface A (stays ip)
```

### Proposed flow

```
deallocate_nodes(uow_factory, config_clouds, idle_machines) -> list[Node]
  busy_ips = {t.allocated_ip ...}                                       # unchanged (Surface E)
  all_enabled_nodes = {n.ip: n ...}                                     # unchanged (Surface E)
  # phase 1: disable idle cloud nodes — unchanged (already NodeId)
  ...
  # phase 2: collect free disabled cloud nodes
  free_disabled_nodes = [n for n in list_disabled()
                         if n.ip not in busy_ips
                         and n.cloud]                                  # "." in n.ip REMOVED
  return free_disabled_nodes                                            # list[Node] (carries node_id)

orchestrator._deallocator_producer:
  disabled_nodes = await deallocate_nodes(...)
  for node in disabled_nodes:
      yield UMessage(node.node_id, node)                               # UniqueQueue[NodeId, Node]

orchestrator._deallocator_consumer:
  node = msg.payload                                                    # NO uow.nodes.get(ip) lookup
  try:
      await deallocate_node(node, repo, clouds, uow_factory)
  # SSH fallback stays ip (Surface A — separate surface)
  if repo.contains(node.ip):
      await repo.disconnect(node.ip)
```

### What's rekeyed (ip → NodeId)

| Site | Before | After |
|---|---|---|
| `deallocate_nodes` return type | `list[str]` | `list[Node]` |
| `_deallocate_q` type param | `UniqueQueue[str, str]` | `UniqueQueue[NodeId, Node]` |
| queue message id | `ip` | `node.node_id` |
| queue message payload | `ip` | `Node` |
| consumer node acquisition | `uow.nodes.get(ip)` (round-trip) | `msg.payload` (direct) |
| `"." in node.ip` filter | present (dead) | removed |

### What stays ip — and which surface it belongs to

| Site | Surface | Why it stays (architectural, not scope-argument) |
|---|---|---|
| `busy_ips = {t.allocated_ip}` | E (Task linkage) | Schema field; removal = migration + 6-site cascade. Separate change. |
| `all_enabled_nodes = {n.ip: n}` | E | Joins with `busy_ips`; leaves with E. |
| `idle_machines: dict[ip, float]` | A (SSH) | Source is `ConnectedMachine.ip` from `list_connected()`; SSH session registered by ip before insert (NodeId doesn't exist yet). SSH rekey surface. |
| `repo.contains(node.ip)` / `repo.disconnect(node.ip)` | A (SSH) | `_sessions` keyed by ip. SSH rekey surface. |
| `clouds.deallocate(node.cloud, node.ip)` | C (cloud host) | `ip` = cloud host arg to `delete_node(host=ip)`; cloud SDK has no NodeId concept. |

These aren't "out of scope" of some prior proposal — they are **different architectural surfaces** (SSH lifecycle, schema, cloud SDK contract), each meriting its own change. This change picks the one surface where NodeId exists on both ends.

## Cross-module data flow

```
list_disabled() ──Node(node_id)──▶ deallocate_nodes ──list[Node]──▶ _deallocator_producer
                                                                        │
                                                          UMessage[NodeId, Node]
                                                                        │
                                                   _deallocator_consumer ◀──┘
                                                                        │
                                              node = msg.payload (Node, carries node_id)
                                                                        │
                                              ┌─────────────────────────┴─────────────────────┐
                                              ▼                                                 ▼
                                  deallocate_node(node, ...)                        repo.contains(node.ip)
                                  uow.nodes.disable/remove(node.node_id)            repo.disconnect(node.ip)  [SSH: ip]
                                  clouds.deallocate(node.cloud, node.ip)  [C: host]
```

## Open questions

1. **`deallocate_node` exception path**: currently the consumer wraps `deallocate_node` + the `elif repo.contains(ip): disconnect(ip)` fallback in a single `try/except Exception`. In the new flow, when should the SSH fallback `disconnect` run — only when `deallocate_node` raises, or unconditionally after? Current behavior: only when `node is None` (row already gone). New behavior: `node` is never None (comes from queue), so the fallback semantics need a deliberate decision — see design.md.
2. **Queue dedup semantics**: `UniqueQueue` dedups by `id`. Switching id from ip to NodeId: is there any producer cycle where the same NodeId could legitimately be re-enqueued and we'd want to skip it (current behavior skips duplicate ip)? NodeId is unique per row, ip is not (duplicates behind jump hosts valid post-migration-003), so NodeId dedup is strictly safer. Confirm no behavior regression.
3. **Logging markers**: `deallocate_nodes` and consumer log lines currently reference `ip=%s`. Do we add `node_id=%s` alongside (matching the `node-id-keyed-mutators` convention from prior changes), or fully replace? Convention from `abandon_node`/`deallocate_node` is "add node_id alongside ip" — follow that.
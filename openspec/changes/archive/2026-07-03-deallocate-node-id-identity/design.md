## Context

The deallocate flow carries a `Node` (with `node_id`) through three stages: `deallocate_nodes` reads `Node` from `list_disabled()`, the orchestrator enqueues it, and `_deallocator_consumer` passes it to `deallocate_node(node, ...)`. Today the `Node` is discarded to a bare `ip` string between stages 1 and 2, then reconstructed via `uow.nodes.get(ip)` in stage 3 — a wasted DB round-trip. The dedup key on the queue is `ip`, which is no longer `UNIQUE` (migration 003 dropped the unique constraint; duplicate IPs are valid behind different jump hosts), so two nodes sharing an IP would dedup to one queue entry. `NodeId` is a `SERIAL PRIMARY KEY` and strictly unique.

The same `deallocate_nodes` function carries a `"." in node.ip` post-filter that was a tmp-node guard for the `prov||<md5hex>` sentinel era. After migration 003 (`remove-tmp-node-fake-ip`), tmp-nodes carry `ip=""` and are excluded at SQL level by `list_disabled.sql` (`WHERE ip <> ''`), so the python guard is dead.

Constraints:
- `deallocate_node` already accepts `Node` and internally calls `repository.contains(node.ip)` + `repository.disconnect(node.ip)` (lines 56-57) — SSH disconnect is already owned by `deallocate_node`, not the consumer.
- `clouds.deallocate(node.cloud, node.ip)` takes `ip` as the cloud host argument (cloud SDK contract — `delete_node(host=ip)`); this stays ip-keyed.
- `idle_machines: dict[str, float]` is sourced from `ConnectedMachine.ip` via `list_connected()`; SSH `_sessions` is keyed by ip because `connect` runs before `insert` (NodeId doesn't exist at connect time). Rekeying SSH is a separate lifecycle rearchitecture, not this change.
- `busy_ips = {t.allocated_ip}` joins `Task.allocated_ip` (a schema field) with `Node.ip`; rekeying Task linkage is a separate schema migration with a 6-site cascade, not this change.

## Goals / Non-Goals

**Goals:**
- Eliminate the `uow.nodes.get(ip)` round-trip lookup in `_deallocator_consumer` by carrying `Node` through the queue.
- Rekey `_deallocate_q` dedup from `ip` (non-unique post migration 003) to `NodeId` (strictly unique `SERIAL PK`).
- Remove the dead `"." in node.ip` post-filter from `deallocate_nodes` phase 2.
- Preserve `deallocate_node`'s internal SSH disconnect ownership (no new SSH responsibility in the consumer).
- Add `node_id=%s` alongside `ip=%s` in `deallocate_nodes` log lines, matching the `node-id-keyed-mutators` convention already applied to `deallocate_node` and `abandon_node`.

**Non-Goals:**
- Rekey SSH `MachineRepository` (`_sessions: dict[ip, Session]`) to NodeId — requires reordering `connect`→`insert` in CLI add-node and `CloudProvisionerImpl.allocate` flows and handling orphaned DB rows on connect failure. Separate architectural change.
- Rekey `Task.allocated_ip` to `allocated_node_id` — schema migration plus cascade through `_task_consumer` (`get_session`), `_start_task_on_machine` (`get(allocated_ip)`), `abandon_node` (`allocated_ip == node.ip`), `show_nodes` (`tasks_by_ip.get(node.ip)`), `check_status` (`get_by_ips`), `_find_free_machines` (`busy_node_ips`). Separate change.
- Rekey `clouds.deallocate(cloud, ip)` / `adapter.delete_node(host=ip)` — `ip` is the cloud host argument; cloud SDK has no NodeId concept. Separate contract change.
- Remove `busy_ips` or `idle_machines` ip-keying — both are blocked on the surfaces above (Task linkage and SSH respectively).
- Change `deallocate_node`'s signature or internal logic — it already takes `Node` and keys mutators on `node_id`. Only its caller (the consumer) and its sibling (`deallocate_nodes`) change.

## Decisions

### D1: `deallocate_nodes` returns `list[Node]`, not `list[str]`

**Choice:** Phase 2 returns `free_disabled_nodes` (the `list[Node]` it already holds), not `[node.ip for node in free_disabled_nodes]`.

**Rationale:** The `Node` objects are already in hand from `list_disabled()`. Throwing them away to ip strings forces the consumer to reconstruct them via `uow.nodes.get(ip)`. Returning `Node` eliminates the round-trip and lets the queue carry `NodeId` as the dedup key.

**Alternative considered:** Return `list[NodeId]` and have the consumer do `uow.nodes.get_by_id(node_id)`. Rejected — it reintroduces a round-trip lookup (by-id instead of by-ip, but still a lookup) and discards the `ip`/`cloud` fields the consumer needs for the SSH fallback and `clouds.deallocate` call. Carrying the full `Node` is strictly better: no lookup, all fields available.

### D2: `_deallocate_q` rekeyed to `UniqueQueue[NodeId, Node]`

**Choice:** The queue's message id becomes `node.node_id` (`NodeId`, hashable, unique); the payload becomes the `Node`.

**Rationale:** `UniqueQueue` dedups on `UMessage.id` via id-only equality. Today `id == ip`, which is non-unique post migration 003 — two distinct nodes sharing an IP (valid behind different jump hosts) would collapse to one queue entry and one would be silently dropped. `NodeId` is a `SERIAL PK`, so dedup on `NodeId` is correct: the same node re-enqueued across producer cycles is skipped (correct), distinct nodes with the same IP are both processed (correct).

**Alternative considered:** Keep `id == ip` and accept the dedup weakness. Rejected — silently dropping a deallocate for one of two same-IP nodes leaks a VM and a DB row.

### D3: `_deallocator_consumer` takes `Node` from `msg.payload`, drops `uow.nodes.get(ip)`

**Choice:**
```python
async def _deallocator_consumer(self, msg: UMessage[NodeId, Node]) -> None:
    node = msg.payload
    try:
        await deallocate_node(node, self._repository, self._clouds, self._uow_factory)
    except Exception as err:
        self._log.error("Deallocator error for node_id=%s ip=%s: %s", node.node_id, node.ip, err)
```

**Rationale:** The `Node` is already in the message. `deallocate_node` already accepts `Node` and internally handles SSH `contains`/`disconnect` (lines 56-57). The consumer no longer needs its own `uow.nodes.get(ip)` lookup or its own SSH `elif repo.contains(ip): disconnect(ip)` fallback — both are redundant with `deallocate_node`'s internals.

**Why the `elif` fallback disappears safely:** Today the `elif self._repository.contains(ip): await self._repository.disconnect(ip)` runs only when `node is None` (the DB row was already removed but the SSH session lingered). In the new flow `node` is never `None` (it came from the queue, sourced from `list_disabled()`), so this branch was unreachable on the happy path anyway. The lingering-session case is already covered by `deallocate_node`'s internal `if repository.contains(node.ip): await repository.disconnect(node.ip)` (lines 56-57), which runs unconditionally inside `deallocate_node` regardless of whether `node.cloud` is set. A node with `cloud=None` (static) would not reach the consumer because `deallocate_nodes` phase 2 filters `and node.cloud`, so the consumer only sees cloud nodes — but `deallocate_node`'s disconnect runs before the `if node.cloud:` guard, so even a hypothetical no-cloud node gets its session disconnected.

**Alternative considered:** Keep a defensive `if self._repository.contains(node.ip): await self._repository.disconnect(node.ip)` in the consumer as belt-and-suspenders. Rejected — it duplicates `deallocate_node`'s lines 56-57 and would double-disconnect (the second `disconnect` is a no-op pop from `_sessions`, but it's noise). `deallocate_node` owns SSH teardown; the consumer should not.

### D4: Remove the `"." in node.ip` post-filter

**Choice:** Phase 2 filter becomes `if node.ip not in busy_ips and node.cloud` (drop `and "." in node.ip`).

**Rationale:** The guard originated to exclude `prov||<md5hex>` tmp-node rows (no dots in the sentinel). After migration 003, tmp-nodes carry `ip=""` and are excluded at SQL level by `list_disabled.sql` (`WHERE ip <> ''`). The guard now protects against nothing real: all current cloud providers return ipv4 (dots present), and the schema column is `VARCHAR(15)` which cannot hold ipv6 or long hostnames. If ipv6/hostname support is ever added, that migration would re-introduce a deliberate filter — but it would be a new requirement, not this dead guard.

**Alternative considered:** Keep the guard as defense-in-depth. Rejected — it's dead code that misleads readers into thinking non-ipv4 disabled cloud nodes are a real case to handle. The `node.cloud` filter already excludes static nodes (the only non-cloud disabled nodes); tmp-nodes are SQL-excluded. Removing it clarifies intent.

### D5: Log lines add `node_id=%s` alongside `ip=%s` in `deallocate_nodes`

**Choice:** Internal log lines in `deallocate_nodes` (phase 1 disable, phase 2 collect) include both `node_id=%s` and `ip=%s`, matching the convention already applied to `deallocate_node` and `abandon_node` by the prior `node-id-keyed-mutators` changes.

**Rationale:** Correlation. `ip` alone is ambiguous post migration 003 (duplicates valid); `node_id` is unique. Keeping `ip` preserves continuity with existing log scraping. The consumer's error log adds `node_id=%s ip=%s` (was `ip=%s` only).

## Risks / Trade-offs

- **[Risk] `Node` object staleness between `list_disabled()` read and consumer processing.** The `Node` is read in the producer's `deallocate_nodes` call and consumed later; the DB row could be modified in between (e.g. re-enabled by an operator via `yasetnode`). → **Mitigation:** `deallocate_node` already handles this — `disable`/`remove` are idempotent-ish (disable on an already-disabled row is a no-op UPDATE; remove on a gone row is a 0-row DELETE no-op), and `clouds.deallocate` is cloud-SDK-dependent idempotent. The window is no wider than today's: today the consumer does `uow.nodes.get(ip)` and the row could change between that get and `deallocate_node`'s internal disable. Carrying the `Node` does not widen the race.

- **[Risk] `deallocate_node` raises after its internal `disconnect`.** SSH disconnect (lines 56-57) runs BEFORE `clouds.deallocate` (line 83), so the session is already torn down by the time the cloud call runs. If `clouds.deallocate` raises an unhandled exception (it doesn't — `deallocate_node` wraps `remove` in try/except but not `clouds.deallocate`; a `clouds.deallocate` raise would propagate to the consumer's `try/except Exception`), the SSH session is already gone; only the DB `remove` step could be skipped. → **Mitigation:** This is the **same** behavior as today — today's consumer also wraps `deallocate_node` in `try/except Exception` and a raise leaves the row disabled-but-not-removed. The monitor task manages any residual session lifecycle. No regression.

- **[Risk] Queue dedup on `NodeId` could skip a legitimate re-enqueue.** If the same node goes idle → gets disabled → gets re-enabled → goes idle again within one producer cycle window, the second enqueue would dedup against the first (still in queue). → **Mitigation:** This is the **same** semantics as today (dedup on ip would also skip it), and strictly better (ip dedup would also skip a *different* node sharing the IP). The producer re-runs every `_sleep_interval`; a node that cycles disabled→enabled→idle within one tick is not a realistic case.

- **[Trade-off] `_deallocate_q` type parameter changes from `UniqueQueue[str, str]` to `UniqueQueue[NodeId, Node]`.** This is a type-only change (runtime `UniqueQueue` is generic-erased), but the producer/consumer signatures move with it. Test mocks that built `UMessage("10.0.0.1", "10.0.0.1")` must update to `UMessage(NodeId(1), node)`. → **Mitigation:** Test updates are mechanical and called out in the impact list.

## Migration Plan

No schema migration. No config change. No public API change. The change is internal to `yascheduler.application` (two functions and one queue type param).

**Deploy:** standard `pip install` / `uv sync` — no migration step. The daemon restart picks up the new code; in-flight queue contents are in-memory and lost on restart anyway (no persistence).

**Rollback:** revert the code change. No data to roll back. In-flight deallocate state is rebuilt from DB on the next producer cycle (`list_disabled()` re-reads).

## Open Questions

(All resolved during design — see Decisions D1-D5. No outstanding open questions.)
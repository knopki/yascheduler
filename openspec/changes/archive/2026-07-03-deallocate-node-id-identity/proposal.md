## Why

The deallocate flow is the last ip-as-identity surface where `NodeId` already exists on both ends of the handoff but is thrown away and reconstructed. `deallocate_nodes` reads `Node` objects (carrying `node_id`) from `list_disabled()`, discards them to bare `ip` strings for the return value, enqueues `UMessage[ip, ip]`, and the consumer then does a `uow.nodes.get(ip)` round-trip lookup to recover the very `Node` it started with. This round-trip is wasted I/O and weakens the dedup key: `ip` is no longer `UNIQUE` post migration 003 (duplicate IPs are valid behind different jump hosts), so queue dedup on `ip` is strictly weaker than on `NodeId`.

The same function also carries a `"." in node.ip` post-filter that is dead code from the fake-ip era: before migration 003 it excluded `prov||<md5hex>` tmp-node rows (no dots); after migration 003 tmp-nodes carry `ip=""` and are excluded at SQL level by `list_disabled.sql` (`WHERE ip <> ''`), so the python guard now protects against nothing real (all providers return ipv4; the schema is `VARCHAR(15)` which cannot hold ipv6 or long hostnames). `remove-tmp-node-fake-ip` cleaned the SQL and repository layers but left this caller-side guard orphaned in `deallocate_nodes`. It is the same ip-as-identity debt, in the same function — cleaning it together.

Other ip-as-identity surfaces (SSH `_sessions` keyed by ip, `Task.allocated_ip` schema field, cloud `delete_node(host=ip)`) are deliberately **not** touched here: each is a distinct architectural surface (SSH lifecycle reordering, schema migration with 6-site cascade, cloud SDK contract) meriting its own change. This change picks the one surface where `NodeId` exists on both ends and the rekey is mechanical.

## What Changes

- `deallocate_nodes` return type changes from `list[str]` to `list[Node]`: phase 2 returns the `Node` objects it already holds (each carrying `node_id`) instead of `[node.ip for node in free_disabled_nodes]`.
- The `"." in node.ip` post-filter in `deallocate_nodes` phase 2 is removed (dead code from the fake-ip era; `list_disabled.sql` already excludes `ip=""` tmp rows at SQL level).
- `_deallocate_q` is rekeyed from `UniqueQueue[str, str]` to `UniqueQueue[NodeId, Node]`: the message id is `node.node_id` (strictly unique, unlike `ip`), the payload is the `Node`.
- `_deallocator_producer` yields `UMessage(node.node_id, node)` for each `Node` returned by `deallocate_nodes`.
- `_deallocator_consumer` takes the `Node` directly from `msg.payload` and **drops the `uow.nodes.get(ip)` round-trip lookup** that previously reconstructed the `Node` from `ip`. `deallocate_node(node, ...)` is called with the already-held `Node`.
- The consumer's SSH fallback path (`elif self._repository.contains(ip): await self._repository.disconnect(ip)`) is reworked: since the `Node` is never `None` in the new flow, the fallback semantics are redesigned to run the SSH `disconnect` unconditionally after `deallocate_node` (covering the case where `deallocate_node`'s internal `repository.contains`/`disconnect` was previously the only path). The exact fallback policy is settled in design.md.
- Internal log lines in `deallocate_nodes` and `_deallocator_consumer` add `node_id=%s` alongside `ip=%s`, matching the convention from the prior `node-id-keyed-mutators` changes (`abandon_node`, `deallocate_node`).
- No schema change. No new dependencies. No public-API change (`deallocate_nodes` and the orchestrator queues are internal).

## Capabilities

### New Capabilities

(None.)

### Modified Capabilities

- `use-cases`: The `DeallocateIdleNodes use case` requirement changes — `deallocate_nodes` returns `list[Node]` (was `list[str]`); the `"." in node.ip` post-filter is removed; phase 2 returns `Node` objects directly. Scenarios "Returns disabled node IPs" and "Idle cloud node disabled" are updated.
- `orchestrator`: The `Deallocate loop` requirement changes — `_deallocate_q` is `UniqueQueue[NodeId, Node]` (was `UniqueQueue[str, str]`); the consumer takes the `Node` from `msg.payload` without a `uow.nodes.get(ip)` round-trip; the SSH fallback path is reworked. Scenario "Deallocator consumer brackets cloud delete with UoWs" and "Cloud node idle too long" are updated.

## Impact

- **Code**: `yascheduler/application/deallocate_nodes.py` (return type, dead-filter removal, contract/log updates), `yascheduler/application/orchestrator.py` (`_deallocate_q` type param, `_deallocator_producer` yield, `_deallocator_consumer` body, fallback semantics).
- **Tests**: `tests/unit/test_application_use_cases.py` (`TestDeallocateNodes` — 2 tests assert on `Node`/`node_id` instead of ip strings), `tests/unit/test_application_orchestrator.py` (`TestDeallocatorConsumer` — 2 tests pass `UMessage(NodeId, Node)` and drop the `mock_uow.nodes.get` mock).
- **Specs**: `openspec/specs/use-cases/spec.md` (`DeallocateIdleNodes use case`), `openspec/specs/orchestrator/spec.md` (`Deallocate loop`).
- **GRACE-lite**: `docs/knowledge-graph.xml` (no new modules — `M-APPLICATION-DEALLOCATE` and `M-APPLICATION-ORCHESTRATOR` annotations updated), `MODULE_CONTRACT`/`MODULE_MAP`/`CHANGE_SUMMARY` in the two edited source files.
- **No schema migration** (no DB change). **No public API change** (`Yascheduler` facade, CLI commands, INI config, AiiDA plugin untouched). **No new dependencies.**
- **Surfaces deliberately not touched** (each is a separate architectural surface, not in this change's scope by its own design, not by inheriting another change's boundaries): SSH `MachineRepository` ip-keyed `_sessions` (requires connect/insert lifecycle reordering), `Task.allocated_ip` schema field (requires migration + 6-site cascade), `clouds.deallocate(cloud, ip)` cloud host argument (cloud SDK has no NodeId concept).
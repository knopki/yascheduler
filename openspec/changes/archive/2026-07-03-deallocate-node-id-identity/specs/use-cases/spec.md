## MODIFIED Requirements

### Requirement: DeallocateIdleNodes use case

The system SHALL provide a `deallocate_nodes` async function that disables
idle cloud nodes exceeding tolerance. The function SHALL accept `uow_factory`,
`config_clouds: Sequence[CloudConfig]`, and `idle_machines: dict[str, float]`
(IP -> free_since monotonic timestamp). It SHALL NOT accept `repository` or
`operations` (the per-node SSH/cloud teardown lives in `deallocate_node`).

The per-node wrapper `deallocate_node(node, repository, clouds, uow_factory)`
SHALL own the disable + remove bracketing around the pure
`clouds.deallocate(cloud, ip)` call. Ordering SHALL be preserved: `disable`
→ `delete_node` → `remove` across two short UoWs (disable before cloud
delete protects against allocator re-selection on failure; remove after
cloud delete ensures the DB row is only dropped once the VM is gone).

`deallocate_node` SHALL call `uow.nodes.disable(node.node_id)` and
`uow.nodes.remove(node.node_id)` (keying on `node_id`, not `ip`).
`clouds.deallocate(node.cloud, node.ip)` SHALL continue to take `ip`
(ip is the cloud host address, not node identity). `deallocate_node` SHALL
call `repository.contains(node.ip)` and `repository.disconnect(node.ip)`
BEFORE the `if node.cloud:` guard, so SSH teardown is owned by
`deallocate_node` and runs regardless of whether the node is a cloud node.

`deallocate_nodes` SHALL iterate `all_enabled_nodes.values()` and call
`uow.nodes.disable(node.node_id)` for each node to disable (the `Node` is
the dict value; the loop uses the value, not the ip key).

`deallocate_nodes` SHALL return `list[Node]` (was `list[str]`). Phase 2
(collect free disabled cloud nodes) SHALL return the `Node` objects it
reads from `uow.nodes.list_disabled()`, each carrying `node_id`, instead
of discarding them to bare `ip` strings. This eliminates the
`uow.nodes.get(ip)` round-trip lookup previously performed by the
orchestrator's `_deallocator_consumer` to reconstruct the `Node` from `ip`.

`deallocate_nodes` phase 2 SHALL filter disabled nodes by
`node.ip not in busy_ips and node.cloud`. The prior `"." in node.ip`
post-filter SHALL NOT be present — it was dead code from the fake-ip era
(`prov||<md5hex>` tmp-node sentinel had no dots; after migration 003 tmp-nodes
carry `ip=""` and are excluded at SQL level by `list_disabled.sql`
`WHERE ip <> ''`). Removing it does not change behavior because no disabled
cloud node with a non-ipv4 `ip` can exist in the current schema
(`VARCHAR(15)` cannot hold ipv6 or long hostnames, and all providers return
ipv4).

Internal log lines in both `deallocate_nodes` and `deallocate_node` SHALL
include both `node_id` and `ip` for correlation (matching the
`node-id-keyed-mutators` convention).

#### Scenario: Idle cloud node disabled
- **WHEN** `deallocate_nodes(uow_factory, config_clouds, idle_machines)` is called and an idle cloud node exceeds tolerance
- **THEN** the node is disabled via `uow.nodes.disable(node.node_id)` and committed; the `Node` (carrying `node_id`) is included in the returned `list[Node]` for orchestrator-level SSH disconnect and cloud deallocation

#### Scenario: Non-cloud node skipped
- **WHEN** a non-cloud node (`node.cloud is None`) is idle
- **THEN** it is not disabled in phase 1 (filtered by `node.cloud == ccfg.prefix`) and not included in the returned `list[Node]` (phase 2 filters `and node.cloud`)

#### Scenario: Returns disabled Node objects carrying node_id
- **WHEN** `deallocate_nodes(...)` completes
- **THEN** a `list[Node]` is returned (was `list[str]` of IPs); each `Node` carries its `node_id`, `ip`, `cloud`, and other fields, so the orchestrator's `_deallocator_consumer` can call `deallocate_node(node, ...)` directly without a `uow.nodes.get(ip)` round-trip lookup

#### Scenario: Phase 2 does not apply the dead ipv4-format filter
- **WHEN** `deallocate_nodes` phase 2 filters disabled nodes
- **THEN** the filter is `node.ip not in busy_ips and node.cloud` — the `"." in node.ip` guard is NOT present (dead code from the fake-ip era; `list_disabled.sql` `WHERE ip <> ''` already excludes tmp-node rows at SQL level)

#### Scenario: Deallocate node brackets cloud delete with disable+remove
- **WHEN** `deallocate_node(node, repository, clouds, uow_factory)` is called for a cloud node
- **THEN** the node's SSH session is disconnected via `repository.contains(node.ip)` + `repository.disconnect(node.ip)` (before the `if node.cloud:` guard), then the node is disabled via `uow.nodes.disable(node.node_id)` and committed, then `clouds.deallocate(node.cloud, node.ip)` is called, then the node is removed via `uow.nodes.remove(node.node_id)` and committed

#### Scenario: Internal logs include node_id and ip
- **WHEN** `deallocate_node` or `deallocate_nodes` logs any line
- **THEN** the line includes both `node_id=%s` and `ip=%s` fields
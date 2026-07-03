## MODIFIED Requirements

### Requirement: Deallocate loop

The system SHALL identify idle cloud nodes via UoW, call `deallocate_nodes`
to disable them, then handle SSH disconnect and cloud deallocation for
returned nodes via `MachineRepository` and `CloudProvisioner`. The
`_deallocator_consumer` SHALL call
`deallocate_node(node, repository, clouds, uow_factory)` directly with the
`Node` taken from `msg.payload` — it SHALL NOT open a UoW to read the node
via `uow.nodes.get(ip)` (the `Node` is already carried in the queue message,
eliminating the round-trip lookup). `deallocate_node` performs SSH
disconnect + disable + cloud delete + remove in two short UoWs bracketing
the pure cloud call. The orchestrator SHALL use `repository.list_connected()`
instead of `gateway.items()` for iterating connected machines.

The `_deallocate_q` queue SHALL be typed `UniqueQueue[NodeId, Node]`
(was `UniqueQueue[str, str]`). The producer SHALL yield
`UMessage(node.node_id, node)` for each `Node` returned by `deallocate_nodes`
— the message id is `node.node_id` (a `NodeId`, strictly unique `SERIAL PK`),
the payload is the `Node`. This rekeys the dedup from `ip` (non-unique post
migration 003 — duplicate IPs are valid behind different jump hosts) to
`NodeId` (strictly unique), so two distinct nodes sharing an IP are both
processed rather than one being silently dropped.

The `_deallocator_consumer` SHALL NOT perform its own SSH
`elif self._repository.contains(ip): await self._repository.disconnect(ip)`
fallback. SSH teardown is owned by `deallocate_node` (which calls
`repository.contains(node.ip)` + `repository.disconnect(node.ip)` internally
before the `if node.cloud:` guard). The consumer SHALL wrap
`deallocate_node` in a `try/except Exception` that logs `node_id`, `ip`, and
the error and continues (the worker-resilience wrapper in
`_create_producer_consumers` already catches consumer exceptions, but the
deallocator consumer keeps its own explicit error log with `node_id`/`ip`
fields for correlation, matching the prior behavior).

#### Scenario: Cloud node idle too long
- **WHEN** a cloud node has been free longer than `idle_tolerance` seconds
- **THEN** `deallocate_nodes` disables the node in DB via `uow.nodes.disable(node.node_id)` and returns the `Node` (carrying `node_id`) for SSH cleanup and cloud deletion

#### Scenario: Deallocator uses list_connected
- **WHEN** `_deallocator_producer` iterates connected machines to build `idle_machines`
- **THEN** it uses `repository.list_connected()` and accesses `session.machine.ip` (and `session.machine.free_since`) directly

#### Scenario: Deallocator queue is keyed on NodeId
- **WHEN** `_deallocator_producer` enqueues disabled nodes
- **THEN** it yields `UMessage(node.node_id, node)` where `node.node_id` is a `NodeId` (the queue dedup key) and `node` is the full `Node` (the payload); the queue is `UniqueQueue[NodeId, Node]`

#### Scenario: Deallocator consumer takes Node from payload without DB lookup
- **WHEN** `_deallocator_consumer` processes a disabled node message
- **THEN** it takes `node = msg.payload` directly and calls `deallocate_node(node, self._repository, self._clouds, self._uow_factory)` — it SHALL NOT call `uow.nodes.get(ip)` to reconstruct the `Node`; the `Node` is already carried in the message

#### Scenario: Deallocator consumer does not duplicate SSH teardown
- **WHEN** `_deallocator_consumer` processes a node
- **THEN** it SHALL NOT call `self._repository.contains(node.ip)` or `self._repository.disconnect(node.ip)` directly; SSH teardown is owned by `deallocate_node`'s internal `repository.contains(node.ip)` + `repository.disconnect(node.ip)` calls (which run before the `if node.cloud:` guard)

#### Scenario: Deallocator consumer logs node_id and ip on error
- **WHEN** `deallocate_node(node, ...)` raises an `Exception` inside `_deallocator_consumer`
- **THEN** the consumer's `except Exception` block logs `node_id=%s ip=%s err=%s` (was `ip=%s err=%s` only) and the worker continues processing subsequent messages
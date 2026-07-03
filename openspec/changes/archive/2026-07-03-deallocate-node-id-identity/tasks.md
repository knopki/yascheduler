## 1. Source — `deallocate_nodes` return type and dead-filter removal

- [x] 1.1 Change `deallocate_nodes` return type annotation from `list[str]` to `list[Node]` (signature line 130)
- [x] 1.2 Update `START_CONTRACT: deallocate_nodes` OUTPUTS from `list[str]` to `list[Node]` and PURPOSE to "return Node objects" (contract block lines 115-125)
- [x] 1.3 Remove `and "." in node.ip` from the phase-2 filter (line 159) — filter becomes `if node.ip not in busy_ips and node.cloud`
- [x] 1.4 Change phase-2 return from `[node.ip for node in free_disabled_nodes]` to `free_disabled_nodes` (line 161) — returns the `Node` objects directly
- [x] 1.5 Add `node_id=%s` alongside `ip=%s` in phase-1 disable log lines (the disable loop, around lines 148-151) matching the `deallocate_node` log convention
- [x] 1.6 Update `START_MODULE_CONTRACT` PURPOSE to mention "return Node objects" instead of "return IPs" (line 4)
- [x] 1.7 Update `START_MODULE_MAP` `deallocate_nodes` description from "return IPs for VM deletion" to "return Node objects for VM deletion" (line 12)
- [x] 1.8 Update `START_CHANGE_SUMMARY` LAST_CHANGE with a v4.6.0 entry describing the return-type change, dead-filter removal, and NodeId-keyed queue (lines 15-16)

## 2. Source — orchestrator deallocate queue and consumer

- [x] 2.1 Change `self._deallocate_q` type from `UniqueQueue[str, str]` to `UniqueQueue[NodeId, Node]` (orchestrator.py line 162) — add `NodeId` to the domain import block at line 31-43 (it is NOT yet imported; only `TaskId` is — add `NodeId` alongside `TaskId`)
- [x] 2.2 Update `_deallocator_producer` (lines 523-547): change the `yield UMessage(ip, ip)` (line 546) to `yield UMessage(node.node_id, node)` where `node` comes from iterating `disabled_nodes` (the `list[Node]` returned by `deallocate_nodes`); update the variable name `disabled_ips` → `disabled_nodes` (line 539)
- [x] 2.3 Update `_deallocator_producer` `START_CONTRACT` OUTPUTS from `AsyncGenerator[UMessage[str, str], None]` to `AsyncGenerator[UMessage[NodeId, Node], None]` (lines 516-522)
- [x] 2.4 Rewrite `_deallocator_consumer` (lines 556-568): take `node = msg.payload` directly (drop `ip = msg.payload` and the `async with uow_factory() as uow: node = await uow.nodes.get(ip)` block); call `deallocate_node(node, self._repository, self._clouds, self._uow_factory)`; drop the `elif self._repository.contains(ip): await self._repository.disconnect(ip)` fallback branch (SSH teardown owned by `deallocate_node`); keep the `try/except Exception` wrap and update the error log to include `node_id=%s ip=%s` (was `ip=%s` only)
- [x] 2.5 Update `_deallocator_consumer` `START_CONTRACT` INPUTS from `UMessage[str, str]` to `UMessage[NodeId, Node]` and SIDE_EFFECTS to drop the "reads the node via UoW" wording (lines 549-555)
- [x] 2.6 Update `START_CHANGE_SUMMARY` LAST_CHANGE in orchestrator.py with a v6.9.0 entry describing the queue rekey and consumer simplification (lines 15-18)

## 3. Tests — `TestDeallocateNodes`

- [x] 3.1 `test_deallocate_nodes_disables_idle_cloud_nodes` (test_application_use_cases.py line 650): change `assert "10.0.0.1" in result` to assert that the returned list contains a `Node` with `node_id=NodeId(1)` and `ip="10.0.0.1"` (the Node is now the element, not a bare ip string)
- [x] 3.2 `test_deallocate_nodes_skips_non_cloud_nodes` (line 690): change `assert "10.0.0.1" not in result` to assert the returned list is empty (or contains no Node with `node_id=NodeId(1)`)
- [x] 3.3 Add `test_deallocate_nodes_returns_node_objects` — assert the return type is `list[Node]` and each element carries `node_id`, `ip`, `cloud` fields (proves D1)
- [x] 3.4 Add `test_deallocate_nodes_no_dot_filter` — construct a disabled cloud node with a valid ipv4 `ip` (no dots would have failed the old filter; the new filter passes it) and assert it is returned; optionally verify a `Node` with `ip=""` is excluded by SQL (mock `list_disabled` to return it and confirm it's filtered out by `node.cloud` being falsy OR by SQL — depending on test layer)

## 4. Tests — `TestDeallocatorConsumer`

- [x] 4.1 `test_calls_deallocate_node_with_uow_factory` (test_application_orchestrator.py line 602): construct `UMessage(NodeId(1), node)` instead of `UMessage("10.0.0.1", "10.0.0.1")`; drop the `mock_uow.nodes.get` mock and the `mock_uow.__aenter__`/`__aexit__` setup (no UoW opened by consumer anymore); assert `deallocate_node` is called with the `node` from the message payload directly
- [x] 4.2 `test_disconnects_when_node_not_found` (line 628): this test asserted the `elif repo.contains(ip): disconnect(ip)` fallback ran when `node is None`. In the new flow `node` is never None and the fallback is removed. Replace this test with `test_consumer_does_not_duplicate_ssh_teardown` — assert the consumer does NOT call `self._repository.contains` or `self._repository.disconnect` directly (those are owned by `deallocate_node`); patch `deallocate_node` and assert the repository methods are not called on `orch._repository`
- [x] 4.3 Add `test_consumer_logs_node_id_and_ip_on_error` — patch `deallocate_node` to raise an Exception, call the consumer, capture the log, assert both `node_id=%s` and `ip=%s` appear in the error log line (proves D5)
- [x] 4.4 Add `test_queue_dedup_on_node_id_not_ip` — enqueue two `UMessage` with different `NodeId` but the same `ip` (simulating duplicate IPs behind jump hosts); assert both are processed (not deduped to one) — this proves D2's dedup-strength claim concretely

## 5. GRACE-lite — knowledge graph and contracts

- [x] 5.1 Update `docs/knowledge-graph.xml`: `M-APPLICATION-DEALLOCATE` annotations — `fn-deallocate_nodes` PURPOSE update to mention "returns list[Node]"; `M-APPLICATION-ORCHESTRATOR` annotations — note the `_deallocate_q` NodeId-keyed queue
- [x] 5.2 Run `python3 scripts/grace_check.py` and confirm exit 0 (XML + source checks pass after contract updates in tasks 1.6-1.8 and 2.3-2.6)

## 6. Verification

- [x] 6.1 Run `uv run pytest -m unit` — all unit tests pass (including the 4 new/updated deallocate tests)
- [x] 6.2 Run `uv run pytest -m integration` — no integration regressions (deallocate flow not directly covered by integration tests, but smoke check)
- [x] 6.3 Run `uv run zuban check` — type checks pass (the `UniqueQueue[NodeId, Node]` retype and consumer signature change typecheck cleanly)
- [x] 6.4 Run `uv run ruff check .` and `uv run ruff format --check .` — lint/format pass
- [x] 6.5 Run `uv run lint-imports` — import layering unchanged (no new cross-layer imports introduced)
- [x] 6.6 Run `openspec validate --all --json` — all specs valid after the change
- [x] 6.7 Run GRACE-lite validation (task 5.2) — exit 0
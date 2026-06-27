## Why

The daemon does not auto-connect static operator-managed nodes (`yasetnode host`, `cloud=None`). After `yasetnode` inserts the `yascheduler_nodes` row and disconnects, the daemon never establishes a persistent SSH connection, so `allocate_task` never sees the node in `repository.list_free()` and tasks stay stuck in `TO_DO` forever. This is a regression of the basic scheduling scenario introduced by `fix-never-connected-node-leak` (commit `3c3f7e0`, task 4.7), which added an over-broad `n.cloud is not None` filter to `_connect_machine_producer` to keep static nodes out of the abandon path — but the filter also excluded them from the connect path. Two e2e tests mask the regression with a fake `cloud="e2e"` workaround.

## What Changes

- Remove the `n.cloud is not None` condition from `Orchestrator._connect_machine_producer` so static nodes are yielded to the connect-machine consumer like cloud nodes.
- Add a consumer-side guard in `_connect_machine_consumer`: on `MachineConnectionError` for `node.cloud is None`, log a warning and return early so static nodes retry indefinitely on every producer cycle without ever reaching `abandon_node` or accumulating entries in `_connect_failures`.
- Remove the `cloud="e2e"` workaround from `tests/e2e/test_full_cycle.py` and `tests/e2e/test_consume_retry.py` so both tests exercise the real static-node path (`cloud=None`).
- Flip the `TestConnectMachineProducerExcludesStaticNodes` unit test class to assert static nodes ARE yielded and ARE retried without abandon (renamed `TestConnectMachineProducerYieldsStaticNodes`), plus a new `test_static_node_past_grace_does_not_abandon` temporal guard.
- Update `openspec/specs/orchestrator/spec.md` Connect-machine requirement and scenarios to describe the new behavior (static nodes connected; static nodes retried without abandon; the 120s grace fallback applies to non-None unmatched clouds only).
- Update `docs/knowledge-graph.xml` `class-Orchestrator` annotation and the `M-APPLICATION-ORCHESTRATOR → M-APPLICATION-ABANDON-NODE` CrossLink to reflect that abandon applies to cloud nodes only (static nodes retried without abandon).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `orchestrator`: Connect-machine loop yields static (`cloud is None`) nodes for connection; static nodes are retried on SSH failure without ever entering the abandon path. The 120s `connect_grace` fallback is clarified to apply only to non-None unmatched cloud prefixes.

## Impact

- **Code**: `yascheduler/application/orchestrator.py` — `_connect_machine_producer` filter, `_connect_machine_consumer` early-return guard, GRACE-lite markup renames (`FILTER_CLOUD_ONLY` → `FILTER_NOT_CONNECTED`, new `STATIC_NODE_RETRY` block), MODULE_CONTRACT SCOPE and CHANGE_SUMMARY updates.
- **Tests**: `tests/unit/test_connect_machine_consumer.py` (class rewrite + new temporal test), `tests/e2e/test_full_cycle.py` (drop workaround), `tests/e2e/test_consume_retry.py` (drop workaround).
- **Specs**: `openspec/specs/orchestrator/spec.md` (Connect machine loop requirement + scenarios).
- **Knowledge graph**: `docs/knowledge-graph.xml` (annotation + CrossLink wording).
- **No changes**: `abandon_node` use case (existing `if node.cloud is not None: deallocate` guard retained as defense-in-depth), `_connect_grace_for` defensive `cloud is None → 120` (untouched, exercised only in unit tests), DB schema, CLI, INI, `allocate_task`, `consume_task`, `deallocate_nodes`.
- **No breaking changes** to public interfaces (CLI, `Yascheduler` API, INI, schema, AiiDA entrypoint).
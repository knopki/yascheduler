## Context

`yascheduler` schedules scientific calculation jobs on SSH machines and cloud-created nodes. The daemon's `Orchestrator._connect_machine_producer` is the sole owner of persistent SSH connections: it polls enabled nodes from `yascheduler_nodes` and connects them via `MachineGateway` so `allocate_task` (which selects machines via `repository.list_free()`, iterating only connected sessions) can dispatch TO_DO tasks.

`yasetnode host` (`entrypoints/cli/manage_node.py:_add_node`) connects, optionally sets up the node, inserts the Node row, and **disconnects in `finally`** — it does not hold a persistent connection. Static operator-managed nodes have `cloud=None`; cloud-provisioned nodes have a non-None cloud prefix.

Commit `3c3f7e0` (change `fix-never-connected-node-leak`, task 4.7) added `n.cloud is not None` to the producer's filter to keep static nodes out of the never-connected-node abandon path (so a transient SSH outage after a daemon restart would not silently delete an operator's node row via `abandon_node`). The filter was over-broad: it also excluded static nodes from the connect path. As a result the daemon never connects static nodes, `allocate_task` never sees them, and tasks targeting static nodes stay stuck in `TO_DO` forever. Two e2e tests mask the regression with a fake `cloud="e2e"` workaround (`tests/e2e/test_full_cycle.py:81-88`, `tests/e2e/test_consume_retry.py:76-82`).

The pre-`3c3f7e0` producer yielded all enabled nodes not in the gateway:
```python
new_nodes = [n for n in enabled_nodes if not self._gateway.contains(n.ip)]
```

## Goals / Non-Goals

**Goals:**
- Restore auto-connection of static nodes (`cloud=None`) by the daemon, as it behaved before `3c3f7e0`.
- Preserve the original intent of `fix-never-connected-node-leak` task 4.7: a static node must NEVER be auto-removed by `abandon_node`, even across daemon restarts or transient SSH outages.
- Remove the `cloud="e2e"` e2e workaround so the e2e suite exercises the real static-node production path.
- Keep the change minimal and free of new abstractions.

**Non-Goals:**
- Changing `abandon_node` use case behavior (its existing `if node.cloud is not None: deallocate` defensive guard stays).
- Changing `_connect_grace_for` (the `cloud is None → 120` defensive fallback stays as code; the spec language is tightened to say the 120s fallback applies to non-None unmatched clouds only, so the path is never reached on the production path for static nodes and is exercised only by unit tests).
- Changing DB schema, CLI, INI, `allocate_task`, `consume_task`, `deallocate_nodes`, or any public interface.
- Backfilling persistent connections from `yasetnode` (the CLI remains a setup-and-disconnect tool; the daemon owns persistence).
- Throttling the static-node retry log (warning-level is already an improvement over the pre-`3c3f7e0` error-level spam; a backoff is a separate concern).

## Decisions

### Decision 1: Guard in the consumer, not the producer (Variant A)

**Choice:** Remove `n.cloud is not None` from the producer; add an early-return guard in `_connect_machine_consumer` for `node.cloud is None` before the grace-check.

**Alternatives considered:**
- **Variant B** — remove the producer filter only; add an early-return `if node.cloud is None: return` at the top of `abandon_node`; leave the grace-check in the consumer as-is. **Rejected:** wrong abstraction layer (`abandon_node` is a cloud-VM-cleanup use case; making it handle static no-ops dilutes its purpose); the early-return guard in `abandon_node` would not fire for 2 minutes (120s grace window), so `_connect_failures` accumulates and `_connect_grace_for(None)` is called unnecessarily every cycle; and the diagnostic log fires only after 120s instead of on every retry.

**Rationale:** The consumer owns the connect-failure operational context (which exception, which node). "Static node + error → retry forever" is a consumer-level operational policy. Placing the guard before the grace-check means `_connect_failures` is never populated for static nodes and `_connect_grace_for(None)` is never called on the production path.

### Decision 2: Guard placement — before `CONNECT_GRACE_CHECK`, not after

**Choice:** The early-return sits at the top of `except MachineConnectionError:`, before the `START_BLOCK_CONNECT_GRACE_CHECK` block.

**Rationale:**
- `_connect_failures.setdefault(node.ip, ...)` (line 299) is never reached for static nodes → the timer never accumulates static IPs.
- `_connect_grace_for(node.cloud)` is never called for static nodes on the production path → the defensive 120s fallback stays a pure function exercised only by unit tests.
- The `_connect_failures.pop(node.ip, None)` on successful connect (line 294) remains a harmless no-op for static IPs (key never set).
- Infinite retry for static nodes is the ORIGINAL pre-`3c3f7e0` behavior (producer re-yielded, consumer logged and returned). Variant A restores it and adds the explicit abandon guard.

### Decision 3: `abandon_node` use case unchanged

**Choice:** Do not modify `abandon_node`. Its existing `if node.cloud is not None: try: await clouds.deallocate(...)` guard (line 57) stays as defense-in-depth.

**Rationale:** With Variant A the only call site (`_connect_machine_consumer`) never calls `abandon_node` for static nodes, so the defensive guard is unreachable on the production path but remains correct for any future caller. Adding an early-return guard to `abandon_node` for `cloud is None` is considered (review suggestion Issue 2) but rejected as out-of-scope: the use case's MODULE_CONTRACT says "clean up a cloud node" and the existing VM-delete guard prevents cloud-cleanup side effects; the DB-row-removal risk for a future caller is explicitly accepted and documented in the risk section. If a future caller needs static-node safety, that caller should guard, not the use case.

### Decision 4: Reversing task 4.7 is safe

**Choice:** Reversing the v6.2.1 producer filter is safe because the consumer-side guard fully covers task 4.7's intent.

**Rationale:** Task 4.7's goal was "static nodes never reach the abandon path." Variant A achieves the same intent with a narrower mechanism: the guard fires before grace-check, so `abandon_node` is structurally unreachable for static nodes. The over-broad producer filter had an unintended side effect (static nodes never connect) which broke the `yasetnode → daemon` handoff. The CHANGE_SUMMARY entry must explicitly justify the reversal.

## Risks / Trade-offs

- **[Retry log spam for down static nodes]** → Every `_sleep_interval` (default 10s) the consumer logs `[CONNECT_RETRY_STATIC]` at warning. This is an improvement over the pre-`3c3f7e0` behavior (which logged at error) and matches the operational intent (operator can see the node is unreachable). No backoff/throttle added (out of scope).
- **[`_await_first_machine` 30s timeout when only static nodes exist and all fail SSH]** → `_machine_connected_event` is not set → 30s timeout → allocate starts with no machines → tasks hang. This is the same failure mode as "cloud-only with all nodes failing SSH" and is NOT a Variant A regression — pre-Variant-A static nodes were never connected at all (worse). Variant A improves: a reachable static node now connects.
- **[Future caller of `abandon_node` with a static node would delete the DB row]** → Defense-in-depth: the existing VM-delete guard stays. Any future caller that needs static-node DB-row preservation should guard at the call site. Accepted as low risk (only one call site today).
- **[Jump-host lookup loop is dead for `cloud=None`]** → `for cloud in self._config_clouds: if cloud.prefix == node.cloud` never matches `None` (all DTO prefixes are non-None). Jump host falls back to `self._remote_defaults.jump_host`. Correct behavior — static nodes use the default jump host. No change needed.
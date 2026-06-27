## 1. Orchestrator code (Variant A)

- [x] 1.1 In `yascheduler/application/orchestrator.py` `_connect_machine_producer`, remove `n.cloud is not None` from the list comprehension so the filter is `[n for n in enabled_nodes if not self._repository.contains(n.ip)]`. Rename `START_BLOCK_FILTER_CLOUD_ONLY`/`END_BLOCK_FILTER_CLOUD_ONLY` → `START_BLOCK_FILTER_NOT_CONNECTED`/`END_BLOCK_FILTER_NOT_CONNECTED` and replace the block comment to describe the not-connected filter (drop the static-exclusion rationale).
- [x] 1.2 In `_connect_machine_consumer`, add a `START_BLOCK_STATIC_NODE_RETRY`/`END_BLOCK_STATIC_NODE_RETRY` block at the top of `except MachineConnectionError:` that early-returns for `node.cloud is None` with a `warning`-level `[Orchestrator][_connect_machine_consumer][CONNECT_RETRY_STATIC] ip=%s err=%s` log. Place it BEFORE `START_BLOCK_CONNECT_GRACE_CHECK` so `_connect_failures.setdefault` and `_connect_grace_for` are never reached for static nodes.
- [x] 1.3 Update the `MODULE_CONTRACT` SCOPE line (orchestrator.py:5): replace "static nodes are excluded from the abandon path" with "static nodes (cloud is None) are connected but retried indefinitely without abandon (consumer-side guard bypasses grace-check)". Bump `FILE VERSION` to `6.7.0`.
- [x] 1.4 Update `START_CHANGE_SUMMARY`: prepend `LAST_CHANGE: v6.7.0 - fix(orchestrator): connect static nodes (cloud=None) again; the v6.2.1 FILTER_CLOUD_ONLY producer filter (fix-never-connected-node-leak task 4.7) excluded static nodes from auto-connect, breaking the yasetnode → daemon handoff (static nodes persisted by _add_node are never reconnected by the daemon, tasks stuck in TO_DO). Replaced with a precise consumer-side guard before the grace-check that retries static nodes indefinitely without ever calling abandon_node. Same intent as task 4.7 (static never abandoned), narrower mechanism, restores pre-3c3f7e0 connectivity.` Demote the existing entry to `PREVIOUS_CHANGE:`.

## 2. Unit tests

- [x] 2.1 In `tests/unit/test_connect_machine_consumer.py`, rename `TestConnectMachineProducerExcludesStaticNodes` → `TestConnectMachineProducerYieldsStaticNodes`. Update the class docstring and the file-level MODULE_MAP entry (line 15) and CHANGE_SUMMARY (line 19) to describe the new contract (static nodes ARE yielded; never abandoned).
- [x] 2.2 Rewrite `test_static_node_not_yielded_to_consumer` → `test_static_node_yielded_to_consumer`: static (`cloud=None`) enabled node not in gateway → producer YIELDS it. Flip the assertion: `"10.0.0.9" in yielded_ips` (was `not in`). Keep the cloud-node assertion (`"10.0.0.10" in yielded_ips`).
- [x] 2.3 Keep `test_gateway_registered_static_node_not_yielded` unchanged (already in gateway → not re-yielded).
- [x] 2.4 Rewrite `test_static_node_never_reaches_abandon_even_past_grace` → `test_static_node_failure_retries_without_abandon`: drive `_connect_machine_consumer` directly with a static node + `MachineConnectionError` (patch `orchestrator.abandon_node` with `AsyncMock`). Assert `abandon_node` NOT called, `_connect_failures` does not contain the ip. Use `caplog` to assert `[CONNECT_RETRY_STATIC]` warning is emitted.
- [x] 2.5 Add `test_static_node_past_grace_does_not_abandon`: static node + `MachineConnectionError` + patched `time.monotonic` returning timestamps >120s apart (same pattern as `test_connect_failure_past_grace_triggers_abandon` in the grace-timer class). Assert `abandon_node` NOT called, DB row preserved (no `uow.nodes.remove` call), `_connect_failures` not populated.
- [x] 2.6 Verify `test_none_cloud_falls_back_to_120s_grace` (line 286) still passes unchanged — it tests `_connect_grace_for(None) == 120` as a pure function and must remain valid (defensive fallback).

## 3. E2E test workaround removal

- [x] 3.1 In `tests/e2e/test_full_cycle.py`, remove the `cloud="e2e"` argument from the `Node(...)` constructor (lines 81-88) so the node uses the default `cloud=None`. Delete the workaround comment block (lines 81-87). Update the file's CHANGE_SUMMARY with a `LAST_CHANGE` entry noting the workaround removal (reference this change).
- [x] 3.2 In `tests/e2e/test_consume_retry.py`, remove the `cloud="e2e"` argument (lines 76-82) and the workaround comment. Update CHANGE_SUMMARY.

## 4. Spec sync

- [x] 4.1 Sync the delta spec `openspec/changes/fix-static-node-connect-exclusion/specs/orchestrator/spec.md` into the main spec `openspec/specs/orchestrator/spec.md` (replace the "Connect machine loop" requirement block with the MODIFIED content). Run `openspec validate --all --json` and confirm exit 0.

## 5. Knowledge graph

- [x] 5.1 In `docs/knowledge-graph.xml`, update the `class-Orchestrator` annotation (line 527): "abandon never-connected nodes" → "abandon never-connected cloud nodes (static nodes retried without abandon)".
- [x] 5.2 Update the `CrossLink from="M-APPLICATION-ORCHESTRATOR" to="M-APPLICATION-ABANDON-NODE"` (line 1215): "delegates never-connected node cleanup when connect-grace window is exceeded" → "delegates never-connected cloud node cleanup when connect-grace window is exceeded (static nodes retried indefinitely without abandon)".

## 6. Verification

- [x] 6.1 Run `uv run pytest -m unit tests/unit/test_connect_machine_consumer.py tests/unit/test_abandon_node.py tests/unit/test_connect_grace.py` — all green.
- [x] 6.2 Run `uv run pytest -m integration tests/integration/test_never_connected_node_abandon.py` — green (uses `cloud="hetzner"`, unaffected).
- [x] 6.3 Run `uv run pytest -m e2e tests/e2e/test_full_cycle.py tests/e2e/test_consume_retry.py` — green with `cloud=None` (no workaround).
- [x] 6.4 Run static checks: `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` — all green.
- [x] 6.5 Run `python3 scripts/grace_check.py` — exit 0.
- [x] 6.6 Run `openspec validate --all --json` — exit 0.
- [x] 6.7 Audit: `rg "cloud is None" openspec/specs/` — confirm no other spec references the old static-exclusion contract besides the orchestrator spec (now updated).
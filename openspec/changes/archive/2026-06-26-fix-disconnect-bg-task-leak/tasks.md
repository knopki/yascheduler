## 1. Gateway data-structure change

- [x] 1.1 In `SSHMachineGateway.__init__`, change `self._bg_tasks: set[asyncio.Task]` to `self._bg_tasks: dict[str, asyncio.Task] = {}` and update the surrounding comment / MODULE_MAP entry accordingly
- [x] 1.2 Rewrite `start_occupancy_check(ip, config)` to (a) cancel any prior task registered for the same IP, (b) install `self._bg_tasks[ip] = task`, (c) attach a done-callback that pops `ip` only if `self._bg_tasks.get(ip) is task` (identity check protects re-registrations)
- [x] 1.3 Rewrite `disconnect(ip)` to `task = self._bg_tasks.pop(ip, None)` before the SSH close block, then `task.cancel()` + `await task` (swallowing `asyncio.CancelledError`) only when a task was returned
- [x] 1.4 Add structured log line `[SSHGateway][disconnect][CANCEL_BG] ip=%s` at the cancellation site; do not log when there was no monitor (matches existing `if state.conn._transport:` quiet path)
- [x] 1.5 Update `START_MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` blocks in `gateway.py` for the data-structure change; bump `VERSION` per repo convention

## 2. GRACE knowledge graph

- [x] 2.1 Update `M-SSH-GATEWAY` annotations in `docs/knowledge-graph.xml` only if the public surface changed (it should NOT — confirm and skip with a one-line note in the change summary); private attribute change alone requires no graph edit

## 3. Unit tests

- [x] 3.1 Migrate `tests/unit/test_ssh_gateway.py:856` from `list(gateway._bg_tasks)[0]` to `gateway._bg_tasks[ip]`
- [x] 3.2 Migrate any other `list(gateway._bg_tasks)` / set-based assertions in `tests/unit/test_ssh_gateway.py` (around lines 628, 662 if present) to dict-key access
- [x] 3.3 Add `test_disconnect_does_not_cancel_other_machines_monitors` to `TestOccupancy` (or `TestConnectionLifecycle`): connect A, B, C; `start_occupancy_check` on each; `await gateway.disconnect("B")`; assert A and C monitors are still alive (`not task.cancelled()`) and `"B"` is gone from both `_machines` and `_bg_tasks`
- [x] 3.4 Add `test_start_occupancy_check_replaces_prior_monitor`: call `start_occupancy_check(ip, engine)` twice for the same IP; assert the first task is cancelled and only the second remains under `_bg_tasks[ip]`
- [x] 3.5 Add `test_disconnect_unknown_ip_leaves_other_monitors_alive`: disconnect an IP that was never connected; assert all other monitors are untouched

## 4. Integration tests

- [x] 4.1 Migrate `tests/integration/test_ssh_gateway.py:516, 628, 662` set-based accesses to `gateway._bg_tasks[ip]`
- [x] 4.2 Add a multi-machine integration regression test mirroring 3.3 but exercising the real asyncssh path against the SSH testcontainer when two containers are available (skip gracefully if only one container is configured — keep the unit test as the primary guard)

## 5. Static checks and validation

- [x] 5.1 `uv run ruff check .` passes
- [x] 5.2 `uv run ruff format --check .` passes
- [x] 5.3 `uv run lint-imports` passes
- [x] 5.4 `uv run zuban check` passes
- [x] 5.5 `uv run pytest -m unit` passes (focused on `tests/unit/test_ssh_gateway.py`)
- [x] 5.6 `uv run pytest -m integration` passes against the SSH testcontainer
- [x] 5.7 `python3 scripts/grace_check.py` exits 0
- [x] 5.8 `openspec validate fix-disconnect-bg-task-leak --json` reports `valid: true`

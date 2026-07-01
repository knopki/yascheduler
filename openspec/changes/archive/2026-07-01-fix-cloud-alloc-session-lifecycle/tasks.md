## 1. GRACE artifacts

- [x] 1.1 Update `CHANGE_SUMMARY` in `yascheduler/application/allocate_task.py` (LAST_CHANGE entry for Fix A in `_find_free_machines` and Fix C in `_allocate_free_machine`)
- [x] 1.2 Update `CHANGE_SUMMARY` in `yascheduler/infra/cloud/manager.py` (LAST_CHANGE entry for Fix B in `CloudProvisionerImpl.allocate` and Fix D in `_setup_vm` CLOUD_INIT block)
- [x] 1.3 Update function contract for `_find_free_machines` (`START_CONTRACT`/`END_CONTRACT`) — INPUTS now include enabled-IP filter, SIDE_EFFECTS notes the additional `uow.nodes.list_enabled()` read, OUTPUTS clarify the enabled-gate invariant
- [x] 1.4 Update function contract for `_allocate_free_machine` — add note that per-session failures are isolated (try/except, log, continue) and do not propagate
- [x] 1.5 Update `_setup_vm` CLOUD_INIT block comment to note the error message now includes stdout
- [x] 1.6 Update `CloudProvisionerImpl.allocate` SETUP_VM block comment to note the disconnect on failure path
- [x] 1.7 Verify `docs/knowledge-graph.xml` needs no structural change (no new M-IDs, no new CrossLinks — confirm M-APPLICATION-ALLOCATION and M-CLOUD-PROVISIONER annotations unchanged); add no edits

## 2. Fix A — DB-enabled gate in `_find_free_machines`

- [x] 2.1 In `yascheduler/application/allocate_task.py`, modify `_find_free_machines` (lines ~159-174): inside the existing `async with uow_factory() as uow:` block, add `enabled_nodes = await uow.nodes.list_enabled()` and build `enabled_ips = {n.ip for n in enabled_nodes}`
- [x] 2.2 Change the list comprehension filter to `if s.machine.ip in enabled_ips and s.machine.ip not in busy_node_ips`
- [x] 2.3 Verify the UoW is closed before the list comprehension runs (move `busy_node_ips` and `enabled_ips` computation inside the `async with`, the filter outside — matches existing structure where `busy_node_ips` is built inside and used outside)

## 3. Fix B — Disconnect on setup failure in `CloudProvisionerImpl.allocate`

- [x] 3.1 In `yascheduler/infra/cloud/manager.py`, in the `CloudSetupError` `except` block of `allocate` (lines ~180-186): add `await self.machine_repository.disconnect(ip_addr)` as the first statement, before `await adapter.delete_node(...)`
- [x] 3.2 In the generic `Exception` `except` block (lines ~187-193): add `await self.machine_repository.disconnect(ip_addr)` as the first statement, before `await adapter.delete_node(...)` and before the `raise CloudSetupError(...)`

## 4. Fix C — Isolate per-session failures in `_allocate_free_machine`

- [x] 4.1 In `yascheduler/application/allocate_task.py`, modify `_allocate_free_machine` (lines ~185-210): wrap the `if await _try_start_on_machine(...): return True` in `try: ... except Exception as err:`
- [x] 4.2 In the `except` block: `logger.error("[AllocateTask][_allocate_free_machine][SESSION_FAILED] task_id=%s ip=%s err=%s", task.task_id, session.ip, err)` then `continue`
- [x] 4.3 Verify NO `repository.disconnect(session.ip)` is added in the except block (per design D3 — transient SSH failure does not imply dead session; monitor owns lifecycle)

## 5. Fix D — stdout in cloud-init error message

- [x] 5.1 In `yascheduler/infra/cloud/manager.py`, in the `_setup_vm` CLOUD_INIT block (lines ~327-331): change the `CloudSetupError` f-string to include `stdout={result.stdout}` alongside the existing `stderr={result.stderr}`

## 6. Unit tests — timing-aware fakes for registry-vs-DB desync

- [x] 6.1 Create `tests/unit/test_cloud_alloc_session_lifecycle.py` with FILE/VERSION/MODULE_CONTRACT headers per GRACE-lite
- [x] 6.2 Implement a fake `MachineRepository` whose `connect(ip)` registers a `MachineSession` with `state=FREE, free_since=now` in an internal `_sessions` dict BEFORE returning (mirrors `SSHMachineRepository.connect`); `list_free(platforms)` returns FREE sessions filtered by platform; `disconnect(ip)` pops from `_sessions`; `disconnect_all()` clears it
- [x] 6.3 Implement a fake `CloudProvisioner` whose `allocate(provider)` calls `machine_repository.connect(ip)` then either (a) on success flips a DB row to `enabled=TRUE` via the uow_factory and returns `Node(enabled=True)`, or (b) on a configured failure mode raises `CloudSetupError` WITHOUT flipping the DB row (mirrors `_setup_vm` failure)
- [x] 6.4 Implement a fake `AbstractUnitOfWork` (or reuse an existing in-memory UoW fake if one exists in the test suite — check `tests/unit/` for a reusable one) that tracks tasks and nodes with `list_by_status`, `list_enabled`, `save`, `commit`
- [x] 6.5 Test Fix A — "setup-in-flight session invisible to allocator": register a session via the fake repository's `connect`, do NOT flip the DB row to enabled, call `allocate_task` with a TO_DO task, assert the task is NOT allocated to that session (it proceeds to cloud branch or returns without dispatching)
- [x] 6.6 Test Fix A — "multiple workers do not pile on": two concurrent `allocate_task` calls, one setup-in-flight session (not enabled), assert neither dispatches to it
- [x] 6.7 Test Fix A — "enabled node allocatable after setup": register a session AND flip the DB row to enabled, call `allocate_task`, assert the task IS allocated to that session
- [x] 6.8 Test Fix A — "disabled-but-not-disconnected excluded": register a session, set the DB row to `enabled=FALSE`, call `allocate_task`, assert the session is excluded
- [x] 6.9 Test Fix B (CloudSetupError path) — "no stale session after failed setup": trigger the fake `CloudProvisioner` to raise `CloudSetupError` during `allocate`, call `allocate_task` (it reaches cloud branch, setup fails), assert the fake repository's `_sessions` is empty (disconnect was called) and `list_free()` returns `[]`
- [x] 6.10 Test Fix B (generic exception path) — "generic exception disconnects before deleting VM": trigger the fake `CloudProvisioner` to raise a non-`CloudSetupError` `Exception` during `allocate`, assert `machine_repository.disconnect(ip)` is still called before the cloud VM is deleted (covers the second `except Exception` block, symmetric to 6.9)
- [x] 6.11 Test Fix B (never-connected safe no-op) — "disconnect on never-connected IP is safe": trigger the fake `CloudProvisioner` to fail at `_connect_to_vm` (before `connect` registers a session), assert `allocate`'s `except` block calls `disconnect(ip)` on the absent IP without raising, and the cloud VM is still deleted (covers the design.md D2 risk mitigation)
- [x] 6.12 Test Fix B (success path no disconnect) — "success path does not disconnect": trigger the fake `CloudProvisioner` to succeed, call `allocate_task`, assert the session REMAINS registered in `_sessions` (disconnect was NOT called) — the orchestrator reuses the connection (negative assertion on disconnect call)
- [x] 6.13 Test Fix C — "stale session failure does not abort loop": populate the fake repository with one stale session (raises on `occupy` or `run`) and one healthy enabled session, call `allocate_task`, assert the allocator logs the failure for the stale session and successfully allocates to the healthy one
- [x] 6.14 Test Fix C — "cloud branch reached when all free sessions fail": populate the fake repository with only a stale/unreachable session, call `allocate_task`, assert the cloud branch is reached (the fake `CloudProvisioner.allocate` is invoked) and the task is not left spinning in TO_DO
- [x] 6.15 Test Fix D — "cloud-init error contains stdout": call `_setup_vm` (or the CLOUD_INIT block path via the fake) with a fake `result` where `exit_code=2`, `stdout="status: error"`, `stderr=""`, assert the raised `CloudSetupError` message contains `stdout=status: error`
- [x] 6.16 Test Fix D — "timeout message unchanged": trigger the `asyncio.TimeoutError` path in the CLOUD_INIT block (fake `result` never returns, or `wait_for` times out via the fake adapter's `create_node_timeout`), assert the raised `CloudSetupError` message is `cloud-init status --wait timed out on {ip} after {timeout}s` (the timeout branch does not read `result.stdout`/`result.stderr`)
- [x] 6.17 Verify all new tests are marked `@pytest.mark.unit` and discoverable by `uv run pytest -m unit`

## 7. Validation

- [x] 7.1 Run `uv run pytest -m unit` — all unit tests pass (existing + new)
- [x] 7.2 Run `uv run pytest -m integration` — no regression (integration tests should be unaffected; no DB/SSH/cluster-flow change)
- [x] 7.3 Run `uv run ruff check .` and `uv run ruff format --check .` — clean
- [x] 7.4 Run `uv run lint-imports` — clean
- [x] 7.5 Run `python3 scripts/grace_check.py` — GRACE-lite validation passes (contracts, anchors, graph consistent with the CHANGE_SUMMARY bumps)
- [x] 7.6 Run `openspec validate --all --json` — spec validation passes (delta specs are well-formed)
- [x] 7.7 Confirm `openspec status --change "fix-cloud-alloc-session-lifecycle"` reports all artifacts done
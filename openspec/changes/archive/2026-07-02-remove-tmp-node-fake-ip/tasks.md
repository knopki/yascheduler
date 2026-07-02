## 1. DB migration + schema.sql snapshot (run first — establishes the new ground state)

- [x] 1.1 Create `yascheduler/infra/persistence/sql/migrations/003_drop_tmp_node_fake_ip.sql` with `UPDATE yascheduler_nodes SET ip = '' WHERE ip LIKE 'prov%';` and `ALTER TABLE yascheduler_nodes DROP CONSTRAINT yascheduler_nodes_ip_key;`
- [x] 1.2 Bump `last_migration` CONSTANT in `yascheduler/infra/persistence/sql/schema.sql` from `'002'` to `'003'`
- [x] 1.3 Edit the `yascheduler_nodes` snapshot DDL in `schema.sql`: change `ip VARCHAR(15) UNIQUE` to `ip VARCHAR(15)` (drop the column-level `UNIQUE`)
- [x] 1.4 Add unit test asserting `schema.sql` `last_migration` CONSTANT matches the latest migration file's `prefix_id` (`003`); if a prior test already asserts this, update its expected value (verify in `tests/unit/`)

## 2. Domain model — NewNode defaults (no Optional ripple)

- [x] 2.1 Update `docs/knowledge-graph.xml` `M-DOMAIN-MODEL` annotations for `NewNode` (note the new `ip=""`, `ncpus=0` defaults) and bump the module VERSION
- [x] 2.2 Edit `yascheduler/domain/model.py` `NewNode` dataclass: add `ip: str = ""` and `ncpus: int = 0` defaults (field order unchanged — ip and ncpus still first, now with defaults); update the `NewNode` MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY + the `START_CONTRACT: NewNode` block (INPUTS reflect defaults)
- [x] 2.3 Add/adjust `tests/unit/test_domain_model.py` (or wherever NewNode is tested) scenarios: `NewNode(cloud="aws", enabled=False)` yields `ip == ""`, `ncpus == 0`, `username == "root"`, `port == 22`; `NewNode(ip="10.0.0.1", ncpus=4)` still works (explicit overrides defaults)

## 3. Domain port — abolish add_tmp from the Protocol

- [x] 3.1 Update `docs/knowledge-graph.xml` `M-DOMAIN-PORTS` annotations: remove the `add_tmp` annotation, note `insert` as sole insertion path; bump module VERSION if the contract changed
- [x] 3.2 Edit `yascheduler/domain/ports.py` `NodeRepository` Protocol: remove the `async def add_tmp(self, cloud: str) -> str: ...` line; update the Protocol docstring (replace the "`add_tmp` ... unchanged ... reworking it is a deferred follow-up" sentence with the abolition rationale — `insert` is sole path, serves tmp via `NewNode(cloud=..., enabled=False)`); update MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY
- [x] 3.3 Update `tests/unit/test_domain_ports.py` `StubNodeRepository`: remove the `add_tmp` stub method (the Protocol no longer requires it); verify `isinstance(StubNodeRepository(), NodeRepository)` still holds structurally

## 4. PostgresNodeRepository — drop add_tmp, drop the two python post-filters

- [x] 4.1 Update `docs/knowledge-graph.xml` `M-PERSISTENCE` annotations: remove `add_tmp` annotation, update `list_enabled`/`list_disabled` annotation notes (python post-filters removed); bump module VERSION
- [x] 4.2 Edit `yascheduler/infra/persistence/postgres.py` `PostgresNodeRepository`: remove the `add_tmp` method (and its `START_CONTRACT: add_tmp` / `END_CONTRACT: add_tmp` block); update the class docstring if it mentions `add_tmp`
- [x] 4.3 Edit `PostgresNodeRepository.list_enabled`: remove the `if "." in r["ip"]` post-filter (return `[self._row_to_node(r) for r in rows]`); update the `START_CONTRACT: list_enabled` block (remove the "post-filtered for valid IPs" language)
- [x] 4.4 Edit `PostgresNodeRepository.list_disabled`: remove the `if "." in r["ip"]` post-filter (return `[self._row_to_node(r) for r in rows]`); update the `START_CONTRACT: list_disabled` block (filter is now in SQL, not python)
- [x] 4.5 Update `PostgresNodeRepository` MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY in `postgres.py` to reflect the removed method and the two removed post-filters

## 5. SQL files — list_disabled filter + delete insert_tmp.sql

- [x] 5.1 Edit `yascheduler/infra/persistence/sql/node/list_disabled.sql`: change `WHERE enabled = FALSE;` to `WHERE enabled = FALSE AND ip <> '';`
- [x] 5.2 Delete `yascheduler/infra/persistence/sql/node/insert_tmp.sql` (no remaining caller)
- [x] 5.3 Check `openspec/specs/postgres-persistence/spec.md` for `insert_tmp.sql` references in the SQL-file-layout requirement; note any inconsistency for archive reconciliation (no pre-archive edits to main specs — the delta spec overrides at archive time)

## 6. allocate_task.py — _TmpSelection + 5 helper signatures + outer body (GRACE top-down: contracts first)

- [x] 6.1 Update `docs/knowledge-graph.xml` `M-APPLICATION-ALLOCATE-TASK` annotations: update `_TmpSelection` (now carries `node_id`), remove any `add_tmp` reference, update `_cleanup_tmp_node_best_effort`/`_allocate_cloud_node`/`_persist_node_with_cleanup`/`_provision_and_persist` signatures (tmp_node_id); bump module VERSION
- [x] 6.2 Edit `yascheduler/application/allocate_task.py` `_TmpSelection` NamedTuple: replace `ip: str` field with `node_id: NodeId` (fields: `name: str`, `node_id: NodeId`); ensure `NodeId` is imported at the module top level (add to the existing `from yascheduler.domain import ...` line — `NamedTuple` resolves annotations via `typing.get_type_hints()` at class-creation time, so `NodeId` must be importable even with `from __future__ import annotations`); add/update `CHANGE_SUMMARY` entry for allocate_task module
- [x] 6.3 Edit `_select_and_insert_tmp`: replace `tmp_ip = await uow.nodes.add_tmp(selected_name)` with `tmp_node = await uow.nodes.insert(NewNode(cloud=selected_name, enabled=False))`; replace `return _TmpSelection(name=selected_name, ip=tmp_ip)` with `return _TmpSelection(name=selected_name, node_id=tmp_node.node_id)`; update the `START_CONTRACT: _select_and_insert_tmp` block (INPUTS/SIDE_EFFECTS reflect `insert` not `add_tmp`); add `NewNode` to imports if not already
- [x] 6.4 Edit `_cleanup_tmp_node_best_effort`: change signature `tmp_ip: str` → `tmp_node_id: NodeId`; remove the `uow.nodes.get(tmp_ip)` lookup and the `if node is not None:` branch; call `await uow.nodes.remove(tmp_node_id)` directly then `await uow.commit()`; update the `START_CONTRACT: _cleanup_tmp_node_best_effort` block + log markers (replace `tmp_ip=%s` with `tmp_node_id=%s` in the `[TMP_CLEANUP_FAILED]` log line)
- [x] 6.5 Edit `_allocate_cloud_node`: change signature `tmp_ip: str` → `tmp_node_id: NodeId`; update the `_cleanup_tmp_node_best_effort` call site to pass `tmp_node_id`; update the `START_CONTRACT: _allocate_cloud_node` block
- [x] 6.6 Edit `_persist_node_with_cleanup`: change signature `tmp_ip: str` → `tmp_node_id: NodeId`; remove the `tmp_node = await uow.nodes.get(tmp_ip)` and `if tmp_node is not None:` branch; call `await uow.nodes.remove(tmp_node_id)` directly after `await uow.nodes.insert(node)`; update the `START_CONTRACT: _persist_node_with_cleanup` block + log markers (`tmp_ip` → `tmp_node_id`)
- [x] 6.7 Edit `_provision_and_persist`: change signature `tmp_ip: str` → `tmp_node_id: NodeId`; thread `tmp_node_id` through to `_allocate_cloud_node` and `_persist_node_with_cleanup`; update the `START_CONTRACT: _provision_and_persist` block
- [x] 6.8 Edit `allocate_task` outer body: change `tmp_ip: str | None = None` → `tmp_node_id: NodeId | None = None`; change `selected.ip` → `selected.node_id` (where `selected` is the `_TmpSelection`); update the outer `finally` block's `_cleanup_tmp_node_best_effort` call to pass `tmp_node_id`; update the `START_CONTRACT: allocate_task` block (SIDE_EFFECTS no longer mention `add_tmp`)
- [x] 6.9 Update `allocate_task.py` MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY to reflect all signature + flow changes

## 7. Tests — update unit tests to the new contract

- [x] 7.1 `tests/unit/test_domain_ports.py`: confirm `StubNodeRepository.add_tmp` removed (task 3.3); verify no test asserts `add_tmp` exists on the Protocol
- [x] 7.2 `tests/unit/test_application_use_cases.py`: update tmp-cleanup test expectations — tmp insertion is `uow.nodes.insert(NewNode(cloud=..., enabled=False))` (not `add_tmp`); cleanup calls `uow.nodes.remove(tmp_node_id)` (NOT `get(tmp_ip)` then `remove(node.node_id)`); update mock assertions accordingly; add a scenario asserting a 0-row `remove(tmp_node_id)` is a no-op (idempotent cleanup)
- [x] 7.3 `tests/unit/test_application_events.py`: verify the `TaskAllocated`/`TaskFailed` event tests don't depend on the old `tmp_ip` plumbing; update if they reference `_TmpSelection.ip` or `add_tmp`
- [x] 7.4 `tests/unit/test_allocate_task_failure_modes.py`: update the cloud-fallback failure-mode tests (cloud-alloc-failed, persist-failed, allocator-unexpected) to assert cleanup uses `remove(tmp_node_id)` directly, not `get(tmp_ip)` + `remove(node.node_id)`
- [x] 7.5 `tests/unit/test_cloud_alloc_session_lifecycle.py`: verify the alloc session lifecycle test's expectations align with the new `_TmpSelection.node_id` + `insert`-based tmp insertion; update mock call assertions

## 8. Integration tests — real DB tmp-node lifecycle + migration 003

- [x] 8.1 `tests/integration/test_db_integration.py`: update the tmp-node lifecycle test to insert via `uow.nodes.insert(NewNode(cloud="aws", enabled=False))`, assert the row has `ip == ""` and `enabled == False` and `node_id` is set, then `uow.nodes.remove(node_id)` cleans up; remove any `add_tmp` assertions
- [x] 8.2 `tests/integration/test_db_integration.py`: add a migration-003 test — seed a row with `ip = 'provabc1234567'` (or any `prov...` value), run `apply_migrations` on a DB at migration `002`, assert the row's `ip` becomes `''` and the `yascheduler_nodes_ip_key` constraint is dropped (a duplicate `ip` insert of a real value into two rows now succeeds); use testcontainers Postgres
- [x] 8.3 `tests/integration/test_db_integration.py`: verify `list_enabled()` no longer python-post-filters (assert a row with `enabled=TRUE` and a real ip is returned; assert no enabled row has `ip=""` by the invariant); verify `list_disabled()` returns only `enabled=FALSE AND ip <> ''` rows (tmp rows with `ip=""` excluded at SQL level)

## 9. Static checks + spec validation (final gate before archive)

- [x] 9.1 Run `uv run ruff check .` and `uv run ruff format --check .` — fix any lint/format issues introduced
- [x] 9.2 Run `uv run lint-imports` — fix any import-order issues (e.g. `NewNode` import added to allocate_task.py)
- [x] 9.3 Run `uv run zuban check` — fix any type errors (verify `Node.ip: str` did NOT become `str | None` anywhere; verify `tmp_node_id: NodeId` annotations are consistent)
- [x] 9.4 Run `uv run pytest -m unit` — all unit tests pass
- [x] 9.5 Run `uv run pytest -m integration` — all integration tests pass (testcontainers Postgres + migration 003)
- [x] 9.6 Run `python3 scripts/grace_check.py` (and `--json`) — GRACE-lite validation passes (knowledge-graph.xml + source contract/anchor checks)
- [x] 9.7 Run `openspec validate --all --json` — spec validation passes after the change (the 4 delta specs are well-formed; the main specs are unchanged at this stage — they sync at archive)
- [x] 9.8 Grep the codebase for any remaining `add_tmp`, `insert_tmp`, `"." in r["ip"]`, `"." in node.ip` (in postgres.py only — the deallocate_nodes caller-side filter stays), `get(tmp_ip)`, `tmp_ip` references in `allocate_task.py` and confirm they are all gone (except the explicitly out-of-scope caller-side dot-filter in `deallocate_nodes.py`)
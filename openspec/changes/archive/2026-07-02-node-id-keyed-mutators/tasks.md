## 1. Domain Protocol — NodeRepository

- [x] 1.1 In `yascheduler/domain/ports.py`, change `NodeRepository.enable(ip: str) -> None` → `enable(node_id: NodeId) -> None`, `disable(ip: str) -> None` → `disable(node_id: NodeId) -> None`, `remove(ip: str) -> None` → `remove(node_id: NodeId) -> None`. `update(node: Node) -> None` signature unchanged.
- [x] 1.2 Update the `NodeRepository` Protocol docstring: replace the "All ip-keyed mutators (`get`, `enable`, `disable`, `remove`, `update`, `get_by_ips`) keep their ip keying" paragraph with the new keying statement (mutators `enable`/`disable`/`remove`/`update` key on `node_id`; lookups `get`/`get_by_ips`/`list_*` remain ip-keyed / unkeyed as a deferred non-goal).
- [x] 1.3 Update the `START_CONTRACT: NodeRepository` / `END_CONTRACT` block (if present) and `START_MODULE_MAP` entry in `ports.py` to reflect the new signatures.
- [x] 1.4 Add `START_CHANGE_SUMMARY` entry to `ports.py` noting the mutator rekeying.

## 2. SQL queries

- [x] 2.1 `yascheduler/infra/persistence/sql/node/enable.sql`: change `WHERE ip = :ip` → `WHERE node_id = :node_id`.
- [x] 2.2 `yascheduler/infra/persistence/sql/node/disable.sql`: change `WHERE ip = :ip` → `WHERE node_id = :node_id`.
- [x] 2.3 `yascheduler/infra/persistence/sql/node/remove.sql`: change `WHERE ip = :ip` → `WHERE node_id = :node_id`.
- [x] 2.4 `yascheduler/infra/persistence/sql/node/update.sql`: change `WHERE ip = :ip` → `WHERE node_id = :node_id`.

## 3. PostgresNodeRepository implementation

- [x] 3.1 In `yascheduler/infra/persistence/postgres.py`, change `enable(self, ip: str)` → `enable(self, node_id: NodeId)`, bind `_run(load_query("node/enable"), node_id=node_id.value)`. Update the `START_CONTRACT: enable` block.
- [x] 3.2 Change `disable(self, ip: str)` → `disable(self, node_id: NodeId)`, bind `node_id=node_id.value`. Update the contract block.
- [x] 3.3 Change `remove(self, ip: str)` → `remove(self, node_id: NodeId)`, bind `node_id=node_id.value`. Update the contract block.
- [x] 3.4 `update(self, node: Node)` — keep signature; change the `_run` call to pass `node_id=node.node_id.value` alongside the existing field params; the SQL `WHERE` now keys on `node_id`. Update the contract block.
- [x] 3.5 Update `MODULE_MAP` and `START_CHANGE_SUMMARY` in `postgres.py`.

## 4. Application call-sites — deallocate

- [x] 4.1 `yascheduler/application/deallocate_nodes.py` `deallocate_node`: change `uow.nodes.disable(node.ip)` → `uow.nodes.disable(node.node_id)`, `uow.nodes.remove(node.ip)` → `uow.nodes.remove(node.node_id)`. Add `node_id=%s` to all log lines alongside `ip=%s`.
- [x] 4.2 `deallocate_nodes` disable loop: today iterates `all_enabled_nodes.items()` building `nodes_to_disable: list[str]` from ip keys; switch to iterate `.values()` and call `uow.nodes.disable(node.node_id)` for each `Node` to disable.
- [x] 4.3 Update `START_CHANGE_SUMMARY` in `deallocate_nodes.py`.

## 5. Application call-site — abandon_node

- [x] 5.1 `yascheduler/application/abandon_node.py`: change `uow.nodes.remove(node.ip)` → `uow.nodes.remove(node.node_id)`. Add `node_id=%s` to all log lines alongside `ip=%s`.
- [x] 5.2 Update `START_CHANGE_SUMMARY` in `abandon_node.py`.

## 6. Application call-sites — allocate_task tmp-cleanup

- [x] 6.1 `yascheduler/application/allocate_task.py` `_cleanup_tmp_node_best_effort`: before `remove`, add `node = await uow.nodes.get(tmp_ip)`; if `node is not None`, `await uow.nodes.remove(node.node_id)`. Keep the best-effort `try/except` wrapper. Update the contract block.
- [x] 6.2 `_persist_node_with_cleanup` success path: same lookup pattern — `get(tmp_ip)` then `remove(node.node_id)` if found. Update the contract block.
- [x] 6.3 Update `START_CHANGE_SUMMARY` in `allocate_task.py`.

## 7. CLI manage_node

- [x] 7.1 `yascheduler/entrypoints/cli/manage_node.py` `_manage_node_async` validation UoW: on the `host_spec` path, resolve `Node` via `uow.nodes.get(target.host_spec.host)` (today calls `_get_by_ip` which already returns `Node | None`); on the `node_id` path, via `uow.nodes.get_by_id(target.node_id)`. Hold the resolved `Node` for dispatch.
- [x] 7.2 Change `_remove_node_hard(deps, ip: str)` → `_remove_node_hard(deps, node: Node)`. Inside: `uow.tasks.list_ids_by_ip_and_status(node.ip, TaskStatus.RUNNING)` (unchanged), `uow.nodes.remove(node.node_id)` (was `node.ip`), user-facing `print(f"Removed host from yascheduler: {node.ip}")` (ip stays).
- [x] 7.3 Change `_remove_node_soft(deps, ip: str)` → `_remove_node_soft(deps, node: Node)`. Inside: `uow.nodes.disable(node.node_id)` or `uow.nodes.remove(node.node_id)` depending on the RUNNING-tasks branch; `print(...)` uses `node.ip`.
- [x] 7.4 Update the dispatch in `_manage_node_async`: pass the resolved `Node` to the remove helpers (drop the `_remove_ip(target, resolved_ip)` indirection — the `Node` carries both `node_id` and `ip`).
- [x] 7.5 Update `START_CONTRACT` blocks on `_remove_node_hard`, `_remove_node_soft`, and the dispatch block; update `MODULE_MAP` and `START_CHANGE_SUMMARY`.
- [x] 7.6 Remove the now-dead `_get_by_ip` and `_remove_ip` helpers (their callers in the dispatch flow are replaced by direct `Node` resolution in 7.1/7.4).

## 8. Tests — update existing

- [x] 8.1 `tests/unit/test_domain_ports.py` `StubNodeRepository`: change `enable(self, ip: str)`, `disable(self, ip: str)`, `remove(self, ip: str)` → take `node_id: NodeId`. Bodies stay `pass`.
- [x] 8.2 `tests/unit/test_cli_manage_node.py`: update the 2 `disable.assert_called_once_with("10.0.0.1")` asserts to `disable.assert_called_once_with(<NodeId>)`. Update any `remove`/`disable` mock-call asserts that reference the ip string.
- [x] 8.3 `tests/unit/test_application_use_cases.py`: update the `disable` and `remove` asserts to expect `NodeId`.
- [x] 8.4 `tests/integration/test_db_integration.py`: `uow.nodes.enable("10.0.0.1")` / `disable("10.0.0.1")` → `enable(NodeId(...))` / `disable(NodeId(...))` using the same row's `node_id` (fetch it first via `get(ip)` or `list_all()`).

## 9. Tests — new coverage

- [x] 9.1 Add unit test: `_cleanup_tmp_node_best_effort` calls `uow.nodes.get(tmp_ip)` then `uow.nodes.remove(node.node_id)` when the node exists.
- [x] 9.2 Add unit test: `_cleanup_tmp_node_best_effort` skips `remove` when `get(tmp_ip)` returns `None` (row already gone); no exception raised.
- [x] 9.3 Add unit test: `_persist_node_with_cleanup` success path calls `get(tmp_ip)` then `remove(node.node_id)`.
- [x] 9.4 Add unit test: `manage_node` remove-by-host path resolves `Node` via `get(spec.host)` and passes it to the remove helper (helper receives `Node`, not `str`).

## 10. GRACE-lite artifacts

- [x] 10.1 Update `docs/knowledge-graph.xml`: `M-DOMAIN-PORTS` `<annotations>` for `fn-enable`, `fn-disable`, `fn-remove` (new `NodeId` param); `M-PERSISTENCE-POSTGRES` `<annotations>` for the four `PostgresNodeRepository` mutators.
- [x] 10.2 Run `python3 scripts/grace_check.py` — exit 0 required.

## 11. Verification

- [x] 11.1 `uv run pytest -m unit` — all green.
- [x] 11.2 `uv run pytest -m integration` — all green (requires testcontainers Postgres).
- [x] 11.3 `uv run ruff check .` and `uv run ruff format --check .` — clean.
- [x] 11.4 `uv run lint-imports` — clean.
- [x] 11.5 `openspec validate --all --json` — change artifacts valid (the pre-existing `cloud` spec failure is unrelated and out of scope).
- [x] 11.6 Run `/opsx-verify` to confirm implementation matches the proposal.
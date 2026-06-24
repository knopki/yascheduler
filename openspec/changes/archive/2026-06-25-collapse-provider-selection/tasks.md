## 1. Domain model and ports

- [x] 1.1 `yascheduler/domain/model.py`: delete the `ProviderSelection` class (including the `# FIXME: very smelly object: remove?` and `# FIXME: username is useless` comments); update `START_MODULE_MAP` to remove the `ProviderSelection` line; bump `START_CHANGE_SUMMARY` with LAST_CHANGE entry referencing this change.
- [x] 1.2 `yascheduler/domain/ports.py`: in `CloudProvisioner` Protocol, change `select_provider(...) -> ProviderSelection | None` → `select_provider(...) -> str | None`; in `NodeRepository` Protocol, change `add_tmp(cloud: str, username: str) -> str` → `add_tmp(cloud: str) -> str`; remove the `ProviderSelection` import; update the file's `START_CHANGE_SUMMARY`. (Note: `CloudProvisioner` is a Protocol with bare stubs — there is no per-method `START_CONTRACT` block to update; the signature flip in the stub is the contract change.)
- [x] 1.3 `yascheduler/domain/__init__.py`: remove `ProviderSelection` from `__all__` and from the import block; update `START_MODULE_MAP` and `START_CHANGE_SUMMARY`.

## 2. Infrastructure — cloud provisioner

- [x] 2.1 `yascheduler/infra/cloud/manager.py`: remove the `ProviderSelection` import from `yascheduler.domain`; rewrite `CloudProvisionerImpl.select_provider` body to return `adapter.name` directly (delete `config = self.configs[adapter.name]` and `return ProviderSelection(name=adapter.name, username=config.username)`; replace with `return adapter.name`); update the `START_CONTRACT: CloudProvisionerImpl.select_provider` PURPOSE (drop "wrap result in ProviderSelection") and OUTPUTS to `str | None`; bump `START_CHANGE_SUMMARY`.

## 3. Infrastructure — persistence

- [x] 3.1 `yascheduler/infra/persistence/sql/node/insert_tmp.sql`: change `INSERT INTO yascheduler_nodes (ip, enabled, cloud, username) VALUES ('prov' || SUBSTR(MD5(RANDOM()::TEXT), 0, 11), FALSE, :cloud, :username) RETURNING ip;` → `INSERT INTO yascheduler_nodes (ip, enabled, cloud) VALUES ('prov' || SUBSTR(MD5(RANDOM()::TEXT), 0, 11), FALSE, :cloud) RETURNING ip;` (drop `username` column and `:username` bind; the DB `DEFAULT 'root'` covers it).
- [x] 3.2 `yascheduler/infra/persistence/postgres.py`: change `async def add_tmp(self, cloud: str, username: str = "root") -> str:` → `async def add_tmp(self, cloud: str) -> str:`; change the `_run` call from `load_query("node/insert_tmp"), cloud=cloud, username=username` → `load_query("node/insert_tmp"), cloud=cloud`; update the `START_CONTRACT: add_tmp` INPUTS to `{ cloud: str }` and SIDE_EFFECTS prose; bump `START_CHANGE_SUMMARY`.

## 4. Application — allocate task

- [x] 4.1 `yascheduler/application/allocate_task.py`: in `_select_and_insert_tmp`, change `selected_name = selection.name` → `selected_name = selection`; change `tmp_ip = await uow.nodes.add_tmp(selected_name, selection.username)` → `tmp_ip = await uow.nodes.add_tmp(selected_name)`; remove any `ProviderSelection` import if present; update the `_select_and_insert_tmp` contract INPUTS/OUTPUTS prose if it references `selection.name`/`selection.username`; bump `START_CHANGE_SUMMARY`.

## 5. GRACE knowledge graph

- [x] 5.1 `docs/knowledge-graph.xml`: remove the `<export-ProviderSelection ... />` annotation (in **M-DOMAIN**, the `domain/__init__.py` re-export block).
- [x] 5.2 `docs/knowledge-graph.xml`: remove the `<type-ProviderSelection ... />` annotation (in **M-DOMAIN-MODEL**).
- [x] 5.3 `docs/knowledge-graph.xml`: update the `<class-CloudProvisioner ...>` annotation in M-DOMAIN-PORTS to reference `select_provider(...) -> str | None` instead of `... -> ProviderSelection | None`.
- [x] 5.4 `docs/knowledge-graph.xml`: update the `<fn-select_provider PURPOSE="...">` annotation in M-CLOUD-PROVISIONER to reference `str | None` instead of `ProviderSelection | None`.

## 6. Unit tests

- [x] 6.1 `tests/unit/test_domain_model.py`: delete the `TestProviderSelection` class entirely (the type no longer exists; nothing to migrate the tests to); remove the `ProviderSelection` import; remove the `TestProviderSelection` line from `START_MODULE_MAP`; bump `START_CHANGE_SUMMARY`.
- [x] 6.2 `tests/unit/test_domain_ports.py`: remove `ProviderSelection` import; update the `CloudProvisioner` Protocol stub's `select_provider` return type to `str | None`; update any `NodeRepository.add_tmp` stub signature to drop `username`; update assertions that checked `ProviderSelection` to assert `str`; bump `START_CHANGE_SUMMARY`.
- [x] 6.3 `tests/unit/test_cloud_provisioner_impl.py`: remove `ProviderSelection` import; change the `select_provider` test — rename method `test_returns_provider_selection_when_capacity_available` → `test_returns_provider_name_when_capacity_available`, rewrite docstring from "Returns ProviderSelection..." → "Returns provider name string...", replace `assert isinstance(result, ProviderSelection)` + `assert result.name == "provider"` + `assert result.username == "root"` with `assert result == "provider"` (drop the dead `.name`/`.username` assertions); update any construction `ProviderSelection(name=..., username=...)` → string literal; bump `START_CHANGE_SUMMARY`.
- [x] 6.4 `tests/unit/test_application_use_cases.py`: remove `ProviderSelection` import; replace `ProviderSelection(name="aws", username="root")` constructions (lines ~313, ~391) with the string `"aws"`; update assertions that read `selection.name`/`selection.username` to use the string directly; bump `START_CHANGE_SUMMARY`.
- [x] 6.5 `tests/unit/test_allocate_task_failure_modes.py`: remove `ProviderSelection` import; replace `ProviderSelection(name="aws", username="root")` constructions (lines ~121, ~160, ~211, ~260) with `"aws"`; update the `_make_clouds` helper signature from `selection: ProviderSelection` → `selection: str` and any `selection.name`/`selection.username` access; bump `START_CHANGE_SUMMARY`.

## 7. Integration tests

- [x] 7.1 `tests/integration/test_persistence_adapter.py`: change `await repo.add_tmp("aws", "deployer")` → `await repo.add_tmp("aws")`; flip the assertion `n.username == "deployer"` → `n.username == "root"` (the row now falls back to the DB default); bump `START_CHANGE_SUMMARY`.
- [x] 7.2 `tests/integration/test_db_integration.py`: change `await uow.nodes.add_tmp("azure", "root")` → `await uow.nodes.add_tmp("azure")` (the assertion already uses `"root"` and remains correct); bump `START_CHANGE_SUMMARY`.

## 8. Static checks and validation

- [x] 8.1 Run `uv run zuban check` — must pass with no `ProviderSelection`-related errors.
- [x] 8.2 Run `uv run ruff check .` and `uv run ruff format --check .` — must pass.
- [x] 8.3 Run `uv run lint-imports` — must pass (verify no orphaned `ProviderSelection` imports remain).
- [x] 8.4 Run `openspec validate --all --json` — must report all passed (33/33 or equivalent).
- [x] 8.5 Run `python3 scripts/grace_check.py` — must exit 0 (knowledge-graph consistency after annotation removals).

## 9. Test runs

- [x] 9.1 Run `uv run pytest -m unit` — all unit tests pass; in particular `test_domain_model.py` no longer references `ProviderSelection`, `test_cloud_provisioner_impl.py` asserts string return, `test_allocate_task_failure_modes.py` passes with `"aws"` literal.
- [x] 9.2 Run `uv run pytest -m integration` — `test_persistence_adapter.py` and `test_db_integration.py` pass with the updated `add_tmp` signature and the `username="root"` default assertion.
- [x] 9.3 (If e2e available in this environment) Run `uv run pytest -m e2e` — full task lifecycle still passes; the allocate flow produces the same observable behavior (provider selected, tmp-node inserted with `username='root'`, real Node persisted with `username` from `ConfigCloud`).
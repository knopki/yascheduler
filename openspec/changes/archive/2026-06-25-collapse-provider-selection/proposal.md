## Why

`ProviderSelection(name, username)` carries dead data and wraps a single live field. `username` is written into a tmp-node row that is deleted before any reader touches it; the real `Node.username` is re-derived from `ConfigCloud` inside `_setup_vm`, independent of the selection. The author flagged both fields with FIXMEs (`very smelly object: remove?`, `username is useless`). A single-field value object that is immediately destructured at its only call site (`selected_name = selection.name`) earns no weight. The port `CloudProvisioner.select_provider` should return `str | None` (the selected provider name), matching the identity-string convention already used across `NodeRepository` (`add_tmp(cloud, str)`, `get(ip: str)`, `remove(ip: str)`).

## What Changes

- **BREAKING** `CloudProvisioner.select_provider` return type changes from `ProviderSelection | None` to `str | None`.
- **BREAKING** Remove `ProviderSelection` value object from `yascheduler.domain.model`.
- **BREAKING** Remove `ProviderSelection` re-export from `yascheduler.domain`.
- **BREAKING** `NodeRepository.add_tmp` drops the `username` parameter: `add_tmp(cloud: str) -> str`. The DB column `yascheduler_nodes.username` keeps its `DEFAULT 'root'` (schema unchanged).
- `node/insert_tmp.sql` stops binding `:username`; INSERT lists only `(ip, enabled, cloud)`.
- `CloudProvisionerImpl.select_provider` returns `adapter.name` instead of `ProviderSelection(name=..., username=...)`.
- `allocate_task` use case: `selected_name = selection.name` → `selected_name = selection`; `add_tmp(selected_name, selection.username)` → `add_tmp(selected_name)`.
- Update GRACE knowledge graph: remove `export-ProviderSelection` and `type-ProviderSelection` annotations; update `class-CloudProvisioner` and `fn-select_provider` annotations to reference `str | None`.
- Update tests: replace `ProviderSelection(name=..., username=...)` with string literals; update return-type assertions.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `domain-ports`: `CloudProvisioner.select_provider` return type `ProviderSelection | None` → `str | None`; remove `ProviderSelection` definition requirement; `NodeRepository.add_tmp` signature drops `username`; rewrite prose "gets a `ProviderSelection` (or `None`), then calls `allocate(selection.name)`" → "gets a `str | None`, then calls `allocate(selection)`"; rewrite the "Select provider returns ProviderSelection" scenario to assert string return.
- `cloud-provisioner`: `CloudProvisionerImpl.select_provider` returns `str | None`; rewrite the requirement paragraph referencing `select_provider(...) -> ProviderSelection | None` and wrapping into `ProviderSelection(name, username)`; rewrite the "Higher priority wins" scenario assertion `returns a ProviderSelection with name=...` → `returns the provider name string`; remove the "ProviderSelection is primitive-only" scenario (the type no longer exists).
- `use-cases`: `allocate_task` flow description updates — `select_provider` returns `str | None`; `add_tmp(selection.name, selection.username)` → `add_tmp(selection)`; `clouds.allocate(selection.name)` → `clouds.allocate(selection)` (three call sites: requirement body + two scenarios).
- `postgres-repositories`: `PostgresNodeRepository.add_tmp(cloud)` — drop `username` parameter; INSERT binds only `:cloud`; rewrite scenario wording "given cloud and username" → "given cloud, username defaults to 'root'".
- `test-db-integration`: `add_tmp(cloud, username)` test contract → `add_tmp(cloud)`.

## Impact

**Code:**
- `yascheduler/domain/model.py` — remove `ProviderSelection` class + its 2 FIXMEs.
- `yascheduler/domain/ports.py` — `CloudProvisioner.select_provider` signature, `NodeRepository.add_tmp` signature, remove `ProviderSelection` import.
- `yascheduler/domain/__init__.py` — remove `ProviderSelection` from `__all__` and imports.
- `yascheduler/infra/cloud/manager.py` — `select_provider` body returns `adapter.name`; contract block OUTPUTS updated.
- `yascheduler/infra/persistence/postgres.py` — `add_tmp` signature and call to `load_query`.
- `yascheduler/infra/persistence/sql/node/insert_tmp.sql` — drop `:username` bind and column.
- `yascheduler/application/allocate_task.py` — `selection.name` → `selection`, drop `selection.username` argument to `add_tmp`.
- `tests/unit/test_application_use_cases.py`, `tests/unit/test_domain_ports.py`, `tests/unit/test_allocate_task_failure_modes.py`, `tests/unit/test_cloud_provisioner_impl.py` — replace `ProviderSelection(name=..., username=...)` constructions with string literals; update return-type assertions.
- `tests/unit/test_domain_model.py` — delete `TestProviderSelection` (the type no longer exists; nothing to migrate the tests to).
- `tests/integration/test_persistence_adapter.py` — drop `username` argument from `add_tmp` call; flip the `n.username == "deployer"` assertion to `n.username == "root"` (the row now falls back to the DB default).
- `tests/integration/test_db_integration.py` — drop `username` argument from `add_tmp` call (its assertion already uses `"root"`).

**GRACE artifacts:**
- `docs/knowledge-graph.xml` — remove `export-ProviderSelection` (in M-DOMAIN, the `domain/__init__.py` re-export block), remove `type-ProviderSelection` (in M-DOMAIN-MODEL); update `class-CloudProvisioner` and `fn-select_provider` annotations in M-DOMAIN-PORTS / M-CLOUD-PROVISIONER to reference `str | None`.
- Module contracts and module maps touched by the above files get CHANGE_SUMMARY bumps.

**DB schema:** unchanged. `yascheduler_nodes.username` column and its `DEFAULT 'root'` remain — the tmp-row simply uses the default.

**Public API:** `class Yascheduler` public API, CLI commands, INI config, AiiDA entrypoint — untouched. The change is internal to ports and the allocate flow.

**No new dependencies.**
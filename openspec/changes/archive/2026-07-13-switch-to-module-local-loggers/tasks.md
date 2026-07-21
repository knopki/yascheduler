## 1. Remove `log` from collaborator constructors and bind module-local loggers

- [x] 1.1 `yascheduler/application/orchestrator.py` — remove `log: YaLogger` from `Orchestrator.__init__` params; remove `self._log = log`; add `logger = get_logger("M-APPLICATION-ORCHESTRATOR")` at module top; replace all `self._log` references with `logger`; update the `START_CONTRACT: Orchestrator.__init__` INPUTS block; remove the dead `import logging` (line 23) and the unused `from yascheduler.shared import get_logger` import (line 43, now used at module top)
- [x] 1.2 `yascheduler/infra/ssh/repository.py` — remove `log: YaLogger | None = None` from `SSHMachineRepository.__init__`; remove `self._log = log or get_logger("M-SSH-REPOSITORY")`; add `logger = get_logger("M-SSH-REPOSITORY")` at module top; replace `self._log` with `logger`
- [x] 1.3 `yascheduler/infra/ssh/session.py` — remove `log: YaLogger | None = None` from `SSHMachineSession.__init__`; remove `self._log = log or get_logger("M-SSH-SESSION")`; add `logger = get_logger("M-SSH-SESSION")` at module top; replace `self._log` with `logger`
- [x] 1.4 `yascheduler/infra/ssh/operations/deployment.py` — remove `log: logging.Logger` from `TaskDeployer.__init__`; remove `self._log = log`; add `logger = get_logger("M-SSH-OPS-DEPLOY")` at module top; replace `self._log` with `logger`; also drop `log: logging.Logger` from `_write_remote_file` and use the module-local `logger`
- [x] 1.5 `yascheduler/infra/ssh/operations/download.py` — remove `log: logging.Logger` from `OutputDownloader.__init__`; remove `self._log = log`; add `logger = get_logger("M-SSH-OPS-DOWNLOAD")` at module top; replace `self._log` with `logger`
- [x] 1.6 `yascheduler/infra/ssh/operations/occupancy.py` — remove `log: YaLogger` from `OccupancyChecker.__init__`; remove `self._log = log`; add `logger = get_logger("M-SSH-OPS-OCCUPANCY")` at module top; replace `self._log` with `logger`
- [x] 1.7 `yascheduler/infra/cloud/manager.py` — remove `log: YaLogger` field from `CloudProvisionerImpl` frozen dataclass; add `logger = get_logger("M-CLOUD-PROVISIONER")` at module top; replace all `self.log` references with `logger`; update the `START_CONTRACT: CloudProvisionerImpl` INPUTS block
- [x] 1.8 Verify outcome: `uv run zuban check` is green (no type errors from the removed fields/params); each module's `logger` is a `YaLogger` instance with the correct M-ID name

## 2. Remove `log` from cloud functions and Protocols

- [x] 2.1 `yascheduler/infra/cloud/protocols.py` — remove `log: logging.Logger` from `CreateNodeCallable.__call__` and `DeleteNodeCallable.__call__` signatures
- [x] 2.2 `yascheduler/infra/cloud/providers/az.py` — drop `log: logging.Logger` from `az_create_node`, `az_delete_node`, and all `az_*` helper functions that take `log`; add `logger = get_logger("M-CLOUD-PROVIDER-AZ")` at module top; replace `log` references with `logger`
- [x] 2.3 `yascheduler/infra/cloud/providers/hetzner.py` — drop `log` from `hetzner_create_node`, `hetzner_delete_node`; add `logger = get_logger("M-CLOUD-PROVIDER-HETZNER")` at module top; replace `log` with `logger`
- [x] 2.4 `yascheduler/infra/cloud/providers/upcloud.py` — drop `log` from `upcloud_create_node`, `upcloud_delete_node`, and helper functions; add `logger = get_logger("M-CLOUD-PROVIDER-UPCLOUD")` at module top; replace `log` with `logger`
- [x] 2.5 `yascheduler/infra/cloud/providers/vastai.py` — drop `log` from `vastai_create_node`, `vastai_delete_node`; add `logger = get_logger("M-CLOUD-PROVIDER-VASTAI")` at module top; replace `log` with `logger`
- [x] 2.6 `yascheduler/infra/cloud/ssh_keys.py` — drop `log: logging.Logger` from `get_or_create_ssh_key`; add `logger = get_logger("M-CLOUD-SSH-KEYS")` at module top; replace `log` with `logger`
- [x] 2.7 `yascheduler/infra/cloud/adapters.py` — drop `log: logging.Logger` from `resolve_adapter`; add `logger = get_logger("M-CLOUD-ADAPTERS-NEW")` at module top; replace `log` with `logger`
- [x] 2.8 `yascheduler/infra/cloud/provider_selection.py` — drop `log: YaLogger` from `select_provider_pure`; add `logger = get_logger("M-CLOUD-PROVIDER-SELECTION")` at module top; replace `log` with `logger`
- [x] 2.9 Verify outcome: `uv run zuban check` is green; all cloud provider modules compile; the Protocol implementations match the updated `CreateNodeCallable` / `DeleteNodeCallable` signatures

## 3. Remove `log` from migration runner helpers

- [x] 3.1 `yascheduler/infra/persistence/postgres_migrations.py` — drop `log: YaLogger` from `_apply_sql_migration`, `_apply_py_migration`, `_record_py_tracker`, `_run_py_migrate`; use the module-local `logger` (already bound at module top via `get_logger("M-PERSISTENCE-MIGRATIONS")`); update all call sites within the module
- [x] 3.2 Verify outcome: `uv run pytest -m unit -k migration` passes; `uv run pytest -m integration -k migration` passes

## 4. Update composition root and daemon core

- [x] 4.1 `yascheduler/entrypoints/di.py` — remove `log: YaLogger | None = None` parameter from `make_daemon`; remove the `if log is None: log = get_logger("M-APPLICATION-ORCHESTRATOR")` block; construct `SSHMachineRepository()` without `log=`; construct `TaskDeployer()`, `OutputDownloader()`, `OccupancyChecker()` without `log`; construct `CloudProvisionerImpl(...)` without `log=`; construct `Orchestrator(...)` without `log=`; update the `make_daemon` START_CONTRACT INPUTS block; remove the now-unused `from yascheduler.shared import YaLogger, get_logger` import if no other reference remains
- [x] 4.2 `yascheduler/entrypoints/cli/daemon_common.py` — change `await make_daemon(config, logger)` to `await make_daemon(config)` in `run_daemon`; `run_daemon` keeps its `logger` parameter for signal-handler messages
- [x] 4.3 Verify outcome: `uv run zuban check` is green; the daemon entry points (`daemonize`, `daemon_systemd`, `daemon_sysv`) still compile

## 5. Update tests

- [x] 5.1 Update all unit tests that construct the seven collaborator classes to drop the `log=` argument (search for `SSHMachineRepository(log=`, `TaskDeployer(log`, `OutputDownloader(log`, `OccupancyChecker(log`, `CloudProvisionerImpl(`, `Orchestrator(` in `tests/`)
- [x] 5.2 Update `tests/unit/test_provider_selection.py` — drop the `log: logging.Logger` fixture parameter from all eight test methods; the `select_provider_pure` calls no longer pass `log=`
- [x] 5.3 Update any e2e/integration tests that construct `make_daemon(config, log=...)` to call `make_daemon(config)` instead
- [x] 5.4 Update any test that asserts on `record.name == "yascheduler.M-APPLICATION-ORCHESTRATOR"` to filter by the correct M-ID for the module that now emits the record (e.g. `M-SSH-REPOSITORY` for repository-emitted records, `M-CLOUD-PROVISIONER` for cloud-provisioner-emitted records)
- [x] 5.5 Verify outcome: `uv run pytest -m unit` passes with all `log=` arguments removed from test constructions

## 6. Add guard test for no-injected-logger discipline

- [x] 6.1 Add `test_no_injected_logger_in_collaborator_constructors` to `tests/unit/test_log_scope_discipline.py` — AST-walk the seven collaborator modules (`orchestrator.py`, `ssh/repository.py`, `ssh/session.py`, `ssh/operations/deployment.py`, `ssh/operations/download.py`, `ssh/operations/occupancy.py`, `cloud/manager.py`), find each class's `__init__` method (or the class itself for frozen dataclasses), and fail if any parameter is named `log`
- [x] 6.2 Verify outcome: the guard test passes on the committed package; it fails loudly when a `log` parameter is reintroduced into any of the seven `__init__` methods

## 7. Update specs

- [x] 7.1 `openspec/changes/switch-to-module-local-loggers/specs/dependency-injection/spec.md` — MODIFIED: remove `log: Logger | None = None` from the `make_daemon` signature requirement; remove the `TaskDeployer(log=log)`, `OutputDownloader(log=log)`, `OccupancyChecker(log=log)` construction requirement; update scenarios
- [x] 7.2 `openspec/changes/switch-to-module-local-loggers/specs/cli/spec.md` — MODIFIED: change `make_daemon(config, logger)` to `make_daemon(config)` in the `run_daemon` requirement and the "daemon runtime error exits 1" scenario
- [x] 7.3 `openspec/changes/switch-to-module-local-loggers/specs/orchestrator/spec.md` — MODIFIED: add a scenario asserting the Orchestrator does NOT accept a `log` parameter
- [x] 7.4 `openspec/changes/switch-to-module-local-loggers/specs/testing-unit/spec.md` — MODIFIED: add the no-injected-logger guard test requirement
- [x] 7.5 Verify outcome: `openspec validate switch-to-module-local-loggers --json` passes

## 8. Update GRACE-lite markup

- [x] 8.1 Update `MODULE_CONTRACT` and `START_CONTRACT` INPUTS blocks in all affected modules to remove `log` from the documented inputs
- [x] 8.2 Update `CHANGE_SUMMARY` entries in all affected modules
- [x] 8.3 No `docs/knowledge-graph.xml` changes needed — no M-IDs are added or removed; only the binding site moves from composition root to module top

## 9. Validation and regression sweep

- [x] 9.1 Run `openspec validate switch-to-module-local-loggers --json` and confirm the change validates cleanly
- [x] 9.2 Run `uv run pytest -m unit` and confirm all unit tests pass (including the three guard tests and the updated construction callsites)
- [x] 9.3 Run `uv run pytest -m integration` and confirm no integration test regresses
- [x] 9.4 Run `uv run pytest -m e2e` (with testcontainers) and confirm the e2e suite passes with the updated logger names
- [x] 9.5 Run static checks: `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports`; fix any violations
- [x] 9.6 Run `python3 scripts/grace_check.py` and confirm the GRACE-lite XML + source checks pass
- [x] 9.7 Verify outcome: the full validation suite passes — `openspec validate`, `pytest -m unit`, `pytest -m integration`, `pytest -m e2e`, `zuban`, `ruff`, `lint-imports`, `grace_check.py` — confirming the migration is complete and log provenance is restored

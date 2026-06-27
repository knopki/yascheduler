# Tasks — decompose-ssh-gateway

Each task ≤ 2 hours. Ordered by dependency. Tasks reference the frozen
design decisions (D1–D9) and the frozen delta specs.

## 1. Platform layer migrations (no callers touched yet)

- [x] 1.1 Create `infra/ssh/platform/registry.py` with `ADAPTERS` (ordered list, moved verbatim from `helpers.py:72-89`). Add MODULE_CONTRACT, MODULE_MAP, CHANGE_SUMMARY. Update `infra/ssh/platform/__init__.py` re-exports to include `ADAPTERS`.
- [x] 1.2 Create `infra/ssh/platform/detect.py` with `_detect_platform` + `MAX_SESSIONS` (moved verbatim from `helpers.py:91,128-149`). Update `platform/__init__.py` re-exports.
- [x] 1.3 Create `infra/ssh/platform/paths.py` with `_init_paths` (moved verbatim from `helpers.py:156-171`). Update `platform/__init__.py` re-exports.
- [x] 1.4 Create `infra/ssh/platform/run_fn.py` with `make_run_fn(conn, adapter) -> OuterRunCallable` (moved verbatim from `gateway.py:1001-1018`, renamed from `_make_run_fn`, public). Add MODULE_CONTRACT/MAP/CHANGE_SUMMARY. Update `platform/__init__.py` re-exports.
- [x] 1.5 Run `uv run ruff check . && uv run ruff format --check .` — platform modules pass lint/format. Run `python3 scripts/grace_check.py --json` — platform graph entries valid.

## 2. Repository module

- [x] 2.1 Create `infra/ssh/repository.py` with MODULE_CONTRACT (purpose: connected-machine collection — registration, lifecycle, queries, state transitions, accessor getters, monitor mechanism), MODULE_MAP, CHANGE_SUMMARY. Add M-SSH-REPOSITORY stub entry to `docs/knowledge-graph.xml` (STATUS=partial).
- [x] 2.2 Move `_MachineState` dataclass from `gateway.py:152-163` to `repository.py` verbatim (frozen `@dataclass`, same fields).
- [x] 2.3 Move `MySSHClient`, `DEFAULT_CONN_OPTS`, `_resolve_tunnel` from `helpers.py` to `repository.py` verbatim.
- [x] 2.4 Implement `SSHMachineRepository.__init__(log)` — owns `_machines: dict[str, _MachineState]` and `_monitors: dict[str, asyncio.Task[None]]` (renamed from `_bg_tasks`).
- [x] 2.5 Implement connection lifecycle: `_open_connection`, `connect` (two-method pattern with `@my_backoff_exc()` on `_connect_impl`, `MachineConnectionError` translation), using `_detect_platform`/`ADAPTERS`/`_init_paths`/`make_run_fn` from `platform/`. Preserve all four `connect` scenarios (success, retry on refused, non-retryable skips, exhausted raises `MachineConnectionError`).
- [x] 2.6 Implement `disconnect(ip)` — pop `_machines` early-return if absent, pop and await `cancel_monitor(ip)`, close SSH connection (preserve pop-before-await ordering). Implement `disconnect_all()`.
- [x] 2.7 Implement `get_conn(ip)` reconnect-on-closing logic (moved verbatim from `gateway.py:964-978`).
- [x] 2.8 Implement queries: `list_free(platforms)` (filter FREE by platform, sort oldest-first by `free_since`), `list_connected()`, `contains`, `__contains__`, `__len__`, `keys()`, `items()`, `register_machine(ip, state)`, `_get_machine_state(ip)`, `get_machine_state(ip)`.
- [x] 2.9 Implement state transitions: `update_machine(machine)` (replace `ConnectedMachine` in stored `_MachineState`), `occupy(ip)` (read-modify-write → BUSY), `release(ip)` (read-modify-write → FREE with `free_since = time.monotonic()`).
- [x] 2.10 Implement accessor getters: `get_adapter`, `get_platforms`, `get_path`, `get_quote`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir`, `get_hostname` (all read stored `_MachineState`).
- [x] 2.11 Implement monitor mechanism: `install_monitor(ip, *, interval, check_factory, on_free)` — create `asyncio.Task` keyed by IP, sleep/await `check_factory()`, call `on_free()` then break on `False`. Replace prior monitor for the IP before installing new. Identity-checked done-callback pops IP only if slot still points at the same task. `cancel_monitor(ip)` pops + cancels (no await). Preserve all four bg-task invariants (replace-prior, identity-checked, IP-keyed, pop-before-await inside `disconnect`).
- [x] 2.12 Run `uv run ruff check yascheduler/infra/ssh/repository.py && uv run ruff format --check yascheduler/infra/ssh/repository.py`. Run `python3 scripts/grace_check.py --json`.

## 3. Operations package — base primitives

- [x] 3.1 Create `infra/ssh/operations/__init__.py` with MODULE_CONTRACT, re-export `SSHMachineOperations`.
- [x] 3.2 Create `infra/ssh/operations/base.py` with MODULE_CONTRACT/MAP/CHANGE_SUMMARY. Define narrow local Protocols `CommandExecutor`, `SftpProvider`, `StateAccessors` (used by collaborators in steps 4–6).
- [x] 3.3 Move `my_backoff_exc` + `my_backoff_sftp` partials from `gateway.py:87-99` to `operations/base.py`.
- [x] 3.4 Implement `SSHMachineOperations.__init__(repository: MachineRepository, log)` — store `_repo`, `_log`; do NOT yet construct collaborators (steps 4.4, 5.5, 6.5 will).
- [x] 3.5 Implement base primitives on `SSHMachineOperations`: `run`, `run_full` (`@my_backoff_exc()`), `run_bg` (NO backoff — non-idempotent), `upload` (NO backoff), `download` (NO backoff), `get_sftp` (async ctx mgr), `pgrep`, `list_processes`, `get_cpu_cores` (`@my_backoff_exc()` — idempotent read), `setup_node` (uses `my_backoff_exc(exception=AllSSHRetryExc)`). All delegate to `state.adapter.*` via `_repo._get_machine_state(ip)`.
- [x] 3.6 Add M-SSH-OPERATIONS stub to knowledge graph (STATUS=partial).

## 4. Operations package — TaskDeployer

- [x] 4.1 Create `infra/ssh/operations/deployment.py` with MODULE_CONTRACT/MAP/CHANGE_SUMMARY.
- [x] 4.2 Move `_safe_b64decode` from `gateway.py:109-116` to `deployment.py` (module-private, no test imports it).
- [x] 4.3 Move `_write_remote_file` from `gateway.py:126-145` to `deployment.py`. Preserve the contract: catch `asyncssh.misc.Error` to log structured code/reason then re-raise; all non-SFTP exceptions propagate.
- [x] 4.4 Implement `TaskDeployer.__init__(operations: SSHMachineOperations, repository: MachineRepository, log)` — store narrow-Protocol-typed references.
- [x] 4.5 Implement `TaskDeployer._upload_task_data(ip, task, remote_dir, input_files)` — moved verbatim from `gateway.py:506-546` (uses `self._operations.get_sftp(ip)`, `_write_remote_file`, `_safe_b64decode`).
- [x] 4.6 Implement `TaskDeployer._exec_spawn_command(machine, engine, task, task_dir, eng_path, ncpus)` — moved verbatim from `gateway.py:555-575` (uses `self._repository.get_quote(machine.ip)`, `self._operations.run_bg`).
- [x] 4.7 Implement `TaskDeployer.start_task_on_machine(machine, engine, task, ncpus, engines_dir) -> bool` — moved verbatim from `gateway.py:590-672` including the `except BaseException` rollback. Replace `self.update_machine(machine.occupy())` → `self._repository.occupy(machine.ip)`; rollback reads `self._repository._get_machine_state(machine.ip)` and calls `self._repository.update_machine(state.machine.release())`.
- [x] 4.8 Wire `SSHMachineOperations.deploy = TaskDeployer(self, repository, log)` in `SSHMachineOperations.__init__` (step 3.4 extension).
- [x] 4.9 Forward `SSHMachineOperations.start_task_on_machine(...)` → `self.deploy.start_task_on_machine(...)`.

## 5. Operations package — OutputDownloader

- [x] 5.1 Create `infra/ssh/operations/download.py` with MODULE_CONTRACT/MAP/CHANGE_SUMMARY. Move `my_backoff_sftp` partial here (from `operations/base.py` step 3.3 — its first user is here).
- [x] 5.2 Implement `OutputDownloader.__init__(operations, repository, log)`.
- [x] 5.3 Implement `OutputDownloader.download_outputs(ip, remote_dir, local_dir, files, task_id=None)` — moved verbatim from `gateway.py:681-742`. Replace `self.get_sftp(ip)` → `self._operations.get_sftp(ip)`, `self.get_path(ip)` → `self._repository.get_path(ip)`. Preserve per-file fresh-SFTP isolation, error classification (SFTPRetryExc→transient, else→permanent), rmtree gate (`if not transient_errors and not permanent_errors`), session-level catch-all → transient, 3-tuple return shape.
- [x] 5.4 Wire `SSHMachineOperations.download = OutputDownloader(self, repository, log)` in `__init__`.
- [x] 5.5 Forward `SSHMachineOperations.download_outputs(...)` → `self.download.download_outputs(...)`.

## 6. Operations package — OccupancyChecker

- [x] 6.1 Create `infra/ssh/operations/occupancy.py` with MODULE_CONTRACT/MAP/CHANGE_SUMMARY.
- [x] 6.2 Implement `OccupancyChecker.__init__(operations, repository, log)`.
- [x] 6.3 Implement `OccupancyChecker._occupancy_by_pgrep(ip, pattern)` — moved verbatim from `gateway.py:753-774`. Uses `self._operations.pgrep(ip, pattern)`. Safe-default busy on `SSHRetryExc`.
- [x] 6.4 Implement `OccupancyChecker._occupancy_by_cmd(ip, cmd, expected_code)` — moved verbatim from `gateway.py:785-801`. Uses `self._operations.run_full`. Safe-default busy on `SSHRetryExc`.
- [x] 6.5 Implement `OccupancyChecker.occupancy_check(ip, config)` — dispatch on `config.check_pname` / `config.check_cmd` / neither (moved verbatim from `gateway.py:810-827`).
- [x] 6.6 Implement `OccupancyChecker.start_occupancy_check(ip, config)` — call `self._repository.occupy(ip)` then `self._repository.install_monitor(ip, interval=config.sleep_interval, check_factory=partial(self.occupancy_check, ip, config), on_free=partial(self._repository.release, ip))`. No more `_bg_tasks` dict access, no more done-callback inline — the repository owns those.
- [x] 6.7 Wire `SSHMachineOperations.occupancy = OccupancyChecker(self, repository, log)` in `__init__`.
- [x] 6.8 Forward `SSHMachineOperations.start_occupancy_check(...)` → `self.occupancy.start_occupancy_check(...)` and `SSHMachineOperations.occupancy_check(...)` → `self.occupancy.occupancy_check(...)`.

## 7. Domain ports split

- [x] 7.1 In `yascheduler/domain/ports.py`: remove the `MachineGateway` Protocol block. Add `MachineRepository` Protocol (`@runtime_checkable`, methods per `specs/ssh-machine-repository/spec.md` Requirement: MachineRepository port). Add `MachineOperations` Protocol (`@runtime_checkable`, methods per `specs/ssh-machine-repository/spec.md` Requirement: MachineOperations port — note: deployment method is named `start_task_on_machine` per Q3 resolution, not `deploy_task`).
- [x] 7.2 Update `domain/__init__.py` re-exports: add `MachineRepository`, `MachineOperations`; remove `MachineGateway`.
- [x] 7.3 Run `uv run ruff check yascheduler/domain/`. Run `uv run python -c "from yascheduler.domain import MachineRepository, MachineOperations; import inspect; assert inspect.isclass(MachineRepository) and inspect.isclass(MachineOperations)"`.

## 8. Infrastructure facade

- [x] 8.1 Update `infra/ssh/__init__.py`: re-export `MachineRepository` (from `.repository`), `SSHMachineRepository`, `SSHMachineOperations` (from `.operations`), retry exceptions (unchanged). Remove `SSHMachineGateway` from re-exports. Remove `_MachineState` from public surface (test-only via `repository._MachineState`).
- [x] 8.2 Run `uv run python -c "from yascheduler.infra.ssh import SSHMachineRepository, SSHMachineOperations, SFTPRetryExc, AllSSHRetryExc"`.

## 9. Call sites — DI

- [x] 9.1 Update `entrypoints/di.py` `make_daemon`: replace `gateway = SSHMachineGateway(log=log)` with `repository = SSHMachineRepository(log=log)` + `operations = SSHMachineOperations(repository=repository, log=log)`. Pass `machine_repository=repository, machine_operations=operations` to `CloudProvisionerImpl`. Pass `repository=repository, operations=operations` to `Orchestrator`. Preserve the `clouds is None` shared-instance invariant (one repository, one operations, both shared).
- [x] 9.2 Run `uv run ruff check yascheduler/entrypoints/di.py`.

## 10. Call sites — application layer

- [x] 10.1 Update `application/orchestrator.py`: constructor takes `repository: MachineRepository, operations: MachineOperations` instead of `gateway: MachineGateway`. Replace all `_gateway.connect/disconnect/disconnect_all/list_free/list_connected/contains/get_machine_state/update_machine` → `_repository.<same>`. Replace `_gateway.start_task_on_machine/download_outputs/start_occupancy_check/get_cpu_cores/setup_node` → `_operations.<same>`.
- [x] 10.2 Update `application/allocate_task.py`: function signatures `gateway: MachineGateway` → `repository: MachineRepository, operations: MachineOperations` (per-method — `allocate_task` calls `start_occupancy_check`, `get_cpu_cores`, `start_task_on_machine` → operations; nothing from repository). Update `_try_start_on_machine` body accordingly.
- [x] 10.3 Update `application/consume_task.py`: `gateway: MachineGateway` → `operations: MachineOperations` (consume uses `download_outputs` only).
- [x] 10.4 Update `application/deallocate_nodes.py`: `gateway: MachineGateway` → `repository: MachineRepository` (deallocate uses `list_connected`, `disconnect`).
- [x] 10.5 Update `application/abandon_node.py`: `gateway: MachineGateway` annotation (the param is unused per the docstring) — drop the parameter entirely if truly unused, OR retype to `MachineRepository | None` if it's kept for symmetry. Check actual usage.
- [x] 10.6 Run `uv run ruff check yascheduler/application/`. Run `uv run zuban check` if available.

## 11. Call sites — CLI

- [x] 11.1 Update `entrypoints/cli/check_status.py`: replace `gateway.connect/disconnect/get_path/get_quote/get_sftp/_get_machine_state/run_full/get_engines_dir` → split between `repository.connect/disconnect/get_path/get_quote/get_engines_dir/_get_machine_state` and `operations.get_sftp/run_full`. The CLI constructs (or receives) both ports — check how it currently obtains `gateway` and update the source.
- [x] 11.2 Update `entrypoints/cli/manage_node.py`: `gateway.connect/disconnect/setup_node` → `repository.connect/disconnect` + `operations.setup_node`.
- [x] 11.3 Run `uv run ruff check yascheduler/entrypoints/cli/`.

## 12. Call sites — cloud manager

- [x] 12.1 Update `infra/cloud/manager.py` `CloudProvisionerImpl.__init__`: rename `machine_gateway` parameter → `machine_repository` AND add `machine_operations` parameter. Update internal usages: `_setup_vm` uses `machine_repository.connect`, `machine_repository.disconnect`, `machine_operations.setup_node`, `machine_operations.get_cpu_cores`. Preserve the shared-instance invariant (DI passes the same pair).
- [x] 12.2 Run `uv run ruff check yascheduler/infra/cloud/manager.py`.

## 13. Delete old modules

- [x] 13.1 Delete `yascheduler/infra/ssh/gateway.py`.
- [x] 13.2 Delete `yascheduler/infra/ssh/helpers.py`.
- [x] 13.3 Run `uv run python -c "import yascheduler.infra.ssh"` — no import errors. Run `uv run ruff check yascheduler/infra/ssh/`.

## 14. Test migration

- [x] 14.1 Update `tests/unit/test_ssh_gateway_bg_tasks.py`: import `_MachineState` from `yascheduler.infra.ssh.repository`. Update patches: `gateway._bg_tasks` → `repository._monitors`; `gateway.start_occupancy_check` → `operations.occupancy.start_occupancy_check`; `gateway._machines` → `repository._machines`. The three regression suites (disconnect-scope isolation, prior-monitor replacement, unknown-IP no-op) MUST pass unchanged against `MachineRepository`.
- [x] 14.2 Update `tests/unit/test_ssh_gateway_connect.py`: import `SSHMachineRepository` from `yascheduler.infra.ssh.repository`. Patches on `gateway._detect_platform`/`_init_paths` now target `platform.detect._detect_platform`/`platform.paths._init_paths` (or wherever the symbols live after step 1).
- [x] 14.3 Update `tests/unit/test_ssh_gateway_download_outputs.py`: import `SSHMachineOperations` from `yascheduler.infra.ssh.operations`. Patch `gateway_module.my_backoff_sftp` → `operations.download.my_backoff_sftp` (the symbol moved to `operations/download.py`). Update `gateway` fixture to construct `SSHMachineOperations(repository, log)` (and possibly a `SSHMachineRepository` fixture too).
- [x] 14.4 Update `tests/unit/test_ssh_gateway_machine_queries.py`: import `_MachineState` + `SSHMachineRepository` from `yascheduler.infra.ssh.repository`. Tests of `update_machine/contains/len/keys/items/register_machine` target the repository.
- [x] 14.5 Update `tests/unit/test_ssh_gateway_retry_rollback.py`: import `_MachineState` + `SSHMachineRepository` from `repository`; import `SSHMachineOperations` + `TaskDeployer` from operations. The rollback test now exercises `operations.deploy.start_task_on_machine` with a mocked repository; rollback calls `repository._get_machine_state` and `repository.update_machine`.
- [x] 14.6 Update `tests/unit/test_ssh_gateway_write_remote_file.py`: import `_write_remote_file` from `yascheduler.infra.ssh.operations.deployment`. The "abort on upload failure" tests patch `_exec_spawn_command` → patch `operations.deploy._exec_spawn_command` (or `TaskDeployer._exec_spawn_command`).
- [x] 14.7 Update `tests/unit/test_ssh_gateway.py`: split into repository-targeted tests (`list_free`, queries, `register_machine`, `keys/items`) and operations-targeted tests. Move import of `_MachineState` from `gateway` → `repository`. Update patches: `gateway._detect_platform`/`_init_paths` → `platform.*`.
- [x] 14.8 Update `tests/integration/test_ssh_gateway.py`: update imports to `SSHMachineRepository` + `SSHMachineOperations`. The integration tests construct both and run `repository.connect` + `operations.occupancy.occupancy_check` against a real SSH container. The `_exec_spawn_command` reproduction scenario in the file uses `operations.run_bg` + `operations.occupancy.occupancy_check`.
- [x] 14.9 Update `tests/e2e/test_full_cycle.py`: construct `SSHMachineRepository(log=log)` + `SSHMachineOperations(repository=repository, log=log)`; replace `gateway.connect` → `repository.connect`, `gateway.setup_node` → `operations.setup_node`, `gateway.get_engines_dir` → `repository.get_engines_dir`, `gateway.run` → `operations.run`, `gateway.disconnect` → `repository.disconnect`, `orchestrator._gateway.get_machine_state` → `orchestrator._repository.get_machine_state`.
- [x] 14.10 Update `tests/e2e/test_consume_retry.py`: same import/call-site updates as 14.9. Patch `orchestrator._gateway.download_outputs` → `orchestrator._operations.download_outputs`. The `check_gw = SSHMachineGateway(log=log)` line at 293 → `SSHMachineRepository(log=log)`.
- [x] 14.11 Run `uv run pytest -m unit` — all unit tests pass.
- [x] 14.12 Run `uv run pytest -m integration` — all integration tests pass (requires testcontainers).
- [x] 14.13 Run `uv run pytest -m e2e` — all e2e tests pass (requires testcontainers).

## 15. GRACE-lite knowledge graph + validation

- [x] 15.1 Update `docs/knowledge-graph.xml`: remove `M-SSH-GATEWAY` and `M-SSH-HELPERS`. Add `M-SSH-REPOSITORY` (path `infra/ssh/repository.py`, annotations: `class-SSHMachineRepository`, `fn-connect/disconnect/disconnect_all/list_free/list_connected/get_machine_state/update_machine/occupy/release/install_monitor/cancel_monitor`, `fn-get_adapter/get_platforms/get_path/get_quote/get_engines_dir/get_data_dir/get_tasks_dir/get_hostname`, `class-_MachineState`, `class-MySSHClient`, `const-DEFAULT_CONN_OPTS`, `fn-_resolve_tunnel`). Add `M-SSH-OPERATIONS` (path `infra/ssh/operations/`, annotations: `class-SSHMachineOperations`, `fn-run/run_full/run_bg/upload/download/get_sftp/pgrep/list_processes/get_cpu_cores/setup_node`). Add sub-IDs `M-SSH-OPS-DEPLOY` (`operations/deployment.py`, `class-TaskDeployer`, `fn-start_task_on_machine/_upload_task_data/_exec_spawn_command/_write_remote_file/_safe_b64decode`), `M-SSH-OPS-DOWNLOAD` (`operations/download.py`, `class-OutputDownloader`, `fn-download_outputs`, `fn-my_backoff_sftp`), `M-SSH-OPS-OCCUPANCY` (`operations/occupancy.py`, `class-OccupancyChecker`, `fn-occupancy_check/_occupancy_by_pgrep/_occupancy_by_cmd/start_occupancy_check`). Update `M-PLATFORM-ADAPTERS` annotations to add `const-ADAPTERS`, `fn-_detect_platform`, `fn-_init_paths`, `const-MAX_SESSIONS`, `fn-make_run_fn`. Update `CrossLink`s referencing `M-SSH-GATEWAY` → `M-SSH-REPOSITORY` / `M-SSH-OPERATIONS` as appropriate. Update `M-DI`, `M-APPLICATION-ORCHESTRATOR`, `M-CLOUD-PROVISIONER` `<depends>` lines.
- [x] 15.2 Update each new/modified module's CHANGE_SUMMARY to reference `decompose-ssh-gateway`.
- [x] 15.3 Run `python3 scripts/grace_check.py --json` — exit 0.
- [x] 15.4 Run `openspec validate --all --json` — exit 0 / all valid.

## 16. Final static checks

- [x] 16.1 Run `uv run ruff check .` — clean.
- [x] 16.2 Run `uv run ruff format --check .` — clean.
- [x] 16.3 Run `uv run lint-imports` — clean.
- [x] 16.4 Run `uv run zuban check` if available — clean.
- [x] 16.5 Run `uv run pytest -m unit` — green. Run `uv run pytest -m integration` — green. Run `uv run pytest -m e2e` — green.
- [x] 16.6 Run `openspec validate decompose-ssh-gateway --json` — valid.
- [x] 16.7 Verify no remaining `MachineGateway` / `SSHMachineGateway` / `infra.ssh.gateway` / `infra.ssh.helpers` references in `yascheduler/` or `tests/` (search the codebase; the only acceptable remaining occurrences are in `CHANGE_SUMMARY` prose lines and in this change's own artifacts).
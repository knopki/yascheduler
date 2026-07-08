## 1. Domain port cleanup

- [x] 1.1 Remove the `MachineOperations` Protocol from `yascheduler/domain/ports.py` (lines ~265–325, the `@runtime_checkable class MachineOperations(Protocol)` block).
- [x] 1.2 Remove the `MachineOperations` symbol re-export from `yascheduler/domain/__init__.py` if it is listed in `__all__` (search and remove).

## 2. Dissolve the SSHMachineOperations facade

- [x] 2.1 Delete `yascheduler/infra/ssh/operations/base.py` entirely.
- [x] 2.2 Update `yascheduler/infra/ssh/operations/__init__.py`: drop `from .base import SSHMachineOperations`; add `from .deployment import TaskDeployer`, `from .download import OutputDownloader`, `from .occupancy import OccupancyChecker`; set `__all__ = ["TaskDeployer", "OutputDownloader", "OccupancyChecker"]`. Update the MODULE_CONTRACT, MODULE_MAP, and CHANGE_SUMMARY to reflect the new package surface (collaborators as primary exports; no facade).
- [x] 2.3 Verify each collaborator class is already stateless `(log)`-only and accepts `(session, ...)` per method (no changes expected — confirm by reading `deployment.py`/`download.py`/`occupancy.py` constructors and method signatures).

## 3. Update package facade

- [x] 3.1 In `yascheduler/infra/__init__.py`: drop the `SSHMachineOperations` re-export; add `TaskDeployer`, `OutputDownloader`, `OccupancyChecker` re-exports (imported from `.ssh.operations`). Update `__all__` accordingly.

## 4. CloudProvisionerImpl

- [x] 4.1 In `yascheduler/infra/cloud/manager.py`: remove the `machine_operations: SSHMachineOperations` dataclass field from `CloudProvisionerImpl`. Update the `START_CONTRACT: CloudProvisionerImpl` block's INPUTS to drop `machine_operations`.
- [x] 4.2 In `CloudProvisionerImpl._setup_vm` (`manager.py:349`): replace `self.machine_operations.run(session, "cloud-init status --wait")` → `session.run("cloud-init status --wait")`; `self.machine_operations.setup_node(session, self.engines)` → `session.setup_node(self.engines)`; `self.machine_operations.get_cpu_cores(session)` → `session.get_cpu_cores()`.
- [x] 4.3 In the MODULE_CONTRACT DEPENDS/LINKS of `manager.py`: drop `M-SSH-OPERATIONS` (replace with `M-SSH-OPERATIONS-DEPLOY/DOWNLOAD/OCCUPANCY` is NOT needed — cloud no longer depends on operations collaborators at all, only on `M-SSH-SESSION` via the session param).

## 5. Orchestrator

- [x] 5.1 In `yascheduler/application/orchestrator.py` `Orchestrator.__init__`: replace the `operations: MachineOperations` parameter with three new params: `task_deployer: TaskDeployer`, `output_downloader: OutputDownloader`, `occupancy_checker: OccupancyChecker`. Store as `self._task_deployer`, `self._output_downloader`, `self._occupancy_checker`. Drop `self._operations`. Update the `START_CONTRACT: Orchestrator.__init__` INPUTS list.
- [x] 5.2 In `Orchestrator._start_task_on_machine` (`orchestrator.py:177-...`): replace `await self._operations.start_task_on_machine(session, engine, task, ncpus, ...)` → `await self._task_deployer.start_task_on_machine(session, engine, task, ncpus, ...)`; replace the `await self._operations.get_cpu_cores(session)` fallback (line ~182) → `await session.get_cpu_cores()`.
- [x] 5.3 In the allocate-loop consumer: pass `occupancy_checker=self._occupancy_checker` to `allocate_task(...)` (was `operations=self._operations`).
- [x] 5.4 In the consume-loop consumer: pass `output_downloader=self._output_downloader` to `consume_task(...)` (was `operations=self._operations`).
- [x] 5.5 In the consume-loop consumer: replace `self._operations.start_occupancy_check(session, engine)` (line ~484) → `self._occupancy_checker.start_occupancy_check(session, engine)`.
- [x] 5.6 Update orchestrator MODULE_CONTRACT DEPENDS and LINKS: replace `M-SSH-OPERATIONS` with `M-SSH-OPS-DEPLOY, M-SSH-OPS-DOWNLOAD, M-SSH-OPS-OCCUPANCY`.
- [x] 5.7 Update the TYPE_CHECKING import block in `orchestrator.py`: replace `MachineOperations` import with `TaskDeployer, OutputDownloader, OccupancyChecker` (imported from `yascheduler.infra`).

## 6. Use cases

- [x] 6.1 In `yascheduler/application/allocate_task.py`: rename the `operations: MachineOperations` parameter of `allocate_task` and `_try_start_on_machine` to `occupancy_checker: OccupancyChecker`; update the `START_CONTRACT` blocks accordingly; replace the `operations.start_occupancy_check(session, engine)` call (line 145) → `occupancy_checker.start_occupancy_check(session, engine)`. Update TYPE_CHECKING imports.
- [x] 6.2 In `yascheduler/application/consume_task.py`: rename the `operations: MachineOperations` parameter of `consume_task` to `output_downloader: OutputDownloader`; update the `START_CONTRACT: consume_task` block; replace `operations.download_outputs(session=session, ...)` (line 254) → `output_downloader.download_outputs(session=session, ...)`. Update TYPE_CHECKING imports.

## 7. Composition root (make_daemon)

- [x] 7.1 In `yascheduler/entrypoints/di.py` `make_daemon`: replace `operations = SSHMachineOperations(repository=repository, log=log)` with three lines: `task_deployer = TaskDeployer(log)`, `output_downloader = OutputDownloader(log)`, `occupancy_checker = OccupancyChecker(log)`. Update the import block to import the three collaborators (drop `SSHMachineOperations`).
- [x] 7.2 In the `CloudProvisionerImpl(...)` call (`di.py:180-189`): drop the `machine_operations=operations` keyword argument.
- [x] 7.3 In the `Orchestrator(...)` call (`di.py:208-224`): replace `operations=operations` with `task_deployer=task_deployer, output_downloader=output_downloader, occupancy_checker=occupancy_checker`.
- [x] 7.4 Update the make_daemon MODULE_CONTRACT SIDE_EFFECTS and LINKS (drop `SSHMachineOperations`; reference the three collaborators).
- [x] 7.5 Update the inline comment above the construction block (lines ~150-156) to reflect three collaborators and the dropped operations port on CloudProvisionerImpl.

## 8. CLI manage_node

- [x] 8.1 In `yascheduler/entrypoints/cli/manage_node.py`: drop the `operations = SSHMachineOperations(repository=repository, log=log)` line at the top of `manage_node` (line ~374); drop the `SSHMachineOperations` import.
- [x] 8.2 In `_add_node`: change the signature to take `repository: SSHMachineRepository` instead of `(gateway, operations, ...)` (drop the operations parameter); replace `await operations.setup_node(session, config.engines)` → `await session.setup_node(config.engines)`.
- [x] 8.3 Update the call site `_add_node(deps, gateway, operations, spec, config, skip_setup)` → `_add_node(deps, repository, spec, config, skip_setup)`.

## 9. Test updates (mechanical)

- [x] 9.1 `tests/unit/test_di.py`: replace `patch("yascheduler.entrypoints.di.SSHMachineOperations")` (2 sites: lines ~198, ~261) with patches for the three collaborators; update the share-invariant assertions from "one SSHMachineOperations" to "one of each collaborator".
- [x] 9.2 `tests/unit/test_cli_manage_node.py`: update the SSHMachineOperations mock construction (line ~127) — the test no longer needs to patch `SSHMachineOperations` at all; assert it is NOT constructed. Update line ~813 accordingly.
- [x] 9.3 `tests/unit/test_cli_check_status.py` (line ~179): replace the SSHMachineOperations mock helper with a `MachineSession` mock that exposes `run_full` directly.
- [x] 9.4 `tests/unit/test_cloud_provisioner_impl.py` (line ~147): drop the mock SSHMachineOperations helper; assert `CloudProvisionerImpl` is constructed without any operations-side field.
- [x] 9.5 `tests/unit/test_cloud_alloc_session_lifecycle.py` (line ~494): drop the configurable SSHMachineOperations helper; CloudProvisionerImpl is constructed without it.
- [x] 9.6 Update the 6 `tests/unit/test_ssh_gateway*.py` files: replace `operations: SSHMachineOperations` fixture/function params with the specific collaborator each test exercises (`TaskDeployer`/`OutputDownloader`/`OccupancyChecker`); for tests that called session pass-through methods via `operations.run`/`operations.setup_node`/`operations.get_cpu_cores`, call `session.X(...)` directly on the test session mock. The `operations` fixture should be removed or replaced with per-collaborator fixtures.
- [x] 9.7 `tests/integration/test_ssh_gateway.py`: replace the `operations` fixture (lines ~160-162) with three per-collaborator fixtures; update the 40+ test method signatures that took `operations: SSHMachineOperations` to take the specific collaborator(s) they exercise; pass-through method tests now call `session.X(...)` directly.
- [x] 9.8 `tests/e2e/test_consume_retry.py`: at line 66, replace `operations = SSHMachineOperations(repository=repository)` with three collaborator constructions. Replace the 6 monkey-patches of `orchestrator._operations.download_outputs` (lines ~118, 152, 210, 240, 268, 314) with patches of `orchestrator._output_downloader.download_outputs`. Construct the orchestrator with the three collaborator kwargs.

## 10. Knowledge graph

- [x] 10.1 In `docs/knowledge-graph.xml`: remove the `M-SSH-OPERATIONS-BASE` module element entirely.
- [x] 10.2 Update `M-SSH-OPERATIONS` module element: change its `<purpose>` and `<path>` to reflect that the package now exports three collaborators (no facade); promote `M-SSH-OPS-DEPLOY`, `M-SSH-OPS-DOWNLOAD`, `M-SSH-OPS-OCCUPANCY` status if they are not yet `implemented`.
- [x] 10.3 Update `CrossLink`s: the link from `M-DI` to `M-SSH-OPERATIONS` becomes a link to the three collaborator modules (or to `M-SSH-OPERATIONS` as the package they're imported from); the link from `M-CLOUD-PROVISIONER` to `M-SSH-OPERATIONS` is REMOVED (cloud no longer depends on operations collaborators).

## 11. Verification gates

- [x] 11.1 Run `uv run pytest -m unit` — all unit tests pass.
- [x] 11.2 Run `uv run pytest -m integration` — integration tests pass (testcontainers Postgres + SSH).
- [x] 11.3 Run `uv run pytest -m e2e` — e2e tests pass.
- [x] 11.4 Run `uv run zuban check` — clean.
- [x] 11.5 Run `uv run ruff check .` and `uv run ruff format --check .` — clean.
- [x] 11.6 Run `uv run lint-imports` — clean.
- [x] 11.7 Run `python3 scripts/grace_check.py` — exit 0 (knowledge graph + source checks).
- [x] 11.8 Run `openspec validate --all --json` — all changes and specs valid.
- [x] 11.9 Grep `yascheduler/` for residual `SSHMachineOperations` and `MachineOperations` references — expect zero matches in production code (test files may retain references in comments being updated as part of task group 9).

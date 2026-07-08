## Why

`SSHMachineOperations` is a facade that adds no logic: every method is
either a `return await session.X(...)` pass-through (5 methods, of which
`run_full`/`run_bg` are dead with zero callers) or a
`return await self.collaborator.X(...)` forwarder (4 methods). Its
constructor takes a `repository` argument it never reads — documented in
code as `# noqa: ANN401 - kept for signature compatibility; collaborators
no longer use it`. The facade exists only to give the orchestrator and
`CloudProvisionerImpl` a single "operations" port; the underlying
collaborators (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`)
are already stateless and take `(session, ...)` per call. Dissolving the
facade removes dead code, drops a misleading indirection, and lets
`CloudProvisionerImpl` shed an operations port it only used for session
pass-throughs it can call directly.

## What Changes

- **BREAKING**: Delete `SSHMachineOperations` from
  `yascheduler/infra/ssh/operations/base.py` and the
  `MachineOperations` Protocol from `yascheduler/domain/ports.py`.
- **BREAKING**: Delete the 5 facade pass-through methods
  (`run`/`run_full`/`run_bg`/`get_cpu_cores`/`setup_node`) from the
  operations surface — callers already hold a `session` and call
  `session.X(...)` directly. `run_full`/`run_bg` have zero callers and
  disappear without replacement.
- **BREAKING**: `Orchestrator.__init__` replaces its `operations:
  MachineOperations` parameter with three collaborator parameters
  (`task_deployer: TaskDeployer`, `output_downloader: OutputDownloader`,
  `occupancy_checker: OccupancyChecker`). The orchestrator directly calls
  only `task_deployer` and `occupancy_checker`; it holds
  `output_downloader` to thread it into `consume_task` (which it invokes
  from its consumer loop). `allocate_task` receives `occupancy_checker`
  positionally; `consume_task` receives `output_downloader` positionally.
- **BREAKING**: `CloudProvisionerImpl` drops its `machine_operations`
  port. `_setup_vm` calls `session.run`/`session.setup_node`/
  `session.get_cpu_cores` directly on the session returned by
  `machine_repository.connect`.
- **BREAKING**: `allocate_task()` takes `occupancy_checker:
  OccupancyChecker`; `consume_task()` takes `output_downloader:
  OutputDownloader`. Each calls the collaborator method directly.
- The `manage_node` CLI no longer constructs an operations instance;
  `setup_node` is called on the session.
- `TaskDeployer`/`OutputDownloader`/`OccupancyChecker` become the
  concrete ports the orchestrator and use cases are typed against
  (concrete classes, no Protocol — they are already stateless
  `(log)`-constructed single-purpose collaborators).

## Capabilities

### New Capabilities

None — no new capability is introduced. The three collaborators already
exist; this change promotes them to first-class ports.

### Modified Capabilities

- `domain-ports`: Remove the `MachineOperations` Protocol requirement.
  The three remaining SSH-side ports (`MachineRepository`,
  `MachineSession`, `CloudProvisioner`) are unaffected.
- `ssh-infrastructure`: Remove the `MachineOperations port` and
  `SSHMachineOperations composition` requirements. The
  `download_outputs`/`start_task_on_machine`/`occupancy` behavior
  requirements move to the corresponding collaborator class
  (`OutputDownloader`/`TaskDeployer`/`OccupancyChecker`) and drop the
  facade indirection in their scenario wording.
- `dependency-injection`: `make_daemon` no longer constructs
  `SSHMachineOperations`; it constructs `TaskDeployer`/`OutputDownloader`/
  `OccupancyChecker` instances and passes them to the orchestrator and
  use cases. `CloudProvisionerImpl` is constructed without
  `machine_operations`. The single-instance sharing invariant becomes
  per-collaborator (one of each, shared where the same collaborator is
  needed).
- `orchestrator`: `operations: MachineOperations` constructor parameter
  is replaced by `task_deployer` + `occupancy_checker`. Per-machine SSH
  pass-throughs (`get_cpu_cores`, `start_task_on_machine`,
  `start_occupancy_check`) call session / collaborator methods directly.
- `use-cases`: `allocate_task` parameter `operations: MachineOperations`
  becomes `occupancy_checker: OccupancyChecker`; `consume_task`
  parameter `operations: MachineOperations` becomes `output_downloader:
  OutputDownloader`. Download/deploy/occupancy scenarios are reworded to
  reference the collaborator.
- `cli`: `manage_node` constructs `SSHMachineRepository` only; the
  `setup_node` call uses the session directly.
- `package-facades`: Drop the `SSHMachineOperations` re-export from
  `yascheduler.infra`. Re-export `TaskDeployer`/`OutputDownloader`/
  `OccupancyChecker` instead (callers import them by name).
- `testing-unit`: The `MachineOperations` Protocol stub surface is
  removed from the protocol-conformance test list.

## Impact

**Code:**
- `yascheduler/infra/ssh/operations/base.py` — deleted (or reduced to a
  bare re-export shim if a deprecation period is desired; design.md
  settles this).
- `yascheduler/infra/ssh/operations/__init__.py` — re-exports the three
  collaborators instead of `SSHMachineOperations`.
- `yascheduler/domain/ports.py` — `MachineOperations` Protocol removed.
- `yascheduler/application/orchestrator.py` — constructor signature and
  the 3 operations call sites change.
- `yascheduler/application/allocate_task.py`,
  `yascheduler/application/consume_task.py` — parameter type and call
  site change.
- `yascheduler/infra/cloud/manager.py` — `CloudProvisionerImpl` field
  `machine_operations` removed; 3 call sites changed to use `session`.
- `yascheduler/entrypoints/di.py`,
  `yascheduler/entrypoints/cli/manage_node.py` — construction wiring
  changes.
- `tests/unit/test_di.py`, `tests/unit/test_cli_manage_node.py`,
  `tests/unit/test_cli_check_status.py`,
  `tests/unit/test_ssh_gateway*.py` (6 files),
  `tests/unit/test_cloud_provisioner_impl.py`,
  `tests/unit/test_cloud_alloc_session_lifecycle.py`,
  `tests/integration/test_ssh_gateway.py`,
  `tests/e2e/test_consume_retry.py` — call-site, fixture, and mock-surface
  updates.

**Public API stability:** `class Yascheduler` public API, CLI command
entry points, INI config format, DB schema, and the AiiDA scheduler
entrypoint are not affected. The breakage is confined to internal ports
and constructor signatures of `Orchestrator`/`CloudProvisionerImpl`,
which the project's `AGENTS.md` lists as composition-root-internal.

**Knowledge graph:** `M-SSH-OPERATIONS-BASE` is removed;
`M-SSH-OPERATIONS` is updated (collaborators become first-class ports,
facade disappears); `CrossLink`s from `M-DI` and `M-CLOUD-PROVISIONER`
are rewritten.

## Context

`SSHMachineOperations` (in `yascheduler/infra/ssh/operations/base.py`) is a
facade introduced by the `decompose-ssh-gateway` change (2026-06-27). At
the time, base primitives lived on the operations class, so the facade
held real logic and a repository reference. The
`session-based-machine-handle` change (2026-06-28) moved base primitives
onto `MachineSession` and made the three collaborators
(`TaskDeployer`/`OutputDownloader`/`OccupancyChecker`) stateless
`(log)`-only. The facade survived "for composition-root stability" (D4
of that change's design), but the `repository` argument became dead
state (assigned to `self._repo`, never read) and three of the facade's
nine methods (`run_full`, `run_bg`, `occupancy_check`) lost all callers.

Today every facade method is pure indirection:

```
5 pass-throughs  : return await session.X(...)        # 2 dead, 3 live
4 forwarders     : return await self.<c>.X(...)       # all live
```

The five live pass-through call sites (3 in `CloudProvisionerImpl._setup_vm`,
1 in `Orchestrator._start_task_on_machine`, 1 in `manage_node`) all hold
a `session` already; they can call `session.X(...)` directly.

## Goals / Non-Goals

**Goals:**
- Delete `SSHMachineOperations` and the `MachineOperations` Protocol.
- Drop `machine_operations` port from `CloudProvisionerImpl`.
- Drop the dead `repository` parameter and the 3 dead methods.
- Promote `TaskDeployer`/`OutputDownloader`/`OccupancyChecker` to the
  concrete port types the orchestrator and use cases are typed against.
- Update the 8 affected specs to reflect the new contract.

**Non-Goals:**
- Introducing new Protocols for the three collaborators. They are
  concrete, stateless, single-purpose; the existing `MagicMock` /
  `AsyncMock` test pattern suffices.
- Splitting the orchestrator into smaller consumers, or changing
  anything about the four asyncio loops, the UoW pattern, or the
  session-resolution flow.
- Touching `MachineRepository`, `MachineSession`, `CloudProvisioner`,
  `TaskRepository`, `NodeRepository`, or any domain model.
- Changing any CLI entry point's user-facing surface (`yasubmit`,
  `yastatus`, `yanodes`, `yasetnode`, `yainit`, `yascheduler`).
- Schema or DB migration changes.
- Adding a deprecation period. The facade has no external consumers; a
  transition shim would be pure noise. One-shot break.

## Decisions

### D1. Three concrete collaborator ports, no new Protocols

The orchestrator and use cases take the collaborators by **concrete
type** (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`), not by
introduced Protocols. Rationale:

- Each collaborator has a single public method (e.g. `start_task_on_machine`
  on `TaskDeployer`, `download_outputs` on `OutputDownloader`). A
  Protocol with one method is ceremony for no gain.
- The existing `MachineRepository` Protocol survives because it has
  multiple implementations envisioned (real + fake) and serves as a
  runtime_checkable contract in tests. The collaborators have one
  production implementation each and are mocked by `MagicMock`/`AsyncMock`.
- The decompose-ssh-gateway change already deleted the narrow local
  Protocols (`CommandExecutor`, `SftpProvider`, `StateAccessors`) for the
  same reason; reintroducing them in a different shape would be
  inconsistent.

**Alternative considered:** introduce `TaskDeployerPort`,
`OutputDownloaderPort`, `OccupancyCheckerPort` Protocols in
`yascheduler/domain/ports.py`. Rejected — three new single-method
Protocols inflate the port surface without enabling any new
substitutability that `MagicMock` doesn't already cover.

### D2. Orchestrator takes two collaborator ports; `OutputDownloader` taken by `consume_task` directly

`Orchestrator.__init__` signature changes:

```
- operations: MachineOperations
+ task_deployer: TaskDeployer
+ occupancy_checker: OccupancyChecker
```

The orchestrator never calls `download_outputs` directly — it is called
inside `consume_task`, which the orchestrator invokes. So the orchestrator
holds `output_downloader` as an instance attribute purely to thread it
into `consume_task` calls from the consumer loop. It is NOT a constructor
parameter; the orchestrator resolves it from its own
`self._output_downloader` and passes it positionally to `consume_task`.

Net: orchestrator constructor takes 2 SSH-collaborator params
(`task_deployer`, `occupancy_checker`) plus the existing `repository`.
Plus one internal attribute (`self._output_downloader`) populated by
make_daemon via a third constructor parameter `output_downloader` —
simpler to make it a third constructor param than to thread it
differently. Settled below.

**Decision:** Orchestrator constructor takes **three** collaborator
params: `task_deployer`, `output_downloader`, `occupancy_checker`. Even
though the orchestrator only directly calls `task_deployer` and
`occupancy_checker`, `output_downloader` is needed to forward into
`consume_task`. Three named params is clearer than two params plus a
hidden attribute.

### D3. `CloudProvisionerImpl` drops `machine_operations` field

`CloudProvisionerImpl._setup_vm` is the only consumer of
`machine_operations` (3 call sites: `run`, `setup_node`, `get_cpu_cores`).
All three are session pass-throughs. After dissolution:

```
- self.machine_operations.run(session, "cloud-init status --wait")
+ session.run("cloud-init status --wait")

- await self.machine_operations.setup_node(session, self.engines)
+ await session.setup_node(self.engines)

- ncpus = await self.machine_operations.get_cpu_cores(session)
+ ncpus = await session.get_cpu_cores()
```

The `machine_operations: SSHMachineOperations` dataclass field is
removed. `make_daemon` stops passing `machine_operations=...` to
`CloudProvisionerImpl`.

**Alternative considered:** keep `machine_operations` field but typed as
`MachineSession`-only facade. Rejected — there is no facade anymore;
keeping a field that's never used would just relocate the dead-state
smell.

### D4. `make_daemon` constructs three collaborator instances

```
task_deployer = TaskDeployer(log)
output_downloader = OutputDownloader(log)
occupancy_checker = OccupancyChecker(log)
```

All three are passed to `Orchestrator(...)`.
`CloudProvisionerImpl(...)` no longer takes any operations-side
parameter.

The single-instance sharing invariant (from current
`dependency-injection` spec) simplifies: there is no longer a shared
`SSHMachineRepository`/`SSHMachineOperations` *pair*; there is one
shared `SSHMachineRepository` (unchanged — needed for the `_sessions`
registry invariant) plus three stateless collaborator instances. The
collaborators could in principle be constructed per-consumer since they
hold no shared state, but make_daemon constructs one of each for
consistency with the existing pattern.

### D5. Use-case signatures

```
# allocate_task
- operations: MachineOperations
+ occupancy_checker: OccupancyChecker

# consume_task
- operations: MachineOperations
+ output_downloader: OutputDownloader
```

`allocate_task`'s internal `_try_start_on_machine` takes the
`occupancy_checker` and calls `occupancy_checker.start_occupancy_check(session, engine)` directly
(replacing the current `operations.start_occupancy_check(session, engine)`).
Its `start_task_on_machine` parameter (a `Callable` that the orchestrator
binds to its own wrapper) is unchanged at the contract level — only the
orchestrator's wrapper internals change (it now calls
`self._task_deployer.start_task_on_machine(...)` instead of
`self._operations.start_task_on_machine(...)`).

`consume_task` calls `output_downloader.download_outputs(...)`
directly.

### D6. Package facade re-exports

`yascheduler/infra/ssh/operations/__init__.py`:
- Drop `from .base import SSHMachineOperations`.
- Add `from .deployment import TaskDeployer`,
  `from .download import OutputDownloader`,
  `from .occupancy import OccupancyChecker`.
- `__all__ = ["TaskDeployer", "OutputDownloader", "OccupancyChecker"]`.
- Delete `base.py`.

`yascheduler/infra/__init__.py` (the package facade): drop the
`SSHMachineOperations` re-export; add re-exports for the three
collaborators. The `package-facades` spec is updated accordingly.

### D7. CLI `manage_node` drops operations construction

Today `manage_node` constructs `SSHMachineRepository()` +
`SSHMachineOperations(repository=...)` at the top and passes both to
`_add_node`. After dissolution:

```
- repository = SSHMachineRepository(log=log)
- operations = SSHMachineOperations(repository=repository, log=log)
- await _add_node(deps, repository, operations, spec, config, skip_setup)
+ repository = SSHMachineRepository(log=log)
+ await _add_node(deps, repository, spec, config, skip_setup)
```

Inside `_add_node`, the `operations.setup_node(session, config.engines)`
call becomes `session.setup_node(config.engines)`.

### D8. Test fake surface — net change

| Surface              | Before                          | After                            |
|----------------------|---------------------------------|----------------------------------|
| Orchestrator ctor    | 1 `operations: MachineOperations` mock with 9 methods | 3 mocks (`task_deployer`, `output_downloader`, `occupancy_checker`), each with 1–2 methods |
| `CloudProvisionerImpl` ctor | 1 `machine_operations` mock with 3 methods | 0 (field removed) |
| `allocate_task`      | 1 `operations` mock             | 1 `occupancy_checker` mock       |
| `consume_task`       | 1 `operations` mock             | 1 `output_downloader` mock       |
| Total mock methods   | 9 (facade) + 3 (cloud ops) + 1 + 1 = 14 | 2 + 1 + 1 + 2 + 1 + 1 = 8       |

Net: test fake surface shrinks. The "2× test-fake surface" concern from
D4 of `session-based-machine-handle` was wrong because it didn't account
for the cloud-side operations port disappearing entirely.

## Risks / Trade-offs

**[Risk] Orchestrator constructor signature widening (one param →
three).** → Mitigation: all three are passed as keyword arguments in
`make_daemon`; the orchestrator is constructed in exactly one production
site and a small number of test sites. Spec explicitly lists the new
signature.

**[Risk] Tests that monkey-patch `orchestrator._operations.download_outputs`
break.** `tests/e2e/test_consume_retry.py` does this in 6 places. →
Mitigation: trivial mechanical rewrite to
`orchestrator._output_downloader.download_outputs`. Listed in tasks.

**[Risk] Forgetting to update a spec.** The proposal lists 8 affected
capabilities. → Mitigation: spec-delta files are produced for every
listed capability; `openspec validate --all --json` runs as a final
gate.

**[Risk] Knowledge graph drift.** `M-SSH-OPERATIONS-BASE` must be
removed and `CrossLink`s rewritten. → Mitigation: explicit task in
tasks.md; `grace_check.py` is a verification gate.

**[Trade-off] No Protocol means no `isinstance` check.** Today
`MachineOperations` is `@runtime_checkable`; one could assert
`isinstance(ops, MachineOperations)` in tests. → Acceptance: the three
collaborators are concrete classes; `isinstance(x, TaskDeployer)` works
on the concrete class. No real loss.

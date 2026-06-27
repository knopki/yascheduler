## Context

`yascheduler/infra/ssh/gateway.py` (1020 ln) and `helpers.py` (171 ln)
implement a single `SSHMachineGateway` god-class plus an unnamed "helpers"
drawer. Both exceed GRACE-lite source limits and obscure the collection-
vs-operations architectural seam. The adjacent `platform/` package
(`protocol.py`, `adapters.py`, `checks.py`, `linux.py`, `windows.py`,
`common.py`, `exceptions.py`) is healthy and stays untouched.

The `MachineGateway` Protocol in `domain/ports.py` is the only SSH-side
port. Six internal modules reference it (five in `application/`:
`allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`,
`abandon_node.py`, `orchestrator.py`; plus `domain/ports.py` itself).
The AiiDA scheduler plugin does NOT depend on it.

External constraints:
- Python ≥ 3.9, `pip` and `uv` compatible, PEP 621 only.
- No new runtime dependencies.
- No DB schema change, no INI config change, no user-visible CLI change.
- GRACE-lite `docs/knowledge-graph.xml` must stay in sync with the new
  module topology.

See `explore-brief.md` for the full alternatives analysis (A through E).
This design implements approach E (Repo/Ops split).

## Goals / Non-Goals

**Goals:**

- Establish the principal architectural seam: **machine collection
  (repository)** vs **operations on a member (operations)**.
- Sub-split the operations side by use-case cluster (base, deploy,
  download, occupancy) so each is independently testable and grows for
  its own reason.
- Resolve the `_bg_tasks` ↔ `_machines` cross-cutting by making the
  repository own both dicts (so `disconnect` cleans both up naturally).
- Dissolve `helpers.py` by sorting its 5 unrelated concerns into their
  natural homes (`platform/` for detection/registry/paths; `repository.py`
  for connection config; delete the dead `my_backoff_exc` duplicate).
- Bring both former files under GRACE-lite soft/hard limits and remove the
  god-class.
- Preserve every behavior contract (connection retry, occupancy monitor
  scoping keyed by IP, per-file SFTP isolation, error classification,
  rollback-on-spawn-failure, non-idempotent ops not retried, etc.).

**Non-Goals:**

- Rewriting the platform adapter layer (`platform/linux.py`,
  `platform/windows.py`, `common.py`) — stays as-is.
- Changing retry/backoff policy (the `my_backoff_exc` /
  `my_backoff_sftp` decorators stay functionally identical).
- Changing the `download_outputs` 3-tuple return shape or its error
  classification semantics.
- Adding new operations or new deployment features.
- Changing the DB schema, INI config, or CLI surface.
- Migrating external consumers (there are none besides the AiiDA plugin,
  which does not use `MachineGateway`).
- Reorganizing the tests directory layout beyond import-path fixes.

## Decisions

### D1. Principal seam: Repository holds state; Operations are stateless collaborators

The repository owns:

- `_machines: dict[str, _MachineState]` — the connected-machine registry.
- `_monitors: dict[str, asyncio.Task[None]]` — keyed by IP, mirroring
  `_machines`.
- All registry queries and state transitions (`list_free`,
  `list_connected`, `get_machine_state`, `update_machine`, `occupy(ip)`,
  `release(ip)`, `contains`, `__len__`, `keys`, `items`,
  `register_machine`).
- All accessor getters that read stored state (`get_adapter`,
  `get_platforms`, `get_path`, `get_quote`, `get_data_dir`,
  `get_engines_dir`, `get_tasks_dir`, `get_hostname`).
- Connection lifecycle (`connect`, `_connect_impl`, `_open_connection`,
  `disconnect`, `disconnect_all`, `get_conn` reconnect).
- The generic occupancy-monitor **mechanism** (`install_monitor(ip, *,
  interval, check_factory, on_free)`, `cancel_monitor(ip)`). The
  repository does NOT know about `Engine`; `check_factory` is an opaque
  `Callable[[], Awaitable[bool]]` and `on_free` is an opaque
  `Callable[[], None]`.

Operations are stateless collaborators that receive a repository
reference (and the base-primitive provider) and operate on a single
machine via the platform adapter. Operations DO NOT own `_machines` or
`_monitors`; they call repository methods.

**Why:** the repository grows when collection concerns change; operations
grow when use-cases change. They change for different reasons — separating
them prevents the god-class from recurring.

**Alternative considered:** keep registry operations as private dict
access inside the operations object (no Repository class). Rejected: that
leaves no place for the monitor mechanism, the accessors, and the
lifecycle to live without leaking into operations.

### D2. The monitor mechanism belongs to the repository; the check logic belongs to operations

The repository provides:

```python
def install_monitor(
    self, ip: str, *, interval: float,
    check_factory: Callable[[], Awaitable[bool]],
    on_free: Callable[[], None],
) -> None: ...
def cancel_monitor(self, ip: str) -> None: ...
```

`install_monitor` creates an `asyncio.Task` keyed by IP, runs
`asyncio.sleep(interval)` then `await check_factory()`, calls `on_free()`
when the check returns `False`, and registers a done-callback that pops
the IP only when the slot still points at the same task (re-registration
identity check — preserved from current `start_occupancy_check` behavior).

`OccupancyChecker.start_occupancy_check(ip, engine)` calls
`repo.occupy(ip)` then `repo.install_monitor(ip, interval=
engine.sleep_interval, check_factory=partial(self.occupancy_check, ip,
engine), on_free=partial(repo.release, ip))`.

`disconnect(ip)` pops `_machines` AND calls `cancel_monitor(ip)` (which
pops `_monitors`, cancels, awaits). The one-to-one IP↔monitor invariant
is preserved by construction (both dicts share the key).

**Why:** this resolves the cross-cutting ownership. The repository does
not know about `Engine`; operations do not know about `_monitors`.

**Alternative considered:** operations own `_bg_tasks` and register a
disconnect hook on the repository. Rejected: recreates coupling through a
side-channel; the current code's bug-prone `_bg_tasks` ↔ `_machines`
parity is precisely the symptom of this split-ownership.

### D3. Operations use composition, not inheritance

`SSHMachineOperations` exposes base primitives (`run`, `run_full`,
`run_bg`, `upload`, `download`, `get_sftp`, `pgrep`, `list_processes`,
`get_cpu_cores`, `setup_node`) and composes three sibling collaborators:

```python
class SSHMachineOperations:
    def __init__(self, repository, log):
        self._repo = repository
        self._log = log
        self.deploy = TaskDeployer(self, repository, log)
        self.download = OutputDownloader(self, repository, log)
        self.occupancy = OccupancyChecker(self, repository, log)

    # base primitives here
```

Each collaborator receives a reference to a primitive-provider (the
operations object itself — or a narrower protocol; see D5) and the
repository. Call sites:

```python
ops.deploy.start_task_on_machine(machine, engine, task, ncpus, engines_dir)
ops.download.download_outputs(ip, remote_dir, local_dir, files, task_id)
ops.occupancy.start_occupancy_check(ip, engine)
ops.run(machine, cmd)
ops.upload(machine, local, remote)
```

**Why:** composition surfaces use-cases at the call site (`ops.deploy.X`
reads as a use-case) and avoids mixin-ordering hazards. Each collaborator
has a single contract.

**Alternative considered (rejected):** a single `SSHMachineOperations`
flat class with `deploy_*`, `download_*`, `occupancy_*` methods — no
sub-objects. Rejected: recreates a smaller god-class; use-cases are not
namespaced at the call site.

**Alternative considered (rejected):** inheritance —
`TaskDeployer(SSHMachineOperations)` etc. — where sub-classes inherit
base primitives via `self`. Rejected: produces three subclasses that are
never instantiated independently and forces a multiple-inheritance fanout
to combine them; composition is simpler.

### D4. `helpers.py` dissolution — every symbol migrates by concern

| Symbol | Destination | Reason |
|---|---|---|
| `ADAPTERS` | `infra/ssh/platform/registry.py` (NEW) | platform detection registry |
| `_detect_platform` | `infra/ssh/platform/detect.py` (NEW) | platform detection |
| `_init_paths` | `infra/ssh/platform/paths.py` (NEW) | normalizes remote dirs via `adapter.path` |
| `MAX_SESSIONS` | `infra/ssh/platform/detect.py` (next to its only user) | only `_detect_platform` uses it |
| `MySSHClient` | `infra/ssh/repository.py` | connection config lives with the connection owner |
| `DEFAULT_CONN_OPTS` | `infra/ssh/repository.py` | connection config |
| `_resolve_tunnel` | `infra/ssh/repository.py` | connection helper |
| `my_backoff_exc` (helpers copy) | **DELETE** | dead duplicate; gateway has its own copy that moves with operations/base |

**Alternative considered (rejected):** keep `helpers.py` and rename it.
Rejected: its contents are unrelated; the name is the symptom, not the
fix.

**Note:** the canonical `my_backoff_exc` and `my_backoff_sftp` both live
in `infra/ssh/operations/base.py` (the executor primitives) — that is
where their first users (`run_full`, `download_outputs`) live.

### D5. Narrow protocols vs concrete-class reference for collaborators

The collaborators (`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`)
need access to base primitives. Two options:

**(a) Narrow protocols** — define `CommandExecutor`, `SftpProvider`
protocols in `domain/ports.py` (or locally in `operations/base.py`),
collaborators type-annotate against them. Enables mocking collaborators'
dependencies in unit tests without instantiating the full operations
object.

**(b) Concrete reference** — collaborators hold `operations:
SSHMachineOperations`. Simpler, fewer protocols, but couples the
collaborators to the concrete class.

**Decision: (a) narrow local protocols in `operations/base.py`** (not in
`domain/ports.py` — they are internal infrastructure protocols, not domain
ports). The collaborators type-annotate against
`CommandExecutor`/`SftpProvider`/`StateAccessors` (small local
Protocols). `SSHMachineOperations` implements them implicitly. Tests of
`TaskDeployer` can construct a fake `CommandExecutor`/`SftpProvider`
without the full operations object.

**Why:** the collaborators are the units with the most branching logic
(rollback, error classification, monitor dispatch) — they benefit most
from isolated testing. The narrow protocols cost ~30 ln but unlock
focused unit tests.

**Alternative considered (rejected):** put the narrow protocols in
`domain/ports.py`. Rejected: these are infrastructure plumbing, not
domain-facing contracts; `domain/ports.py` already has the two domain
Protocols (`MachineRepository`, `MachineOperations`) which are the
abstraction domain consumers care about.

### D6. `_make_run_fn` placement

`_make_run_fn(conn, adapter) -> OuterRunCallable` is a pure closure used
by `repository.connect` (to populate `ConnectedMachine.ncpus` via
`adapter.get_cpu_cores`) and by `operations.base.get_cpu_cores` /
`setup_node`.

**Decision:** define it in `infra/ssh/platform/run_fn.py` (NEW, ~15 ln)
and import from both places. It is adapter-glue (binds `conn` + `quote`
+ the adapter's `run`), so it belongs with the platform layer.

**Alternative considered (rejected):** put it in `repository.py`.
Rejected: that makes `operations/base.py` depend on `repository.py` for a
pure utility that has nothing to do with collection state. Placing it in
`platform/` keeps the dependency graph clean: both `repository.py` and
`operations/base.py` depend on `platform/`, neither depends on the other.

### D7. Public re-exports from `infra/ssh/__init__.py`

The package root re-exports the public surface:

```python
from .exceptions import AllSSHRetryExc, SFTPRetryExc, SSHRetryExc
from .operations import SSHMachineOperations
from .repository import MachineRepository

__all__ = [
    "AllSSHRetryExc",
    "MachineRepository",
    "SFTPRetryExc",
    "SSHMachineOperations",
    "SSHRetryExc",
]
```

`_MachineState` is NOT re-exported (private to `repository.py`; tests
import it via `yascheduler.infra.ssh.repository._MachineState`).
Collaborator classes (`TaskDeployer`, `OutputDownloader`,
`OccupancyChecker`) are NOT re-exported (accessed via
`SSHMachineOperations.deploy` / `.download` / `.occupancy` attributes).
`MySSHClient`, `DEFAULT_CONN_OPTS`, `_resolve_tunnel`,
`my_backoff_exc`/`my_backoff_sftp` are NOT public (used internally).

**Why:** minimize the public surface. Domain consumers (Orchestrator,
Cloud) compose via the two Protocols in `domain/ports.py`. Tests import
internals from their actual module paths.

### D8. `domain/ports.py` — two Protocols replace one

Remove `MachineGateway`. Add two `@runtime_checkable` Protocols:

```python
@runtime_checkable
class MachineRepository(Protocol):
    # Collection lifecycle
    async def connect(self, ip, username, client_keys, *, port=22,
        connect_timeout=None, data_dir=None, engines_dir=None,
        tasks_dir=None, jump_host=None, jump_username=None) -> ConnectedMachine: ...
    async def disconnect(self, ip: str) -> None: ...
    async def disconnect_all(self) -> None: ...

    # Queries
    def list_free(self, platforms: list[str] | None) -> list[ConnectedMachine]: ...
    def list_connected(self) -> list[ConnectedMachine]: ...
    def contains(self, ip: str) -> bool: ...
    def get_machine_state(self, ip: str) -> ConnectedMachine | None: ...

    # State transitions
    def update_machine(self, machine: ConnectedMachine) -> None: ...
    def occupy(self, ip: str) -> None: ...
    def release(self, ip: str) -> None: ...

    # Accessors (stored-state readers)
    def get_adapter(self, ip: str) -> RemoteMachineAdapter: ...
    def get_platforms(self, ip: str) -> Sequence[str]: ...
    def get_path(self, ip: str) -> type[PurePath]: ...
    def get_quote(self, ip: str) -> QuoteCallable: ...
    def get_data_dir(self, ip: str) -> PurePath: ...
    def get_engines_dir(self, ip: str) -> PurePath: ...
    def get_tasks_dir(self, ip: str) -> PurePath: ...
    def get_hostname(self, ip: str) -> str: ...

    # Monitor mechanism
    def install_monitor(self, ip: str, *, interval: float,
        check_factory: Callable[[], Awaitable[bool]],
        on_free: Callable[[], None]) -> None: ...
    def cancel_monitor(self, ip: str) -> None: ...

    # Internals registry access (test/CLI uses)
    def __len__(self) -> int: ...
    def __contains__(self, ip: str) -> bool: ...

@runtime_checkable
class MachineOperations(Protocol):
    # Base exec / SFTP / inspection / node setup
    async def run(self, machine: ConnectedMachine, cmd: str) -> ProcessResult: ...
    async def run_full(self, machine: ConnectedMachine, cmd: str) -> SSHCompletedProcess: ...
    async def run_bg(self, machine: ConnectedMachine, cmd: str, *, cwd: str | None = None) -> None: ...
    async def upload(self, machine: ConnectedMachine, local: Path, remote: str) -> None: ...
    async def download(self, machine: ConnectedMachine, remote: str, local: Path) -> None: ...
    async def get_cpu_cores(self, ip: str) -> int: ...
    async def setup_node(self, ip: str, engines: EngineRepository) -> None: ...
    async def pgrep(self, ip: str, pattern: str | Pattern[str], full: bool = True) -> AsyncGenerator[ProcessInfo, None]: ...
    async def list_processes(self, ip: str) -> AsyncGenerator[ProcessInfo, None]: ...

    # Use-case collaborators
    def deploy_task(self, machine: ConnectedMachine, engine: Engine, task: Task, ncpus: int, engines_dir: PurePath) -> bool: ...
    # Note: `deploy_task` is the operations-level entry; `SSHMachineOperations.deploy.start_task_on_machine`
    # is the implementation. The Protocol method is named `deploy_task` to flatten the namespace
    # for type-checking; the operations object's `.deploy.X` attribute provides use-case namespacing
    # for the concrete impl. Alternative: expose as a TaskDeployer protocol attribute — deferred to Open Question Q3.

    async def download_outputs(self, ip: str, remote_dir: str, local_dir: Path, files: list[str], task_id: int | None = None) -> tuple[list[tuple[str, Any]], list[tuple[str | None, Exception]], list[tuple[str | None, Exception]]]: ...

    async def occupancy_check(self, ip: str, config: Engine) -> bool: ...
    def start_occupancy_check(self, ip: str, config: Engine) -> None: ...
```

**Why two Protocols:** repository-side operations are synchronous queries
+ state transitions + lifecycle; operations-side are mostly async task-
facing calls. Splitting makes the type system express the architectural
seam. Consumers that only need queries (e.g., CLI `get_path`) depend only
on `MachineRepository`.

### D9. Call-site rewrite strategy (phased within a single change)

To keep the change atomic and reviewable, the rewrite proceeds in this
order (reflected as ordered tasks in `tasks.md`):

1. Introduce the new modules alongside the old (`repository.py`,
   `operations/`, `platform/run_fn.py`, `platform/registry.py`,
   `platform/detect.py`, `platform/paths.py`). The new code imports from
   `platform/` only — no circular deps.
2. Update `domain/ports.py`: add `MachineRepository` + `MachineOperations`,
   keep `MachineGateway` temporarily (deprecated alias for compatibility
   during the transition) — OR remove `MachineGateway` outright if the
   rewrite is atomic. Decision: remove outright (see Open Question Q1).
3. Update `entrypoints/di.py`: construct `MachineRepository` +
   `SSHMachineOperations`, pass two ports to `Orchestrator` and
   `CloudProvisionerImpl`.
4. Update application call sites: `orchestrator.py`,
   `allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`,
   `abandon_node.py` — replace `gateway.X` with `repository.X` or
   `operations.X` (and `gateway: MachineGateway` type annotations with
   the two new Protocols or both).
5. Update CLI call sites: `check_status.py`, `manage_node.py`.
6. Update tests (import paths, patch targets, fixtures).
7. Delete `gateway.py` and `helpers.py`.
8. Update `infra/ssh/__init__.py` re-exports.
9. Update `docs/knowledge-graph.xml` + run `grace_check.py`.

Each step compiles and passes tests; the final step removes the old
files.

## Risks / Trade-offs

### Risk: Test patch targets move → silent test pass

Tests patch `gateway_module.my_backoff_sftp`,
`gateway._detect_platform`, `gateway._init_paths`. If the patches target
the old paths after the code moves, the patches silently patch nothing
and the tests may pass for the wrong reason.

→ **Mitigation:** enumerate every patch target in tasks.md and update in
lockstep; the test-migration task runs the affected test files
immediately after the move.

### Risk: Behavior regression in monitor replacement

The current `start_occupancy_check` has subtle semantics: replace-prior
before installing the new task; identity-checked done-callback protects
re-registration; `_bg_tasks` keyed by IP; `disconnect` pops before await
(to prevent re-insertion races). Moving this to a generic
`install_monitor` mechanism must preserve all four invariants.

→ **Mitigation:** the existing tests in
`tests/unit/test_ssh_gateway_bg_tasks.py` (three regression suites:
disconnect-scope isolation, prior-monitor replacement, unknown-IP
no-op) MUST pass unchanged against the new `MachineRepository`. These
tests pin the invariants; if they break, the mechanism is wrong.

### Risk: `disconnect` ordering regression

Current `disconnect` pops `_machines` before awaiting task cancellation
(to prevent re-entry race re-inserting the cancelled task). The new
implementation must preserve this ordering.

→ **Mitigation:** preserved explicitly in the
`MachineRepository.disconnect` contract; tested by the same bg-tasks
regression suite.

### Risk: `_MachineState` import-path churn breaks 4 test files

`test_ssh_gateway_bg_tasks.py`, `test_ssh_gateway_retry_rollback.py`,
`test_ssh_gateway_machine_queries.py`, `test_ssh_gateway_write_remote_file.py`
import `_MachineState` from `gateway`. Path change → 4 import updates.

→ **Mitigation:** tasks.md enumerates the exact import update for each
test file. `_MachineState` stays a private dataclass of `repository.py`.

### Risk: Two-port constructor change cascades through `Orchestrator` /
`CloudProvisionerImpl` signature

`Orchestrator.__init__` and `CloudProvisionerImpl.__init__` today take
`gateway: MachineGateway`. Splitting the parameter affects every
construction site and every test that constructs these classes.

→ **Mitigation:** tasks.md has a dedicated task for constructor-signature
update across DI + tests; tests use keyword args so the update is
mechanical.

### Risk: Knowledge graph drift

`docs/knowledge-graph.xml` currently has `M-SSH-GATEWAY` and
`M-SSH-HELPERS`. After the change, both must be removed and replaced by
`M-SSH-REPOSITORY` + `M-SSH-OPERATIONS` (+ sub-IDs for deploy/download/
occupancy collaborators) and the migrated `M-PLATFORM-*` symbols.

→ **Mitigation:** the final task updates the knowledge graph atomically
with the deletion of the old modules and runs `grace_check.py` to verify.

### Trade-off: indirection overhead

`ops.deploy.start_task_on_machine(...)` adds one attribute lookup vs the
current `gateway.start_task_on_machine(...)`. Negligible at the call
volume (task deployment, not hot path). Worth the use-case namespacing.

### Trade-off: more files to navigate

Seven new files vs two old files. Each is under 250 ln and single-
responsibility. Net navigation cost is lower because a reader looking for
"deploy" goes straight to `operations/deployment.py` instead of
scrolling a 1020-ln file.

## Migration Plan

This is a pure refactor with no persisted-state change and no config
change. Rollback is `git revert`. No database migration, no config
migration, no runtime flag.

Atomicity: the change is implemented as a single PR. Steps in D9 run in
order; intermediate commits compile and pass tests; the final commit
removes the old files. Operators do nothing differently before/after
deploy.

## Open Questions

### Q1. Atomic vs transitional removal of `MachineGateway` Protocol

The simplest path is to remove `MachineGateway` from `domain/ports.py`
in the same change that introduces the two new Protocols. This is
atomic but breaks any out-of-tree consumer (we believe there are none).

A transitional path would keep `MachineGateway` as a deprecated
`Protocol`-alias for one release, then remove it later.

**Decision:** atomic removal. The proposal confirms no external consumers
besides the AiiDA scheduler plugin (which does not import
`MachineGateway`). Internal consumers are all rewritten in this change.

### Q2. Should `MachineRepository.occupy(ip)` / `release(ip)` be Protocols?

These are convenience methods wrapping `update_machine(machine.occupy())`
/ `update_machine(machine.release())`. They are used by operations
(`OccupancyChecker.start_occupancy_check` calls `repo.occupy(ip)`).

**Decision:** yes, include in the `MachineRepository` Protocol. They
express the occupy/release transition intent more directly than
`update_machine(...)` and are easier to mock in tests.

### Q3. Should `MachineOperations` Protocol expose `deploy` /
`download` / `occupancy` as sub-attributes, or flatten the methods?

Two shapes for the Protocol:

(a) Flat: `MachineOperations.deploy_task(...)`,
`MachineOperations.download_outputs(...)`,
`MachineOperations.start_occupancy_check(...)`. Simple Protocol; call
sites `ops.deploy_task(...)`.

(b) Nested: `MachineOperations.deploy.start_task_on_machine(...)`,
etc. Protocol describes a `deploy: TaskDeployer` attribute typed against
a separate `TaskDeployer` Protocol.

**Decision (deferred to implementation):** prefer (b) for the concrete
class (use-case namespacing at call site reads better) but (a) for the
domain Protocol (consumers depending on the Protocol should not need to
know about internal collaborator classes). The concrete
`SSHMachineOperations` exposes `deploy`/`download`/`occupancy`
attributes; the domain `MachineOperations` Protocol flattens the methods
the domain layer actually calls. Implementation verifies that the
flattened Protocol methods forward to the collaborators.

### Q4. Where does `occupy`/`release` get the current machine?

`occupy(ip)` needs to read the current `_MachineState` for `ip`, get its
`machine`, call `machine.occupy()`, then `update_machine(result)`. This
is a read-modify-write on the registry. Race-window: another call
modifies the same machine between read and write.

**Decision:** acceptable — the current `update_machine` has the same
window and relies on single-threaded asyncio event-loop scheduling. No
new race introduced.

### Q5. `_write_remote_file` and `_safe_b64decode` location

Both are private helpers used only by `_upload_task_data` (deploy path).

**Decision:** both move to `infra/ssh/operations/deployment.py` as
module-private functions. `_safe_b64decode` is not imported by any test;
`_write_remote_file` is imported by one test file
(`test_ssh_gateway_write_remote_file.py`) — its import path updates.
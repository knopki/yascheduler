# Explore Brief — decompose-ssh-gateway

## Problem

`yascheduler/infra/ssh/gateway.py` (1020 ln) is one god-class (`SSHMachineGateway`)
mixing two responsibilities:

1. **Machine collection lifecycle** — registry of connected machines, queries,
   state transitions, occupancy-monitor task mechanism (keyed by IP, cancelled
   on `disconnect`), connection lifecycle.
2. **Operations on a single machine** — command exec, SFTP transfer, task
   deployment, output download, occupancy check logic.

Adjacent `helpers.py` (171 ln) is an unnamed drawer of 5 unrelated concerns:
adapter registry, SSH client factory, connection options, tunnel helper,
platform detection, path initialization, a duplicated `my_backoff_exc`
(dead-code clone of gateway's own copy).

Both modules exceed GRACE-lite soft/hard source limits and obscure the
primary architectural seam: **collection ≠ operations on a member**.

## Alternatives Considered

### A. Extract free functions only (state.py + ops.py + helpers untouched)
Rejected — does not fix the god-class; only moves 3 helpers out.
`SSHMachineGateway` still ~830 ln with 7 responsibilities. `helpers.py`
untouched.

### B. Decompose by cluster (registry / connection / occupancy / deployment /
   download / sftp_ops / command_exec)
Rejected — over-decomposes. `MachineRegistry` extracted as a separate class
would just wrap a dict in trivial methods every other method reads/writes; the
registry IS the gateway's state, not a collaborator. `sftp_ops.py` and
`command_exec.py` would be 30-ln files of pure thin delegation to asyncssh/
adapter — they have no contract worth a module. Pre-condition for B
("gateway still huge after core extractions") does not hold once the heavy
clusters leave.

### C. Mixins (`SSHMachineGateway(ConnectionMixin, RegistryMixin, ...)`)
Rejected — implicit shared-state access via `self._machines` is fragile;
mixin ordering hazards; "Mixin" is a smell for "couldn't decompose properly";
harder to test in isolation.

### D. Hybrid (extract only the 2–3 heaviest: occupancy + deployment +
   connection; kill helpers.py by sorting its contents by concern)
Partially accepted — the *extraction targets* are correct (occupancy,
deployment, connection) but D leaves registry + operations entangled in the
residual gateway. Does not establish the principal architectural seam.

### E. Repo/Ops split (CHOSEN)
Split along the principal seam: **MachineRepository** (owns the collection:
`_machines` dict, `_monitors` dict, connect/disconnect lifecycle, queries,
state transitions, accessor getters, monitor mechanism) vs **MachineOperations**
(operates on a member: exec, SFTP, deploy, download, occupancy check logic).
Then sub-split the operations side by case-cluster (base / deploy / download /
occupancy) since those grow independently and have distinct contracts.

The repository owns the monitor *mechanism* (`install_monitor`,
`cancel_monitor`); operations provide the *check logic* and request the
repository to install/monitor. This cleanly resolves the `_bg_tasks` ↔
`_machines` cross-cutting: the repository owns both dicts, so `disconnect`
cleans up naturally.

## Mapping Tables (final approach)

### Method → destination

| Method | Destination | Notes |
|---|---|---|
| `__init__` | `MachineRepository` | owns `_machines`, `_monitors` |
| `connect` / `_connect_impl` / `_open_connection` | `MachineRepository` | collection lifecycle + builds `ConnectedMachine` via adapter |
| `disconnect` / `disconnect_all` | `MachineRepository` | pops `_machines` + cancels monitor |
| `register_machine` | `MachineRepository` | |
| `list_free` / `list_connected` | `MachineRepository` | queries |
| `contains` / `__contains__` / `__len__` / `keys` / `items` | `MachineRepository` | |
| `get_machine_state` / `update_machine` | `MachineRepository` | port contract |
| `_get_machine_state` | `MachineRepository` | adapter-internal accessor |
| `get_conn` | `MachineRepository` | connection lifecycle (reconnect) |
| `install_monitor` / `cancel_monitor` (NEW) | `MachineRepository` | generic monitor mechanism (interval, check factory, on_free) |
| `get_adapter` / `get_platforms` / `get_path` / `get_quote` / `get_data_dir` / `get_engines_dir` / `get_tasks_dir` / `get_hostname` | `MachineRepository` | accessor getters — read stored state |
| `run` / `run_full` / `run_bg` | `SSHMachineOperations` (base) | exec primitives |
| `upload` / `download` / `get_sftp` | `SSHMachineOperations` (base) | SFTP primitives |
| `pgrep` / `list_processes` | `SSHMachineOperations` (base) | process inspection |
| `get_cpu_cores` / `setup_node` / `_make_run_fn` | `SSHMachineOperations` (base) | node info/install; `_make_run_fn` may move to `platform/run_fn.py` |
| `_upload_task_data` / `_exec_spawn_command` / `start_task_on_machine` / `_write_remote_file` / `_safe_b64decode` | `TaskDeployer` | deploy use-case + rollback |
| `download_outputs` + `my_backoff_sftp` | `OutputDownloader` | download use-case + error classification |
| `occupancy_check` / `_occupancy_by_pgrep` / `_occupancy_by_cmd` / `start_occupancy_check` | `OccupancyChecker` | check logic + engine-aware installer that calls `repo.occupy(ip)` + `repo.install_monitor(...)` |

### `_MachineState` placement

Stays a private dataclass of `MachineRepository` (`repository.py`).
Re-exported from `yascheduler.infra.ssh` package root only if external
consumers need it — but no external consumers exist; tests are the only
importers and tests can update their import paths.

### `helpers.py` dissolution

| Symbol | Destination | Reason |
|---|---|---|
| `ADAPTERS` | `infra/ssh/platform/` (registry module) | platform concern |
| `_detect_platform` | `infra/ssh/platform/` (detection module) | platform concern |
| `_init_paths` | `infra/ssh/platform/` (paths module) | platform concern |
| `MAX_SESSIONS` | `infra/ssh/platform/` (next to `_detect_platform`) | only used by `_detect_platform` |
| `MySSHClient` | `infra/ssh/repository.py` | connection config lives with repository |
| `DEFAULT_CONN_OPTS` | `infra/ssh/repository.py` | connection config lives with repository |
| `_resolve_tunnel` | `infra/ssh/repository.py` | connection helper |
| `my_backoff_exc` (helpers copy) | **DELETE** | dead duplicate of `gateway.py:87-92`; gateway defines its own and does not import from helpers |
| `helpers.py` itself | **DELETE** | all symbols have a better home |

### New protocols in `domain/ports.py`

`MachineGateway` Protocol is split into two focused Protocols:

**`MachineRepository`** — collection lifecycle + queries + state transitions +
accessor getters + `install_monitor`/`cancel_monitor` mechanism.

**`MachineOperations`** — exec + SFTP + deploy + download + occupancy-check
logic + `start_occupancy_check` (engine-aware installer that calls repo).

`runtime_checkable` retained for each. Old `MachineGateway` Protocol removed.

### Composition / DI

```python
repository = MachineRepository(log=log)
operations = SSHMachineOperations(repository=repository, log=log)
# operations internally composes TaskDeployer, OutputDownloader, OccupancyChecker
# exposing them as operations.deploy / operations.download / operations.occupancy
# OR each is a standalone class with shared base primitives.
```

`Orchestrator` and `CloudProvisionerImpl` receive `repository` and
`operations` (two ports) where they today receive one `gateway`. Call sites
split unambiguously:

| Caller today | After |
|---|---|
| `_gateway.connect` / `disconnect` / `list_free` / `list_connected` / `contains` / `get_machine_state` / `update_machine` / `disconnect_all` | `_repository.<same>` |
| `_gateway.start_task_on_machine` / `download_outputs` / `start_occupancy_check` / `get_cpu_cores` / `setup_node` | `_operations.<member>.<method>` (or flat on operations) |
| CLI `get_path` / `get_quote` / `get_engines_dir` | `_repository.<getter>` |

No method is ambiguous about its destination.

## Cross-Module Data Flows

### Task deployment

```
Orchestrator.allocate_task
  → _operations.deploy.start_task_on_machine(machine, engine, task, ncpus, engines_dir)
    → _repository.occupy(machine.ip)   # transition state
    → _repository.get_sftp_ctx(ip)      # OR operations.base.get_sftp — TBD design
    → _repository.get_path(ip) / get_quote(ip)  # read accessor
    → TaskDeployer._upload_task_data(...)        # uses base primitives
    → TaskDeployer._exec_spawn_command(...)      # uses base run_bg
    except BaseException:
      → _repository.get_state(ip)                 # rollback decision
      → _repository.update_machine(released)      # rollback
      raise
```

### Occupancy monitoring install + lifecycle

```
Orchestrator.mark_running
  → _operations.occupancy.start_occupancy_check(ip, engine)
    → _repository.occupy(ip)                       # occupy at gateway level
    → _repository.install_monitor(
        ip,
        interval=engine.sleep_interval,
        check_factory=lambda: _operations.occupancy.occupancy_check(ip, engine),
        on_free=lambda: _repository.release(ip)
      )

Daemon.shutdown
  → _repository.disconnect_all()
    for ip: _repository.disconnect(ip)
      → pop _machines
      → cancel_monitor(ip)  # pops _monitors, cancel, await
      → close conn
```

### Output download

```
Orchestrator.consume_task
  → _operations.download.download_outputs(ip, remote_dir, local_dir, files, task_id)
    → per file: open fresh sftp via _operations.base.get_sftp(ip)
      → classify per-file exception → transient / permanent
    → if both empty: open fresh sftp, rmtree via _repository.get_path(ip)
    → catch-all → session-level transient
    → return (meta_add, transient_errors, permanent_errors)
```

## Call-graph among new modules (acyclic)

```
                REPOSITORY  BASE_OPS  DEPLOY  DOWNLOAD  OCCUPANCY
─────────────────────────────────────────────────────────────────
BASE_OPS         read          self       —        —          —
DEPLOYMENT       transition   run_bg      self      —          —
DOWNLOAD         path+sftp     —         self     self         —
OCCUPANCY        transition   run_full,    —        —        self
                              pgrep
```

No cycles. Repository first → base ops → then three sibling children.

## Inheritance vs composition for operations sub-clusters

Decision: **composition**, not inheritance. `SSHMachineOperations` exposes
base primitives (`run_full`, `run_bg`, `get_sftp`, `pgrep`, ...). Three
sibling collaborators (`TaskDeployer`, `OutputDownloader`,
`OccupancyChecker`) receive a reference to a primitive-provider (the
operations object itself or a narrow protocol) and the repository. Calls
read `ops.deploy.start_task_on_machine(...)` / `ops.download.download_outputs(...)`
/ `ops.occupancy.start_occupancy_check(...)` — use-case names at the call
site, no god-class.

## Open Questions

1. **Where does `_make_run_fn` live?** Pure `(conn, adapter) -> OuterRunCallable`
   closure. Used by `repository.connect` (build `ConnectedMachine`) and by
   `operations.base` (`get_cpu_cores`, `setup_node`). Candidate homes:
   `platform/run_fn.py` (most likely — it's an adapter glue), or `repository.py`.
   Decision in design.md.
2. **Does `SSHMachineOperations` expose sub-objects as attributes
   (`ops.deploy`, `ops.download`, `ops.occupancy`) or flat methods on the
   operations object?** Attribute namespaces give use-case grouping at call
   site; flat is simpler. Decision in design.md — leaning attribute namespaces.
3. **Public re-exports from `infra/ssh/__init__.py`**: which symbols
   (`MachineRepository`, `SSHMachineOperations`, sub-collaborator classes,
   retry exceptions) are public surface? Decision in design.md.
4. **Test import path updates**: tests currently import `_MachineState`,
   `_write_remote_file`, `_safe_b64decode`, patch `gateway._detect_platform`
   / `_init_paths` / `my_backoff_sftp`. Final targets to be enumerated in
   tasks.md (test migration).
5. **GRACE-lite knowledge graph update**: `M-SSH-GATEWAY` splits into
   `M-SSH-REPOSITORY` + `M-SSH-OPERATIONS` (+ maybe sub-M-ids for deploy/
   download/occupancy). `M-SSH-HELPERS` is removed; its symbols migrate to
   `M-PLATFORM-*` and `M-SSH-REPOSITORY`. CrossLinks updated. Decision in
   tasks.md.
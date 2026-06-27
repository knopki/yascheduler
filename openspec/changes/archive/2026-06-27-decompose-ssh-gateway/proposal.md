## Why

`yascheduler/infra/ssh/gateway.py` (1020 ln) is a single god-class mixing
two architecturally distinct responsibilities — managing a collection of
connected machines (registry, lifecycle, queries, state transitions,
occupancy-monitor mechanism) and operating on a single machine (command
exec, SFTP, task deployment, output download, occupancy check logic). The
adjacent `helpers.py` (171 ln) is an unnamed drawer of five unrelated
concerns (adapter registry, SSH client factory, connection options, tunnel
helper, platform detection, path initialization) plus a dead duplicate of
`my_backoff_exc`. Both files exceed GRACE-lite source limits and obscure
the primary seam: **a collection is not operations on its members**. As
the system grows (new machine operation kinds, new monitor strategies),
both sides change for different reasons and the god-class compounds the
cost of every change.

## What Changes

- **SPLIT** `SSHMachineGateway` along the collection-vs-operations seam:
  - **NEW** `MachineRepository` (in `infra/ssh/repository.py`) owns the
    connected-machine collection: `connect`/`disconnect`/`disconnect_all`,
    `register_machine`, queries (`list_free`/`list_connected`/
    `get_machine_state`), state transitions (`update_machine`,
    `occupy(ip)`, `release(ip)`), accessors (`get_path`/`get_quote`/
    `get_engines_dir`/...), connection lifecycle (`get_conn` reconnect),
    and a generic monitor **mechanism** (`install_monitor(ip, *, interval,
    check_factory, on_free)`, `cancel_monitor(ip)`) keyed by IP. The
    repository holds the `_machines` and `_monitors` dicts so `disconnect`
    cleans both up naturally.
  - **NEW** `SSHMachineOperations` (in `infra/ssh/operations/`) operates on
    a single machine via the platform adapter and SFTP. Composed of base
    primitives (`run`/`run_full`/`run_bg`, `upload`/`download`/`get_sftp`,
    `pgrep`/`list_processes`, `get_cpu_cores`/`setup_node`) plus three
    sibling use-case collaborators: `TaskDeployer`
    (`start_task_on_machine` + upload + spawn + rollback,
    `_write_remote_file`, `_safe_b64decode`), `OutputDownloader`
    (`download_outputs` + error classification, `my_backoff_sftp`),
    `OccupancyChecker` (`occupancy_check`, `_by_pgrep`, `_by_cmd`,
    `start_occupancy_check` — which calls `repo.occupy(ip)` +
    `repo.install_monitor(...)`).
- **DELETE** `infra/ssh/helpers.py`. Its symbols migrate by concern:
  `ADAPTERS`/`_detect_platform`/`_init_paths`/`MAX_SESSIONS` →
  `infra/ssh/platform/`; `MySSHClient`/`DEFAULT_CONN_OPTS`/`_resolve_tunnel`
  → `infra/ssh/repository.py`; the dead duplicate `my_backoff_exc` is
  deleted (the gateway's own copy in `gateway.py:87-92` is the canonical
  one and moves with the operations/base module that uses it).
- **SPLIT** the `MachineGateway` Protocol in `domain/ports.py` into two
  focused Protocols: `MachineRepository` (collection lifecycle, queries,
  state transitions, accessors, monitor mechanism) and `MachineOperations`
  (exec, SFTP, deploy, download, occupancy check logic). Both are
  `@runtime_checkable`. **BREAKING:** the single `MachineGateway` Protocol
  is removed; consumers (Orchestrator, CloudProvisionerImpl, DI) take two
  parameters (`repository`, `operations`) instead of one `gateway`.
- **UPDATE** call sites and Protocol consumers:
  - Behavioral call sites (address repository methods via `_repository.*`
    and operations via `_operations.*` with use-case namespacing such as
    `_operations.deploy.start_task_on_machine(...)`):
    `application/orchestrator.py`, `infra/cloud/manager.py`,
    `entrypoints/di.py`, `entrypoints/cli/check_status.py`,
    `entrypoints/cli/manage_node.py`.
  - Protocol-typed call sites (function/method signatures annotated
    `MachineGateway` — replaced by `MachineRepository` and/or
    `MachineOperations` per method use, **BREAKING**): `application/
    allocate_task.py`, `application/consume_task.py`,
    `application/deallocate_nodes.py`, `application/abandon_node.py`,
    `application/orchestrator.py`. Five application files plus
    `domain/ports.py` itself import or reference `MachineGateway`.
- **UPDATE** unit/integration/e2e tests: import `_MachineState` from
  `infra/ssh/repository`; `_write_remote_file` from
  `infra/ssh/operations/deployment`; patch `_detect_platform`/`_init_paths`
  on their new `platform/` location; patch `my_backoff_sftp` on its new
  `operations/download` location. (`_safe_b64decode` is private to the
  deploy module and not imported by any test; no test migration needed.)
- **UPDATE** GRACE-lite knowledge graph (`docs/knowledge-graph.xml`):
  `M-SSH-GATEWAY` splits into `M-SSH-REPOSITORY` + `M-SSH-OPERATIONS`
  (with sub-IDs for deploy/download/occupancy collaborators); `M-SSH-HELPERS`
  is removed; `CrossLink`s updated.

## Capabilities

### New Capabilities

- `ssh-machine-repository`: Connected-machine collection — registration,
  lifecycle (connect/disconnect), queries, state transitions, accessor
  getters, and a generic occupancy-monitor mechanism keyed by IP.

### Modified Capabilities

- `ssh-gateway`: Split into `MachineRepository` + `MachineOperations`;
  the single `SSHMachineGateway` class and the single `MachineGateway`
  Protocol are removed. Behaviors previously covered by `ssh-gateway`
  requirements move to `ssh-machine-repository` (lifecycle, queries,
  monitor mechanism) and to `ssh-machine-operations` (exec, transfer,
  deploy, download, occupancy logic). See delta spec.
- `domain-ports`: The `MachineGateway` Protocol is split into
  `MachineRepository` and `MachineOperations` Protocols. **BREAKING.** See
  delta spec.
- `platform-adapters`: Receives `ADAPTERS`, `_detect_platform`,
  `_init_paths`, `MAX_SESSIONS` from the dissolved `helpers.py` (these
  symbols always belonged to platform detection). The existing
  platform-adapters requirements are extended with these new locations.
  See delta spec.
- `dependency-injection`: `make_daemon` constructs and injects two
  ports (`repository`, `operations`) instead of one `gateway`; construction
  call site and Orchestrator/CloudProvisionerImpl constructor signatures
  updated. See delta spec.

## Impact

- **Code:**
  - NEW: `infra/ssh/repository.py` (~250 ln), `infra/ssh/operations/`
    package (`__init__.py`, `base.py` ~120 ln, `deployment.py` ~130 ln,
    `download.py` ~80 ln, `occupancy.py` ~120 ln). Possible
    `infra/ssh/platform/run_fn.py` for `make_run_fn`.
  - REMOVED: `infra/ssh/gateway.py`, `infra/ssh/helpers.py`.
  - MODIFIED: `domain/ports.py` (Protocols split),
    `application/orchestrator.py`, `infra/cloud/manager.py`,
    `entrypoints/di.py`, `entrypoints/cli/check_status.py`,
    `entrypoints/cli/manage_node.py`, `infra/ssh/__init__.py`
    (re-exports), `infra/ssh/platform/__init__.py` (re-exports migrated
    symbols).
  - Public API surface of `infra/ssh` (re-exported names) may narrow
    to `MachineRepository`, `SSHMachineOperations`, retry exceptions,
    `_MachineState` (test-only). Final surface decided in design.md.
- **APIs:** `MachineGateway` Protocol replaced by `MachineRepository` +
  `MachineOperations` Protocols — **BREAKING**. External consumers depending
  on `MachineGateway`: the AiiDA scheduler plugin does NOT import it. Six
  internal modules reference `MachineGateway` (five in `application/`:
  `allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`,
  `abandon_node.py`, `orchestrator.py`; plus `domain/ports.py` itself),
  and several others reference `SSHMachineGateway` directly. Constructor
  signatures of `Orchestrator` and `CloudProvisionerImpl` change (two
  ports instead of one).
- **Dependencies:** No new runtime dependencies. Tests continue to use
  testcontainers (PostgreSQL, SSH) for integration/e2e.
- **DB schema:** Unchanged.
- **INI config:** Unchanged.
- **CLI commands:** No user-visible change; internal call-site rewrite only.
- **AiiDA scheduler plugin:** Unaffected (uses the AiiDA scheduler plugin
  entrypoint, not `MachineGateway`).
- **Tests:** Unit tests in `tests/unit/test_ssh_gateway*.py` (7 files)
  need import-path and patch-target updates; some split between
  repository-tests and operations-tests. Integration
  `tests/integration/test_ssh_gateway.py` and e2e
  (`tests/e2e/test_full_cycle.py`, `tests/e2e/test_consume_retry.py`) need
  call-site updates. Behavior is preserved; only module boundaries and
  call paths change.
- **GRACE-lite:** `M-SSH-GATEWAY` and `M-SSH-HELPERS` removed from
  `docs/knowledge-graph.xml`; replaced by `M-SSH-REPOSITORY`,
  `M-SSH-OPERATIONS` (with sub-IDs). `M-PLATFORM-*` gains the migrated
  platform symbols. `CrossLink`s updated. `grace_check.py` must pass.
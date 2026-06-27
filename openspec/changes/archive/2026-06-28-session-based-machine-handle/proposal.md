## Why

`decompose-ssh-gateway` split the `SSHMachineGateway` god-class into
`SSHMachineRepository` + `SSHMachineOperations` along the "collection vs
operations" seam. The split is superficial: the connected-machine entity
(`_MachineState`) stayed private to the repository, hidden behind IP-keyed
accessor wrappers, while operations reached past those wrappers via the
**private** `_get_machine_state` method — 11 production call sites (8× in
`operations/base.py`, 1× in `deployment.py` rollback, 1× in `occupancy.py`,
1× in `entrypoints/cli/check_status.py:340` with an explicit
`# noqa: SLF001` acknowledging the smell). The decompose change's own
`explore-brief.md` rejected its Alternative B with this exact critique
("MachineRegistry would just wrap a dict in trivial methods every other
method reads/writes"); Alternative E (chosen) re-created the problem it
warned about. The entity that operations actually operate on is not
first-class; the IP-keyed lookup pattern is preserved under a renamed
facade. This change makes the entity first-class.

## What Changes

- **NEW** `MachineSession` Protocol in `yascheduler/domain/ports.py` and
  concrete `SSHMachineSession` class in
  `yascheduler/infra/ssh/session.py` (~150 ln). The session is the public
  entity handle carrying: domain identity (`ip`, mutable `machine`
  snapshot, `occupy`/`release`/`update` transitions), read-only connect-time
  config (`adapter`, `platforms`, `data_dir`, `engines_dir`, `tasks_dir`),
  adapter-derived accessors (`path`, `quote`, `hostname`), connection
  lifecycle (`is_closed` property, `_close()` called only by repository
  disconnect), base primitives (`run`, `run_full`, `run_bg`, `upload`,
  `open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`, `list_processes`),
  and the monitor mechanism (`install_monitor`, `cancel_monitor`). The
  session owns its own teardown — no `_monitors` dict in the repository.

- **REWRITE** `SSHMachineRepository` (`infra/ssh/repository.py`, 505 ln →
  ~150 ln). Surface shrinks to seven methods: `connect → MachineSession`,
  `disconnect(ip)`, `disconnect_all()`, `list_free(platforms) →
  list[MachineSession]`, `list_connected() → list[MachineSession]`,
  `get_session(ip) → MachineSession | None`, plus `__contains__`/`__len__`.
  Removes: `_get_machine_state` (private, 11 callers), `get_machine_state`,
  `occupy`/`release`/`update_machine` (wrappers — moved to session),
  `get_path`/`get_quote`/`get_hostname` (wrappers — moved to session),
  `install_monitor`/`cancel_monitor` (moved to session), `register_machine`/
  `keys`/`items` (test-only hooks). Removes the `_monitors: dict[str, Task]`
  — the session owns its own monitor task. `_machines: dict[str,
  _MachineState]` becomes `_sessions: dict[str, MachineSession]`. The
  connection-building bits (`MySSHClient`, `DEFAULT_CONN_OPTS`,
  `_resolve_tunnel`) STAY in `repository.py`. `_MachineState` is removed
  (replaced by `MachineSession`).

- **REWRITE** `SSHMachineOperations` (`infra/ssh/operations/base.py`,
  253 ln → facade only). Per RF2, the facade STAYS (orchestrator signature
  unchanged) but its base primitives are removed (moved onto `MachineSession`);
  the methods that remain on `SSHMachineOperations` resolve the session via
  `repository.get_session(ip)` and delegate to the session. The three
  sibling collaborators (`TaskDeployer`, `OutputDownloader`,
  `OccupancyChecker`) become **stateless** — each takes `(log)` at
  construction and `(session, …)` per call. They no longer need a
  repository reference (the OccupancyChecker's last reason for needing
  one — `install_monitor` — is now on the session).

- **CHANGE** `MachineOperations` Protocol method signatures in
  `yascheduler/domain/ports.py`: parameters that today take
  `ConnectedMachine` or `ip: str` for the machine-reference now take
  `session: MachineSession` instead. The Protocol name and facade
  pattern stay. **BREAKING** for any consumer of the Protocol's method
  signatures (internal-only; see Impact).

- **UPDATE** application-layer consumers to resolve sessions at the
  seams and pass them through:
  - `application/orchestrator.py` — per-tick `session =
    self._repository.get_session(ip)` at each consumer entry that
    previously called `get_machine_state(ip)`; pass `session` to
    `operations.X(…)`.
  - `application/allocate_task.py`, `application/consume_task.py`,
    `application/deallocate_nodes.py` — parameter types change from
    `ConnectedMachine`/`ip` to `MachineSession` for SSH-side calls;
    use cases continue to receive snapshots only where they make
    allocation decisions on snapshot state (then resolve session via
    `repository.get_session` for the operations call).
  - `application/abandon_node.py` — no SSH-side call; no change.
  - `infra/cloud/manager.py` — `_setup_vm` stores the `connect()` return
    and passes it to `machine_operations.run(...)`;
    `machine_operations.setup_node(ip, ...)` and
    `machine_operations.get_cpu_cores(ip)` resolve the session inside
    operations (signatures take `MachineSession`).
  - `entrypoints/di.py` — construction unchanged (same two SSH-side
    ports wired into the orchestrator).
  - `entrypoints/cli/check_status.py` — `_get_machine_state(ip)`
    replaced with `get_session(ip)` (line 340, removing the
    `# noqa: SLF001`); `_download_convergence_snippet` and
    `_display_remote_output` currently thread `(repository, operations,
    ip)` and call `repository.get_path(ip)` / `operations.get_sftp(ip)`
    — both removed — so they collapse to taking a single `MachineSession`
    resolved once at the top of the command. The 4-tuple return shape
    of `_display_remote_output` narrows accordingly.

- **UPDATE** `MachineRepository` Protocol in `yascheduler/domain/ports.py`:
  seven methods (see above), with return types changing from
  `list[ConnectedMachine]` / `ConnectedMachine | None` to
  `list[MachineSession]` / `MachineSession | None`. **BREAKING** for
  any consumer of the Protocol.

- **DELETE** `infra/ssh/operations/base.py` primitives section
  (`run`/`run_full`/`run_bg`/`upload`/`get_sftp`/`pgrep`/`list_processes`/
  `get_cpu_cores`/`setup_node`) — these move onto `MachineSession`. The
  narrow local Protocols (`CommandExecutor`, `SftpProvider`,
  `StateAccessors`) become unnecessary and are deleted (collaborators
  take sessions directly).

- **UPDATE** tests across `tests/unit/test_ssh_gateway*.py` (5+ files),
  `tests/integration/test_ssh_gateway.py`, `tests/e2e/test_full_cycle.py`,
  `tests/e2e/test_consume_retry.py`, `tests/unit/test_domain_ports.py`:
  fixtures construct `MachineSession` instances instead of
  `_MachineState`; patches on `_machines`/`_monitors`/`_get_machine_state`
  migrate to `_sessions`/`session._monitor_task`/`get_session`. Behavior
  invariants preserved.

- **UPDATE** GRACE-lite knowledge graph (`docs/knowledge-graph.xml`):
  `M-SSH-REPOSITORY` annotation list shrinks (lost methods); new
  `M-SSH-SESSION` module added with annotations for `MachineSession`,
  `SSHMachineSession`, `install_monitor`, `cancel_monitor`, `_close`,
  `occupy`, `release`, `update`, `path`, `quote`, `hostname`, `run`,
  `run_full`, `run_bg`, `upload`, `open_sftp`, `get_cpu_cores`,
  `setup_node`, `pgrep`, `list_processes`; `CrossLink`s updated.

## Capabilities

### New Capabilities

- `ssh-machine-session`: The connected-machine entity handle. Defines
  `MachineSession` Protocol (domain port) and the concrete
  `SSHMachineSession` class carrying connect-time config, mutable
  `machine` snapshot, base SSH primitives, and the per-session monitor
  mechanism. The session is what operations actually operate on; the
  repository hands it out and tracks it.

### Modified Capabilities

- `ssh-machine-repository`: Repository surface shrinks from ~25 methods
  to 7. `_MachineState` removed; replaced by `MachineSession`. Monitor
  mechanism (`install_monitor`/`cancel_monitor`) moves off the repository
  and onto the session — reverses `decompose-ssh-gateway` D2 (rationale
  collapses once session type exists). Repository owns only
  `_sessions: dict[str, MachineSession]`; no `_monitors` dict.
  `MySSHClient`/`DEFAULT_CONN_OPTS`/`_resolve_tunnel` stay.
  `MachineOperations` Protocol method signatures change to take
  `MachineSession`. **BREAKING.** See delta spec.
- `domain-ports`: New `MachineSession` Protocol added.
  `MachineRepository` Protocol method list narrows and return types
  change to `MachineSession`. `MachineOperations` Protocol method
  signatures change to take `MachineSession` instead of
  `ConnectedMachine`/`ip`. Both Protocols remain `@runtime_checkable`.
  **BREAKING.** See delta spec.

## Impact

- **Code:**
  - NEW: `yascheduler/infra/ssh/session.py` (~150-180 ln).
  - REWRITTEN: `yascheduler/infra/ssh/repository.py` (~505 → ~150 ln),
    `yascheduler/infra/ssh/operations/base.py` (primitives removed,
    facade retained, ~253 → ~80 ln), `yascheduler/infra/ssh/operations/
    deployment.py` (collaborator becomes stateless, ~287 → ~200 ln),
    `yascheduler/infra/ssh/operations/download.py` (~138 → ~110 ln),
    `yascheduler/infra/ssh/operations/occupancy.py` (~199 → ~150 ln),
    `yascheduler/infra/ssh/operations/__init__.py` (re-exports updated),
    `yascheduler/infra/ssh/__init__.py` (re-exports updated).
  - MODIFIED: `yascheduler/domain/ports.py` (add `MachineSession`
    Protocol, slim `MachineRepository`, change `MachineOperations`
    signatures), `yascheduler/application/orchestrator.py`,
    `yascheduler/application/allocate_task.py`,
    `yascheduler/application/consume_task.py`,
    `yascheduler/application/deallocate_nodes.py`,
    `yascheduler/entrypoints/cli/check_status.py`,
    `yascheduler/entrypoints/cli/manage_node.py`,
    `yascheduler/infra/cloud/manager.py`.
  - UNCHANGED: `application/abandon_node.py` (no SSH-side call),
    `entrypoints/di.py` wiring (2 SSH-side ports unchanged).
- **APIs:** The `MachineRepository` Protocol narrows and changes return
  types; `MachineOperations` Protocol method signatures change to take
  `MachineSession`. **BREAKING** for any consumer of these Protocols.
  All consumers are internal (`application/*`, `infra/cloud/manager.py`,
  `entrypoints/cli/*`, `entrypoints/di.py`, tests). The AiiDA scheduler
  plugin does NOT import these Protocols — unaffected. The package's
  public surface (`yascheduler` CLI commands, `Yascheduler` class, INI
  config, DB schema) is unchanged.
- **Dependencies:** No new runtime dependencies. Tests continue to use
  testcontainers (PostgreSQL, SSH) for integration/e2e.
- **DB schema:** Unchanged.
- **INI config:** Unchanged.
- **CLI commands:** No user-visible change.
- **AiiDA scheduler plugin:** Unaffected.
- **Tests:** Five+ unit test files rewritten (fixtures, patches,
  import paths). Integration and e2e tests get import-path and
  call-site updates. Behavior is preserved; only module boundaries and
  call paths change.
- **Predecessor:** `cleanup-unused-repository-symbols` MUST land first.
  This change's tasks reference method names it removes.
- **GRACE-lite:** New module `M-SSH-SESSION` added.
  `M-SSH-REPOSITORY` annotation list shrinks.
  `M-SSH-OPERATIONS-BASE` annotation list shrinks (primitives moved to
  session). `CrossLink`s updated. `grace_check.py` must pass.
- **Rollback:** `git revert`. Pure refactor with no persisted-state
  change, no config change, no runtime flag.

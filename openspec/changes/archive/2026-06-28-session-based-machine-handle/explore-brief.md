# Explore Brief — session-based-machine-handle

## Problem

`SSHMachineRepository` (505 ln, ~25 methods) established by `decompose-ssh-gateway`
separates collection from operations only superficially: the entity
(`_MachineState`, private) stays hidden behind IP-keyed accessor wrappers, while
operations reach past them via the **private** `_get_machine_state` — 11
production call sites (8× in `operations/base.py`, 1× `deployment.py` rollback,
1× `occupancy.py`, 1× `cli/check_status.py:340` with `# noqa: SLF001`).
The wrapper repository is the symptom; the private reach-through is the disease.
The decompose-ssh-gateway `explore-brief.md` rejected its own Alternative B with
exactly this critique ("MachineRegistry would just wrap a dict in trivial
methods"); Alternative E (chosen) re-created the problem it warned about.

## Alternatives Considered

### A. Status quo (do nothing)
Rejected — the wrapper repository hides the real entity, exposing 8 accessors
(audit: 5 of them have zero production callers — being removed by
`cleanup-unused-repository-symbols`) while the actual operations API is a
private method. Every new SSH operation re-entrenches the smell.

### B. Variant D from earlier exploration (extract accessors/state-transitions into separate MachineAccessors collaborator)
Rejected — relocating the wrappers does not fix the disease. `_MachineState`
stays private; the new collaborator still reads repository internals. Adds a
class, removes nothing.

### C. Entity-handle redesign (CHOSEN)
Promote `_MachineState` to a public `MachineSession` class carrying conn +
adapter + paths + machine snapshot AND the operations on them. Repository
shrinks to a true collection (7 methods). Operations methods take sessions, not
IPs/snapshots. Monitor mechanism moves onto the session (1:1 with the session,
not a collection-level concern).

## Final Approach — Mapping Tables

### Repository surface — before/after

| Today (505 ln, ~25 methods)              | After (~150 ln, 7 methods)            |
|------------------------------------------|---------------------------------------|
| `connect`, `_connect_impl`, `_open_connection` | `connect → MachineSession`         |
| `disconnect`, `disconnect_all`            | `disconnect(ip)`, `disconnect_all()`  |
| `list_free`, `list_connected`             | `list_free → list[MachineSession]`, `list_connected → list[MachineSession]` |
| `contains`/`__contains__`, `__len__`      | same (unchanged surface)              |
| `get_machine_state`                       | replaced by `get_session(ip) → MachineSession \| None` |
| `install_monitor`, `cancel_monitor`       | **move onto session** (RF1)           |
| `register_machine`, `keys`, `items`       | **deleted** (test-only, replaced by `_sessions[ip] = session` direct poke in tests, or `register_session` if needed) |
| `_get_machine_state` (private, 11 callers)| **deleted** (callers receive session directly) |
| `_machines`, `_monitors` dicts            | `_sessions: dict[str, MachineSession]` only (no `_monitors`) |
| `occupy`, `release`, `update_machine` (wrappers) | **deleted** — these move onto session |
| `get_adapter`, `get_platforms`, `get_data_dir`, `get_engines_dir`, `get_tasks_dir` | **already deleted by `cleanup-unused-repository-symbols`** |
| `get_path`, `get_quote`, `get_hostname` (wrappers) | **deleted** — these become session properties |
| `MySSHClient`, `DEFAULT_CONN_OPTS`, `_resolve_tunnel` | **stay** in `repository.py` (used by `_open_connection`) |
| `_MachineState` (private dataclass)       | **deleted** — replaced by public `MachineSession` class in `infra/ssh/session.py` |

### MachineSession — new public class in `infra/ssh/session.py`

Carries (frozen-at-connect-time): `ip`, `machine` (mutable snapshot), `adapter`,
`platforms`, `data_dir`, `engines_dir`, `tasks_dir`, `conn`, `conn_opts`.
Owns: `_monitor_task`, `_closed` flag.

Methods/properties:
- Domain face: `ip`, `machine`, `occupy()`, `release()`, `update(machine)`
- Read-only config properties: `adapter`, `platforms`, `data_dir`, `engines_dir`, `tasks_dir`
- Adapter-derived properties: `path`, `quote`, `hostname`
- Base primitives (moved from `operations/base.py`): `run`, `run_full`, `run_bg`,
  `upload`, `open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`, `list_processes`
- Monitor mechanism (moved from repository): `install_monitor`, `cancel_monitor`
- Lifecycle: `_close()` (called only by `repository.disconnect`), `is_closed` property

### Protocol layering

| Layer            | Sees                                                                    |
|------------------|-------------------------------------------------------------------------|
| `domain/model.py` | `ConnectedMachine` only (unchanged)                                     |
| `domain/ports.py` | `ConnectedMachine`, `MachineSession` Protocol (new), `MachineRepository` Protocol (slimmed), `MachineOperations` Protocol (method signatures change to take `MachineSession`) |
| `application/*`   | All of the above (use cases pass sessions through; orchestrator resolves `get_session(ip)` per-tick) |
| `infra/ssh/*`     | Concrete `SSHMachineSession`, `SSHMachineRepository`, `SSHMachineOperations` facade (kept per RF2), three collaborators (stateless: `TaskDeployer(log)`, `OutputDownloader(log)`, `OccupancyChecker(log)` — all take sessions now) |

### Collaborators — before/after

| Today                                   | After                                    |
|-----------------------------------------|------------------------------------------|
| `TaskDeployer(operations, repository, log)` | `TaskDeployer(log)` — takes `session` per call |
| `OutputDownloader(operations, repository)` | `OutputDownloader(log)` — takes `session` per call |
| `OccupancyChecker(operations, repository)` | `OccupancyChecker(log)` — takes `session` per call (monitor installed via `session.install_monitor`) |

### `MachineOperations` Protocol — kept (RF2), signatures change

Today's `run(machine: ConnectedMachine, cmd)` → `run(session: MachineSession, cmd)`. Same for all base primitives and the three use-case methods. Orchestrator signature unchanged: still `(repository, operations)` — 2 SSH-side ports.

### Orchestrator call-site pattern

Per-tick: `session = self._repository.get_session(ip); if session is None: MACHINE_GONE; …`. Session is short-lived per-tick reference; the underlying session/conn/monitor has long lifetime in `_sessions`.

## Cross-Module Data Flows

### Task deployment
```
Orchestrator._start_task_on_machine(machine, engine, task)
  session = self._repository.get_session(machine.ip)
  ncpus = await session.get_cpu_cores()
  await self._operations.start_task_on_machine(session, engine, task, ncpus, engines_dir)
    → TaskDeployer.start_task_on_machine(session, engine, task, ncpus, engines_dir)
      session.occupy()
      try:
        async with session.open_sftp() as sftp: …
        await session.run_bg(cmd, cwd=…)
      except BaseException:
        if session.is_closed:
          log "already disconnected"; raise
        session.update(session.machine.release()); raise
      return True
```

### Occupancy monitoring install + lifecycle
```
Orchestrator / allocate_task → operations.start_occupancy_check(session, engine)
  → OccupancyChecker.start_occupancy_check(session, engine)
    if session.machine.state == FREE: session.occupy()
    session.install_monitor(
      interval=engine.sleep_interval,
      check_factory=lambda: self.occupancy_check(session, engine),
      on_free=session.release,
    )
# session._close() (from repository.disconnect) marks closed, cancels monitor, awaits, closes conn
```

### Output download
```
Orchestrator → operations.download_outputs(session, remote_dir, local_dir, files, task_id)
  → OutputDownloader.download_outputs(session, …)
    per file: async with session.open_sftp() as sftp: …
    on empty: rmtree via session.path
```

## Real risks (grounded in code)

### R1. Rollback "already disconnected" detection
Today (`deployment.py:254-283`): `state = repo._get_machine_state(ip); if state is None: log "already disconnected"; raise`. Under redesign: deployer holds session; check becomes `if session.is_closed: log; raise`. **Must wire `session.is_closed` into rollback path explicitly.** Pinned by `test_ssh_gateway_retry_rollback.py`.

### R2. Test rewrite is bulk of diff
`tests/unit/test_ssh_gateway_bg_tasks.py` etc. poke `repository._machines[ip]` / `repository._monitors[ip]`. Under redesign: `_sessions[ip]`. Mechanical but touches 4+ test files. Enumerate every touch in tasks.md to avoid silent-pass regressions.

### R4. disconnect ordering invariant
Today (`repository.py:275-296`): pop `_machines[ip]` BEFORE awaiting monitor cancel. Under redesign: pop `_sessions[ip]` then `await session._close()`. `session._close()` MUST set `_closed = True` synchronously BEFORE its first await.

Phantom risk dismissed: `partial(repo.release, ip)` → `session.release` is fine — monitor task is cancelled and awaited before conn closes; even in race window, mutation on orphaned session is invisible.

## Decisions (Q-G1/Q-G2/Q-G3)

- **Q-G1 (session-owns-monitor):** RF1 — adopted. `_monitors` dict eliminated. Reverses D2 from `decompose-ssh-gateway` (D2 rationale collapses once session type exists).
- **Q-G2 (`list_*` return type):** `list[MachineSession]`. Use cases pass sessions through.
- **Q-G3 (orchestrator caching):** Fresh `get_session(ip)` per tick (preserves today's `get_machine_state(ip)` pattern).

## Predecessor / ordering

`cleanup-unused-repository-symbols` MUST land first — it deletes 9 methods whose absence simplifies this change's diff. This change's tasks.md references method names that the cleanup removes.

## Open questions

None blocking. Q-G1/Q-G2/Q-G3 resolved above. R1/R2/R4 have mitigations spelled out.

## Context

`decompose-ssh-gateway` (archived) split the `SSHMachineGateway` god-class
into `SSHMachineRepository` + `SSHMachineOperations` along the
"collection vs operations" seam. The seam is superficial: the entity
(`_MachineState`, private dataclass in `infra/ssh/repository.py`) stayed
hidden behind IP-keyed accessor wrappers on the repository, while
operations reached past those wrappers via the **private**
`_get_machine_state` method (11 production call sites: 8× in
`operations/base.py`, 1× in `deployment.py` rollback, 1× in
`occupancy.py`, 1× in `cli/check_status.py:340` with `# noqa: SLF001`).
The decompose change's own `explore-brief.md` rejected its Alternative B
with the exact critique that applies today: "MachineRegistry would just
wrap a dict in trivial methods every other method reads/writes."

External constraints:
- Python ≥ 3.9, `pip` and `uv` compatible, PEP 621 only.
- No new runtime dependencies.
- No DB schema change, no INI config change, no user-visible CLI change.
- AiiDA scheduler plugin unaffected (does not import `MachineRepository`
  / `MachineOperations`).
- Predecessor `cleanup-unused-repository-symbols` MUST land first; it
  removes 9 zero-caller methods (`get_conn`, `keys`, `items`,
  `register_machine`, `get_adapter`, `get_platforms`, `get_data_dir`,
  `get_engines_dir`, `get_tasks_dir`) so this change's diff is honest.
- GRACE-lite `docs/knowledge-graph.xml` must stay in sync with the new
  module topology; `grace_check.py` must pass.

See `explore-brief.md` for the alternatives analysis (A status quo, B
extract-accessors-collaborator, C entity-handle chosen). This design
implements approach C with the three refinements (RF1/RF2/RF3) surfaced
during review.

## Goals / Non-Goals

**Goals:**

- Establish the principal architectural correction: **the connected-machine
  entity is first-class**. `MachineSession` is public, carries its own
  state AND behavior, and is what operations actually operate on.
- Eliminate the private `_get_machine_state` reach-through (11 callers).
  Sessions are passed explicitly, never resolved via private dict lookup.
- Shrink `SSHMachineRepository` to a true collection: 7 methods, one
  `_sessions: dict[str, MachineSession]`, no `_monitors` dict.
- Move the monitor mechanism onto the session (RF1). The 1:1 relationship
  between a connected machine and its monitor makes the session the
  natural owner; the cross-cutting `_monitors ↔ _machines` parity
  invariant disappears.
- Preserve the `MachineOperations` facade (RF2). The orchestrator's
  SSH-side constructor signature stays `(repository, operations)` — 2
  ports, no test-fake surface growth at the composition root.
- Keep the domain layer clean (RF3): `MachineSession` Protocol in
  `domain/ports.py`, concrete `SSHMachineSession` in
  `infra/ssh/session.py`; domain entities (`ConnectedMachine`) and
  domain services see only the snapshot via `session.machine`.
- Preserve every behavior contract: connection retry/backoff, monitor
  invariants (disconnect-scope isolation, prior-monitor replacement,
  identity-checked done-callback, pop-before-await ordering), rollback
  on spawn failure, error classification, SFTP per-file isolation.

**Non-Goals:**

- Rewriting the platform adapter layer (`platform/linux.py`,
  `platform/windows.py`, `common.py`) — stays as-is.
- Changing retry/backoff policy (`my_backoff_exc` /
  `my_backoff_sftp` stay functionally identical).
- Changing the `download_outputs` 3-tuple return shape or its error
  classification semantics.
- Adding new operations or new deployment features.
- Changing the DB schema, INI config, CLI surface, or AiiDA plugin.
- Migrating external consumers (there are none besides the AiiDA
  plugin, which does not use these Protocols).
- Reorganizing the tests directory layout beyond import-path fixes
  and fixture rewrites.

## Decisions

### D1. `MachineSession` is a public class with three faces

The session carries:
- **Domain face**: `ip` (read-only), mutable `machine: ConnectedMachine`
  snapshot, transitions `occupy()`/`release()`/`update(machine)`.
- **Connect-time config face** (read-only): `adapter`, `platforms`,
  `data_dir`, `engines_dir`, `tasks_dir`. Adapter-derived: `path`,
  `quote`, `hostname`.
- **Operations face**: base primitives (`run`, `run_full`, `run_bg`,
  `upload`, `open_sftp`, `get_cpu_cores`, `setup_node`, `pgrep`,
  `list_processes`) and the monitor mechanism (`install_monitor`,
  `cancel_monitor`, `_close`).

The session owns its own teardown (`_close()` called only by
`repository.disconnect`): mark closed → cancel monitor → await monitor
→ close conn. The repository stops knowing about monitors.

**Type discipline:** the repository holds the concrete
`SSHMachineSession` internally (`_sessions: dict[str,
SSHMachineSession]`), so `_close()` stays private — it is an
implementation detail only the repository needs. Public-facing methods
(`connect`, `get_session`, `list_connected`, `list_free`) return the
`MachineSession` Protocol type; consumers never need `_close` and never
see it.

**Why three faces on one object:** splitting into a "domain handle" +
"infra handle" pair would force every caller to thread two references.
The session is what callers actually want — its identity, its current
state, the operations on it. Splitting is over-engineering.

**Alternative considered (rejected):** narrow `MachineHandle` Protocol
(domain-only) + concrete `SSHMachineSession` with extras. Rejected: the
operations port methods (`run`, `run_full`, …) need a session-typed
parameter; if the narrow Protocol doesn't include them, the concrete
collaborator must downcast or take the concrete type — re-leaking the
concrete type into call sites. One Protocol, one concrete class.

### D2. `MachineSession` Protocol lives in `domain/ports.py`; concrete `SSHMachineSession` lives in `infra/ssh/session.py` (RF3)

The Protocol describes the operational contract on a connected machine;
it sits next to `MachineRepository` and `MachineOperations` (which already
name `run`, `upload`, `download`, `pgrep` etc.). The concrete class is
infrastructure (imports asyncssh).

**Layering rule preserved:** `domain/model.py`, `domain/engine.py`, and
other domain-only modules see only `ConnectedMachine`. The application
layer (orchestrator + use cases) sees `MachineSession` via the ports
module — this is consistent with today, where application already imports
`MachineOperations` from `domain.ports`.

**Alternative considered (rejected):** put `MachineSession` Protocol in
`infra/ssh/session.py` as a local typing aid. Rejected: the application
layer (orchestrator, use cases) needs to type-annotate session-typed
parameters; if the Protocol lives in infra, application imports infra
for typing — same layering concern with worse ergonomics.

### D3. Monitor mechanism moves onto the session; `_monitors` dict eliminated (RF1)

The session owns `_monitor_task: asyncio.Task[None] | None`. Methods:
- `install_monitor(*, interval, check_factory, on_free)`: cancels prior
  task if present, creates new task, registers identity-checked
  done-callback, stores in `self._monitor_task`. Idempotent on closed
  session: if `_closed`, returns immediately without installing (the
  session is being torn down; no monitor should start).
- `cancel_monitor()`: pops and cancels (no await).
- `_close()` (called only by `repository.disconnect`, concrete class
  only): if already `_closed`, returns immediately (idempotency guard
  against double-call); otherwise sets `_closed = True` synchronously,
  cancels `_monitor_task`, awaits it, closes conn.

`repository.disconnect(ip)` becomes:
```
session = self._sessions.pop(ip, None)
if session is None: return
await session._close()
```

This **reverses `decompose-ssh-gateway` D2** ("monitor mechanism belongs
to the repository"). D2's rationale had two prongs: (a) "the repository
owns both dicts so disconnect cleans both up naturally" and (b) "the
repository does not know about `Engine`; operations do not know about
`_monitors`." Both prongs collapse once a session type exists. For (a):
the session owns its own teardown, so the repository doesn't need a
parallel `_monitors` dict. For (b): the session's `install_monitor`
remains Engine-agnostic — it takes opaque `check_factory` /
`on_free` callbacks (exactly as the repository's version did); only
`OccupancyChecker.start_occupancy_check` knows about `Engine`, and it
composes the same opaque-callback shape onto the session. The
cross-cutting `_monitors ↔ _machines` parity invariant (disconnect must
pop both atomically) is eliminated at the source.

**Alternative considered (rejected):** keep `install_monitor` on the
repository, with the repository holding both `_sessions` and `_monitors`
dicts. Rejected: preserves the parity invariant as ongoing
maintenance burden; the `fix-disconnect-bg-task-leak` archived change
was called in precisely to fix a bug of this kind.

### D4. `MachineOperations` facade stays (RF2); method signatures change to take `MachineSession`

The facade `SSHMachineOperations(repository, log)` is kept. Its method
bodies change: instead of holding base primitives, it resolves a session
via `repository.get_session(ip)` and delegates to session methods.

```python
class SSHMachineOperations:
    def __init__(self, repository, log):
        self._repo = repository
        self._log = log
        from .deployment import TaskDeployer
        from .download import OutputDownloader
        from .occupancy import OccupancyChecker
        self.deploy = TaskDeployer(self._log)
        self.download = OutputDownloader(self._log)
        self.occupancy = OccupancyChecker(self._log)

    async def run(self, session, cmd):
        return await session.run(cmd)

    async def start_task_on_machine(self, session, engine, task, ncpus, engines_dir):
        return await self.deploy.start_task_on_machine(session, engine, task, ncpus, engines_dir)
    # ... etc.
```

The orchestrator's SSH-side constructor signature stays
`(repository, operations)` — 2 ports, unchanged. Test fakes for the
orchestrator's `operations` parameter keep their current surface.

**Why keep the facade:** dissolving it (the original draft's "4 SSH-side
ports" idea) was over-rotation. The facade is a useful boundary; what
was wrong was its internals (reaching into `_get_machine_state`), not
its existence.

**Alternative considered (rejected):** dissolve `MachineOperations`,
have the orchestrator take `(repository, deployer, downloader,
occupancy)` as 4 ports. Rejected: 2× the test-fake surface for no real
gain; the use cases (`allocate_task`, `consume_task`) need to call
operations methods, and having them take 3 collaborator ports instead
of 1 operations port is noise.

### D5. Collaborators become stateless; each takes `(session, …)` per call

```python
class TaskDeployer:
    def __init__(self, log): self._log = log

    async def start_task_on_machine(self, session, engine, task, ncpus, engines_dir) -> bool:
        session.occupy()
        try:
            async with session.open_sftp() as sftp: …
            await session.run_bg(cmd, cwd=…)
        except BaseException:
            if session.is_closed:
                self._log.warning("…already disconnected…")
                raise
            session.update(session.machine.release())
            raise
        return True
```

The rollback path (R1) explicitly checks `session.is_closed` to preserve
today's "already disconnected" warning (`deployment.py:258-265`).

`OccupancyChecker.start_occupancy_check(session, engine)` calls
`session.install_monitor(…)` — no repository reference needed (the last
reason to need one, `install_monitor`, moved onto the session).

**Alternative considered (rejected):** keep collaborators holding a
repository reference for state transitions. Rejected: the session owns
its own state now; routing transitions through the repository would
recreate the wrapper-repository smell in a new shape.

### D6. Orchestrator resolves sessions per-tick (Q-G3)

Today: `machine = self._repository.get_machine_state(ip)` per consumer
tick (`orchestrator.py:432, 470`). Under redesign: `session =
self._repository.get_session(ip)` per tick. Same pattern. Session is a
short-lived per-call reference; the underlying session/conn/monitor has
long lifetime in `_sessions`.

**Why per-tick:** if the orchestrator cached session references across
ticks, the "stale handle" concern (earlier flagged as Q1-phantom)
becomes real — a cached reference survives `disconnect` and silently
mutates an orphaned session. Per-tick `get_session(ip)` returns either
the live session or `None`, and the orchestrator's `MACHINE_GONE` path
already handles `None` cleanly.

**Alternative considered (rejected):** orchestrator caches sessions in
`self._session_cache: dict[str, MachineSession]`. Rejected: dict lookup
is O(1) in single-threaded asyncio — caching provides no measurable
benefit and introduces lifecycle complexity.

### D7. `list_free`/`list_connected` return `list[MachineSession]` (Q-G2)

Callers (`orchestrator.py:212-214, 518-520`; `allocate_task.py:170`)
read `.state`/`.free_since`/`.ip`/`.platform` — all available via
`session.machine`. The allocator immediately operates on the chosen
machine, so passing sessions is cleaner than round-tripping
`get_session(machine.ip)`.

**Why sessions, not snapshots:** the use case (`allocate_task`) calls
`operations.start_occupancy_check(session, engine)` after picking a
machine — it needs the session. Returning snapshots would force a
`get_session` lookup at every consumer; returning sessions is one step.

**Alternative considered (rejected):** return `list[ConnectedMachine]`
snapshots. Rejected: forces every consumer that subsequently calls an
operations method to resolve a session — adds a step at every
allocation/consume site with no benefit.

### D8. Connection-building bits stay in `repository.py`

`MySSHClient`, `DEFAULT_CONN_OPTS`, `_resolve_tunnel` are used only by
`SSHMachineRepository._open_connection`. The repository is the
connection builder; the bits stay there. The session is constructed BY
the repository at connect time and receives its already-open `conn` —
the session does not own connection-building logic.

**Alternative considered (rejected):** move them to `infra/ssh/conn.py`.
Rejected: adds a module for three small symbols used at one site;
`repository.py` at ~150 ln after this change is well under GRACE-lite
limits.

### D9. `make_run_fn` placement unchanged

`make_run_fn(conn, adapter)` (in `platform/run_fn.py` today) is used by
`repository.connect` (build `ConnectedMachine.ncpus`) and by operations
(`get_cpu_cores`, `setup_node`). Under redesign, the second user becomes
`session.get_cpu_cores`/`session.setup_node`. Both `repository.py` and
`session.py` depend on `platform/run_fn.py` — clean DAG, no cycle. No
placement change.

**Alternative considered (rejected):** move `make_run_fn` to
`session.py` (or to `repository.py`). Rejected: both modules use it,
so placing it in either creates a dependency edge the other must cross
— `repository.connect` constructs the session, so `session.py` cannot
depend on `repository.py`; and the session runs commands, so
`repository.py` should not depend on the session for a pure utility.
The current home in `platform/run_fn.py` is the correct DAG root
(adapter-glue that both depend on without coupling to each other).

### D10. Public re-exports from `infra/ssh/__init__.py`

```python
from .exceptions import AllSSHRetryExc, SFTPRetryExc, SSHRetryExc
from .operations import SSHMachineOperations
from .repository import SSHMachineRepository
from .session import SSHMachineSession

__all__ = [
    "AllSSHRetryExc",
    "SSHMachineRepository",
    "SSHMachineOperations",
    "SSHMachineSession",
    "SFTPRetryExc",
    "SSHRetryExc",
]
```

`MachineSession` Protocol is re-exported from `yascheduler.domain` (next
to `MachineRepository` and `MachineOperations`). Collaborator classes
(`TaskDeployer`, `OutputDownloader`, `OccupancyChecker`) are NOT
re-exported (accessed via `SSHMachineOperations.deploy` /
`.download` / `.occupancy`).

## Risks / Trade-offs

### Risk R1: Rollback "already disconnected" detection loses its signal
Today (`deployment.py:254-283`) the rollback branch detects a
mid-deploy disconnect via `state = repo._get_machine_state(ip); if state
is None: log "already disconnected"`. Under redesign the deployer holds
the session directly; `_get_machine_state(ip)` is gone. The naive rewrite
would silently mutate a closed session and lose the warning.

→ **Mitigation:** the rollback path explicitly checks
`if session.is_closed: log "already disconnected"; raise` BEFORE calling
`session.update(...)`. The session's `is_closed` flag is set
synchronously by `_close()` before any await yields control. The
existing `test_ssh_gateway_retry_rollback.py` MUST pass unchanged
against the new rollback shape — pin it in tasks.md as a regression
sentinel.

### Risk R2: Test rewrite is the bulk of the diff and the most likely silent-pass site
`tests/unit/test_ssh_gateway_bg_tasks.py` (the four-invariant regression
suite), `test_ssh_gateway.py` (`TestPropertyHelpers` already removed by
`cleanup-unused-repository-symbols`; the rest poke
`repository._machines`/`_monitors`), `test_ssh_gateway_machine_queries.py`,
`test_ssh_gateway_retry_rollback.py`, `test_ssh_gateway_write_remote_file.py`
all reach into private dict shape. Under redesign: `_machines`/`_monitors`
→ `_sessions`; `_get_machine_state` → `get_session`. A careless rewrite
can silently pass for the wrong reason (the same risk class
`decompose-ssh-gateway` flagged).

→ **Mitigation:** tasks.md enumerates every test-file touch and the
exact replacement. The four monitor invariants (disconnect-scope
isolation, prior-monitor replacement, identity-checked done-callback,
pop-before-await ordering) get explicit new test names that assert
behavior, not dict shape.

### Risk R3 (dismissed): `partial(repo.release, ip)` → `session.release` race
Today `on_free=partial(repo.release, ip)` looks up the IP in the dict
(no-op if popped). Under redesign `on_free=session.release` mutates the
orphaned session's `_machine`. This was flagged as a possible
use-after-close. **Not a risk:** `disconnect` awaits monitor task
cancellation before closing conn; even in the race window where
`on_free` runs synchronously before `task.cancel()` takes effect at the
next await, the mutation is invisible — no one holds the session
reference, `list_connected()` won't return it, the conn is being closed.
Functionally identical to today's silent no-op.

### Risk R4: Disconnect ordering invariant must be preserved explicitly
Today's `disconnect(ip)` pops `_machines[ip]` BEFORE awaiting monitor
cancel (prevents re-entry race re-inserting the cancelled task). Under
redesign, `repository.disconnect(ip)` pops `_sessions[ip]` then calls
`await session._close()`. The pop-before-await property is preserved
**iff** `session._close()` sets `_closed = True` synchronously BEFORE
its first await.

→ **Mitigation:** the `_close()` contract says: first statement is
`self._closed = True`, no awaits before it. Tested by the same bg-tasks
regression suite (disconnect-scope isolation invariant).

### Risk R5: Knowledge graph drift
After this change, `M-SSH-REPOSITORY` annotation list shrinks (lost
methods), new `M-SSH-SESSION` is added with full annotation list,
`M-SSH-OPERATIONS-BASE` annotation list shrinks (primitives moved to
session), `CrossLink`s must be updated.

→ **Mitigation:** the final task updates the knowledge graph atomically
and runs `grace_check.py` to verify.

### Trade-off: indirection layer between operations facade and session
`ops.run(session, cmd)` is now `session.run(cmd)` underneath — one extra
function-call hop vs the old direct path. Negligible at the call volume
(task deployment, periodic checks — not a hot path). Worth keeping the
facade for the orchestrator signature stability.

### Trade-off: more files to navigate
One new file (`infra/ssh/session.py`) and one significant shrink
(`repository.py` 505 → ~150 ln). Net file count: +1. Navigation cost
decreases — a reader looking for "what runs commands on a machine" goes
straight to `session.run`, not via the wrapper labyrinth.

## Migration Plan

Pure refactor, no persisted-state change, no config change. Rollback is
`git revert`. No DB migration, no config migration, no runtime flag.

Atomicity: implemented as a single PR. Steps (reflected as ordered tasks
in `tasks.md`):

1. Introduce `MachineSession` Protocol in `domain/ports.py` and concrete
   `SSHMachineSession` in `infra/ssh/session.py` (carrying everything
   today's `_MachineState` carries plus the primitives that today live
   in `operations/base.py`, plus the monitor mechanism from the
   repository). New code imports from `platform/` only — no circular
   deps.
2. Rewrite `SSHMachineRepository` to use `_sessions: dict[str,
   MachineSession]`; remove `_get_machine_state`, `_monitors`,
   `install_monitor`/`cancel_monitor`, `get_machine_state`,
   `occupy`/`release`/`update_machine`, `get_path`/`get_quote`/
   `get_hostname`, `register_machine`/`keys`/`items`. Update
   `disconnect` to delegate teardown to `session._close()`.
3. Rewrite `SSHMachineOperations` facade: remove base primitives (moved
   to session); each method resolves `session = repo.get_session(ip)`
   and delegates. The three collaborators become stateless.
4. Update `MachineRepository` and `MachineOperations` Protocols in
   `domain/ports.py` (slim repository; change operations signatures to
   take `MachineSession`).
5. Update application-layer consumers (`orchestrator.py`,
   `allocate_task.py`, `consume_task.py`, `deallocate_nodes.py`) and
   CLI (`check_status.py`, `manage_node.py`) and
   `infra/cloud/manager.py` call sites to thread sessions.
6. Update tests: fixtures construct `MachineSession`; patches migrate;
   behavior invariants preserved.
7. Update `infra/ssh/__init__.py` and `infra/ssh/operations/__init__.py`
   re-exports.
8. Update `docs/knowledge-graph.xml`; run `grace_check.py`.

Each step compiles and passes tests; intermediate commits may keep the
old types alive temporarily until step 6/7 removes them.

## Open Questions

All design questions resolved during explore-mode review. Three minor
implementation details deferred to tasks.md:

- **Q-Impl-1:** Does `SSHMachineSession` need a public `is_closed`
  property or only the private `_closed` flag (accessed via a
  Protocol-level `is_closed` property on `MachineSession`)? Decision in
  tasks.md: expose as `@property def is_closed(self) -> bool` on both
  the concrete class and the Protocol — it's part of the public contract
  (rollback path, CLI status display).
- **Q-Impl-2:** For tests that today construct `_MachineState` directly
  (`test_ssh_gateway_bg_tasks.py:215`,
  `test_ssh_gateway_retry_rollback.py:277`), what's the replacement
  constructor signature? Decision: tests construct `SSHMachineSession`
  via a test-only helper or by calling `SSHMachineRepository.connect`
  against a fake conn — both options enumerated in tasks.md, prefer
  the helper to keep unit tests independent of asyncssh.
- **Q-Impl-3:** `test_domain_ports.py`'s `FakeMachineRepository` and
  `FakeMachineOperations` need new fake `MachineSession` types.
  Decision: introduce a single `FakeMachineSession` in
  `tests/unit/test_domain_ports.py` covering all Protocol surface; both
  fakes reference it.

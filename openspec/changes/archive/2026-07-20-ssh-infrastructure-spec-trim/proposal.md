## Why

`openspec/specs/ssh-infrastructure/spec.md` (377 lines, 12 requirements, 22 scenarios) interleaves
actual SHALL requirements with three content kinds that GRACE assigns to code-local contracts,
not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 18+ distinct instances
   enumerating absent code, non-behavior, or negative scope as normative requirements:
   - `The Protocol SHALL NOT include operations on a single machine (exec, SFTP, deploy, download, occupancy-check logic, monitor mechanism) — those are MachineSession.`
   - `connect SHALL NOT take username, port, jump_host, or jump_username parameters — they are read from node.`
   - `MachineRepository is @runtime_checkable. The Protocol SHALL NOT reference Engine.`
   - `The Protocol SHALL NOT expose accessor getters (get_path/get_quote/get_hostname), state-transition wrappers (occupy/release/update_machine), or the monitor mechanism (install_monitor/cancel_monitor) — those are on MachineSession.`
   - `The Protocol SHALL NOT expose get_machine_state — callers use get_session(node_id).machine instead.`
   - `MachineSession is @runtime_checkable. The Protocol SHALL NOT include collection lifecycle, queries, or repository keying — those are MachineRepository.`
   - `MachineSession is @runtime_checkable. The Protocol SHALL NOT reference Engine; install_monitor is generic over Callable[..., Awaitable[bool]] and Callable[..., None].`
   - `SSHMachineSession's base primitives SHALL use the session's own conn and adapter directly — NO hostname-keyed lookup, NO call into the repository.`
   - `setup_node SHALL NOT log the CPU count — the CPU-count log is owned by SSHMachineRepository.connect at the discovery site.`
   - `an info log line with the CPU count is emitted from the repository's connect path, and SSHMachineSession.setup_node SHALL NOT emit a separate CPU-count log`
   - `The orchestrator SHALL NOT cache session references across await boundaries (a stale reference survives disconnect and silently mutates an orphaned session).`
   - `Use cases SHALL receive sessions as parameters or resolve them via repository.get_session(node_id); they SHALL NOT cache sessions.`
   - `The method SHALL NOT raise.` (on `download_outputs`)
   - `When either list is non-empty, the remote directory SHALL NOT be removed.`
   - `Non-SFTP exceptions SHALL propagate immediately during remote file upload; they SHALL NOT be swallowed.`
   - `The system SHALL NOT apply retry to run_bg and SHALL NOT apply SFTP retry to upload or download — these are non-idempotent`
   - `disconnect(node_id) SHALL be scoped to the targeted node — it SHALL not affect monitors for any other machine.`
   - `cancel_monitor() -> None (sync) — cancels the session's monitor (if any); does NOT await`
   - `the instance has a dict of sessions keyed by NodeId and does NOT have _machines or _monitors` (scenario THEN clause)
   Every one is either already asserted by a positive Gherkin scenario or describes a
   non-existent code path dressed up as a normative requirement, or restates a code-shape
   fact (no `_machines`/`_monitors` attribute) that the class body itself is the source of
   truth for. The prose is drift bait.

2. **Design rationale and layering narrative living in the spec** — answers *why the code is
   shaped this way* that belong in `RATIONALE` / `INVARIANTS` / `SCOPE` on the owning entity:
   - `The collection is keyed by NodeId, not by ip. The transport address, login user, port, and jump-leg parameters survive ONLY as fields on node read inside connect; they are NOT separate parameters.` — INVARIANT on `CLASS_SSHMachineRepository` and `METHOD_connect`.
   - The full API-shape restatement of every `connect` / `disconnect` / query / base-primitive
     signature (parameter names, defaults, return types) — the code is the source of truth;
     observable behavior is captured by Gherkin scenarios; restating signatures in prose is
     pure drift bait.
   - `CPU count is invariant for the lifetime of one SSH connection, so repeated get_cpu_cores() calls within the same session SHALL return the cached value without re-executing the remote command.` — RATIONALE on `METHOD_get_cpu_cores`.
   - `The cache lives for the session's lifetime only — a reconnected session starts with an empty cache and re-discovers once. CPU hot-add during a live session goes unobserved until reconnect; an operator who needs the scheduler to see added CPUs without reconnecting SHALL set ncpus explicitly via yasetnode ~N.` — RATIONALE on `METHOD_get_cpu_cores`.
   - The retry-policy justification `these are non-idempotent (a successful remote side-effect followed by a lost client confirmation would produce a duplicate on retry)` — RATIONALE on `run_bg`, `upload`, `OutputDownloader.download_outputs`.
   - `The cache SHALL be primed by SSHMachineRepository.connect after constructing the session, seeding it with the CPU count already read via adapter.get_cpu_cores(...).` — INVARIANT on `METHOD_connect` / `METHOD__prime_ncpus_cache`.
   - `On connection failure, MachineConnectionError(node.node_id, node.hostname, str(err)) SHALL be raised.` — ENSURES on `METHOD_connect` (the raise site already lives there).
   - `constructs and registers an SSHMachineSession keyed by node.node_id` / `asyncssh transport uses node.hostname as the host address, node.username as the login user, node.port as the port, and node.jump_host / node.jump_port / node.jump_username to build the tunnel leg` — INVARIANTS on `METHOD_connect` / `METHOD__open_connection`.
   - `The snapshot carries node_id and platform only, NOT hostname or ncpus` — INVARIANT on `ConnectedMachine` construction site in `METHOD__connect_impl`.
   - `Close is idempotent: if is_closed is already True, it returns immediately. Otherwise it SHALL release the SSH connection and cancel the monitor task.` — ENSURES on `METHOD__close` (already partially there).
   - `The session SHALL own its own teardown, invoked only by SSHMachineRepository.disconnect.` — INVARIANT on `METHOD__close`.
   - `Session.hostname stays sourced from node.hostname ... the session's transport-echo field is sourced from the Node parameter, NOT from ConnectedMachine.hostname — ConnectedMachine no longer carries hostname` — INVARIANT on `CLASS_SSHMachineSession`.
   - The monitor mechanism description `periodically calls check_factory() and calls on_free() when the check returns False. Re-installing cancels the prior monitor before installing the new one. Idempotent on a closed session.` — INVARIANT on `METHOD_install_monitor` (mostly already there).
   - `ProcessInfo (frozen dataclass with fields pid: int, name: str, command: str) SHALL be defined in the platform protocol module.` — INVARIANT/SCOPE on `CLASS_ProcessInfo` and `MODULE_CONTRACT` of `protocol.py`.
   - `ADAPTERS, platform detection, path init, and MAX_SESSIONS SHALL live in the platform package.` — MODULE_CONTRACT SCOPE on `platform/__init__.py` (already there).
   - `Platform-specific modules SHALL live in the SSH platform package.` — MODULE_CONTRACT SCOPE.
   - `Platform modules SHALL import Engine, EngineRepository, and Deploy* types from yascheduler.domain.` — MODULE_CONTRACT DEPENDENCIES on `platform/linux.py`, `platform/windows.py`.
   - The rollback defensiveness narrative on `start_task_on_machine` (`If the session is closed ... log a warning and re-raise without rollback. If the session is open but not BUSY ... Otherwise log an info line and re-raise.`) — already lives as `BLOCK_rollback_busy` comment in `deployment.py`; the spec restates it.
   - `This requirement SHALL govern the session-level occupancy marker only; the DB task status and orchestrator's in-memory mark_running() are owned by the caller and unaffected by this rollback.` — INVARIANT on `METHOD_start_task_on_machine`.

3. **Out-of-capability / duplicated orchestrator guidance** — the entire `Session is returned
   by repository and resolved per-tick by the orchestrator` requirement mixes one
   ssh-infrastructure concern (return-type of `connect`/`list_free`/`list_connected`/
   `get_session`) with orchestrator-side caching guidance that already lives in
   `openspec/specs/orchestrator/spec.md` (the
   `repository.get_session(task.allocated_node_id)` per-tick resolution is asserted by the
   orchestrator spec's consumer deploy scenario). The orchestrator-side "SHALL NOT cache
   session references across await boundaries" / "Use cases SHALL NOT cache sessions"
   sentences are duplicated layering guidance; they belong as `INVARIANTS` on the
   orchestrator and use-case collaborators (handled in `orchestrator-spec-trim`), not in the
   ssh-infrastructure spec. The return-type SHALL statements stay (they are ssh-infra
   observable behavior); the orchestrator-resolution prose is removed.

In parallel, the code under `yascheduler/infra/ssh/` violates the GRACE Python rule ("if an
entity is annotated by markup, it must always be wrapped in a region"):

- `MyPureWindowsPath` (in `platform/windows.py`) carries an internal `METHOD__parse_args`
  region but no enclosing `CLASS_MyPureWindowsPath`.
- `MySSHClient` (in `repository.py`) is a public class with no contract region.
- `RemoteMachineAdapter` (in `platform/adapters.py`) — frozen public dataclass, no contract.
- `ProcessInfo` (in `platform/protocol.py`) — frozen public dataclass, no contract.
- `PlatformGuessFailedError` (in `platform/exceptions.py`) — public exception, no contract.
- The 6 callable `Protocol` classes in `platform/protocol.py` (`RunCallable`,
  `RunBgCallable`, `OuterRunCallable`, `ListProcessesCallable`, `PgrepCallable`,
  `SetupNodeCallable`) — public Protocols, no contract.
- The non-trivial private helper `_build_tunnel_options` in `repository.py` lives under the
  `MODULE_CONTRACT` with no entity-level contract region.
- The non-trivial private method `_prime_ncpus_cache` in `session.py` lives under
  `CLASS_SSHMachineSession` with no entity-level contract region.
- The base-primitive async methods on `SSHMachineSession` (`run`, `run_bg`, `upload`,
  `open_sftp`, `pgrep`, `list_processes`) are public surface and currently unwrapped.
- The existing `CLASS_SSHMachineRepository`, `CLASS_SSHMachineSession`, `CLASS_TaskDeployer`,
  `CLASS_OutputDownloader`, `CLASS_OccupancyChecker`, and their `METHOD_*` regions hold
  `PURPOSE` only — the rationale/invariants/scope that should accompany the code is missing
  because it currently sits in the spec.

## What Changes

- **MODIFIED `ssh-infrastructure`**: rewrite all 12 requirements to carry only behavioral
  contracts (SHALL statements + Gherkin scenarios). Remove the 18+ invented `SHALL NOT`
  enumerations of absent code, the design rationale / layering narrative / signature
  restatements listed above, and the duplicated orchestrator-side caching guidance. Every
  observable behavioral scenario (22) survives unchanged (the `__init__ does NOT have
  _machines or _monitors` scenario THEN is rewritten to assert the positive — "the instance
  has a dict of sessions keyed by `NodeId` as its only collection attribute"; the remaining
  21 scenarios are unchanged in their observable assertions). No requirement is added,
  removed, merged, or split; the 12 requirement headers stay identical so OpenSpec
  recognizes the MODIFIED operation.
- Wrap the missing `CLASS_*` regions required by the GRACE Python rule on the 10
  currently-unwrapped public classes / Protocols / dataclasses / exceptions:
  `MySSHClient` (in `repository.py`), `MyPureWindowsPath` (in `platform/windows.py` — the
  nested `METHOD__parse_args` stays INSIDE the new `CLASS_*`), `RemoteMachineAdapter` (in
  `platform/adapters.py`), `ProcessInfo` (in `platform/protocol.py`), the 6 callable
  `Protocol` classes in `platform/protocol.py` (`RunCallable`, `RunBgCallable`,
  `OuterRunCallable`, `ListProcessesCallable`, `PgrepCallable`, `SetupNodeCallable`),
  `PlatformGuessFailedError` (in `platform/exceptions.py`).
- Add `METHOD_*` regions on the unwrapped non-trivial methods/helpers: `_build_tunnel_options`
  (free function in `repository.py` — wrapped as `FUNC__build_tunnel_options`),
  `_prime_ncpus_cache` (in `session.py`), and the 6 base-primitive async methods on
  `SSHMachineSession` (`run`, `run_bg`, `upload`, `open_sftp`, `pgrep`, `list_processes`).
  Trivial one-line properties (`hostname`, `machine`, `is_closed`, `adapter`, `platforms`,
  `data_dir`, `engines_dir`, `tasks_dir`, `path`, `quote`) and trivial `__init__` one-liners
  (`SSHMachineRepository.__init__`, `OutputDownloader.__init__`, `TaskDeployer.__init__`,
  `OccupancyChecker.__init__`) stay unwrapped per the GRACE proportional rule.
- Enrich existing `MODULE_CONTRACT`, `CLASS_*`, `FUNC_*`, and `METHOD_*` regions across
  `yascheduler/infra/ssh/**/*.py` with the rationale/invariants/scope that leaves the spec,
  each in its correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `SSHMachineRepository` is keyed by `NodeId` not IP; transport identity is read from
    `Node` inside `connect`, never from separate parameters; `ConnectedMachine` snapshot
    carries `node_id` + `platform` only; the CPU-core cache lives for the session lifetime
    only and is primed by `SSHMachineRepository.connect`; `SSHMachineSession.hostname` is
    sourced from the `Node` parameter, not from `ConnectedMachine`; retry is applied only to
    idempotent ops — `get_cpu_cores` cache-miss and connection establishment; non-idempotent
    `run_bg` / `upload` / `download` are single-attempt; `cancel_monitor` does not await;
    `disconnect` is scoped to the targeted node only).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g. why the
    collection is `NodeId`-keyed; why transport identity lives on `Node` and not on
    `connect`'s parameter list; why retry is suppressed on non-idempotent ops; why the
    CPU-core cache is per-session and not per-process; why `install_monitor` is generic over
    callables instead of referencing `Engine`).
  - `SCOPE` declares the entity's functional boundaries with explicit `NOT:` exclusions
    where useful (e.g. `MachineRepository` SCOPE NOT: single-machine operations, monitor
    mechanism — those are `MachineSession`).
  - `REQUIRES` / `ENSURES` carry preconditions and postconditions (e.g. `METHOD_connect`
    ENSURES: on transport failure raises `MachineConnectionError(node.node_id,
    node.hostname, str(err))`; `METHOD__close` ENSURES: idempotent — `is_closed` set
    synchronously before any await).
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`, `INVARIANTS`,
  `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`, `REQUIRES`, `ENSURES`. No
  `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no `RAISES:`, no free-form labels. The
  spec's removed `SHALL NOT` sentences do NOT become a `SHALL NOT:` contract field — they
  become an `INVARIANTS` entry stating the positive contract, or a `RATIONALE` Q/A if the
  rationale is the valuable part.
- Every `CLASS_*` region encloses the FULL class body — the `class` line (and any
  `@dataclass(...)` decorator), the docstring, every field, every `__init__` line, every
  `self.<attr>` assignment — through the trailing blank line before the next region marker.
  Every `FUNC_*` / `METHOD_*` region encloses the decorator (if any), the `def`/`async def`
  line, the body, every nested `BLOCK_*` region, and the trailing blank line. No region
  closes before its entity ends; nesting is allowed — `METHOD_*` and inner `BLOCK_*`
  regions live INSIDE the enclosing `CLASS_*`; the `CLASS_*` `# endregion` comes after the
  last nested `# endregion`.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `ssh-infrastructure`: requirements slimmed to SHALL statements and behavior scenarios;
  invented `SHALL NOT` negative-space language (18+ instances), design rationale, layering
  narrative, signature restatements, and the duplicated orchestrator-side caching guidance
  relocated out of the spec text and into GRACE code contracts across
  `yascheduler/infra/ssh/**/*.py`. No SSH behavior, signature, scenario, INI key, DB
  schema, public API, log format, retry policy, or import path is added, removed, or
  changed.

## Impact

- **Specs**: `openspec/specs/ssh-infrastructure/spec.md` rewritten — every requirement
  trimmed to behavioral SHALL + scenarios; pre/post scenario count compared and MUST remain
  22 → 22 (the `__init__ does NOT have _machines or _monitors` scenario THEN is rewritten
  positively — same observable assertion; the remaining 21 scenarios are unchanged).
  `openspec validate --all --json` must still pass after the change.
- **Code (markup only, no logic)**:
  `yascheduler/infra/ssh/repository.py`,
  `yascheduler/infra/ssh/session.py`,
  `yascheduler/infra/ssh/operations/deployment.py`,
  `yascheduler/infra/ssh/operations/download.py`,
  `yascheduler/infra/ssh/operations/occupancy.py`,
  `yascheduler/infra/ssh/platform/protocol.py`,
  `yascheduler/infra/ssh/platform/adapters.py`,
  `yascheduler/infra/ssh/platform/exceptions.py`,
  `yascheduler/infra/ssh/platform/windows.py`,
  `yascheduler/infra/ssh/platform/linux.py`,
  `yascheduler/infra/ssh/platform/detect.py`,
  `yascheduler/infra/ssh/platform/common.py`,
  `yascheduler/infra/ssh/platform/paths.py`,
  `yascheduler/infra/ssh/platform/run_fn.py`,
  `yascheduler/infra/ssh/platform/checks.py`,
  `yascheduler/infra/ssh/keys.py`,
  `yascheduler/infra/ssh/__init__.py`,
  `yascheduler/infra/ssh/operations/__init__.py` — existing `MODULE_CONTRACT`/`CLASS_*`/
  `FUNC_*`/`METHOD_*` regions enriched with `INVARIANTS`/`RATIONALE`/`SCOPE`/`REQUIRES`/
  `ENSURES`; new `CLASS_*` regions added for the 10 currently-unwrapped public entities;
  new `FUNC_*`/`METHOD_*` regions added for the unwrapped non-trivial helpers and base
  primitives. No code logic, signature, decorator, docstring semantics, or import changes.
  Code contracts absorb what leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the acceptance
  criteria; existing SSH unit and integration tests already assert them
  (`tests/unit/test_ssh_gateway.py`,
  `test_ssh_gateway_connect.py`,
  `test_ssh_gateway_download_outputs.py`,
  `test_ssh_gateway_machine_queries.py`,
  `test_ssh_gateway_bg_tasks.py`,
  `test_cloud_alloc_session_lifecycle.py`,
  `test_allocate_task_node_pairing.py`,
  `test_consume_task.py`,
  `tests/integration/test_ssh_gateway.py`,
  `tests/e2e/test_consume_retry.py`).
  A passing `uv run pytest -m unit` and `-m integration` run after the change is the
  regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key, DB schema,
  public API, or log-format change in the diff. The diff is `# region`/`# endregion`
  markup + comment-field enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `ssh-infrastructure` spec. Other specs
  (`cloud` is handled by `cloud-spec-trim`; `orchestrator` by `orchestrator-spec-trim`;
  `cli` by `cli-spec-trim`; `use-cases`, `domain-*`, etc.) are explicitly out of scope.
  Follows the pattern set by `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`, `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`, `2026-07-18-slim-domain-ports-spec`,
  `cloud-spec-trim`, `orchestrator-spec-trim`, and `cli-spec-trim`.
- **Non-goals**:
  - No change to any SSH behavior, retry policy, connection lifecycle, monitor mechanism,
    CPU-cache semantics, occupancy-check logic, deploy/spawn rollback, download
    error-classification, or log marker.
  - No spec split; all trimmed requirements remain in the `ssh-infrastructure` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No rewrite of `yascheduler/domain/ports.py` (`MachineRepository` / `MachineSession`
    Protocols — already trimmed by `2026-07-18-slim-domain-ports-spec`); only the
    `ssh-infrastructure` capability spec and `yascheduler/infra/ssh/**/*.py` are touched.
  - No markup additions outside `yascheduler/infra/ssh/**` (orchestrator-side caching
    INVARIANTS are handled by `orchestrator-spec-trim`).

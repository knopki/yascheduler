## Context

`yascheduler/infra/ssh/platform/protocol.py` is the contracts module for the
SSH platform layer: retry-exception tuples, `Protocol` classes for callable
shapes (`RunCallable`, `RunBgCallable`, `OuterRunCallable`,
`ListProcessesCallable`, `PgrepCallable`, `SetupNodeCallable`), and type
aliases (`SSHCheck`, `QuoteCallable`, `GetCPUCoresCallable`). Two of its
`Protocol` classes are now dead weight:

- `PNode` (fields `ip: str, username: str`) — zero consumers outside its own
  re-export. The canonical node identity type is the domain `Node` dataclass
  (`yascheduler/domain/model.py:373`, fields `ip, ncpus, enabled, cloud,
  username, port`), a strict superset used by `NodeRepository`, the
  application layer, persistence, and tests.
- `PProcessInfo` (fields `pid: int, name: str, command: str`) — a structural
  shadow of the `ProcessInfo` frozen dataclass that lives one file over in
  `common.py`. It exists solely to let `ListProcessesCallable` and
  `PgrepCallable` annotate `AsyncGenerator[..., None]` return types without
  `protocol.py` importing from `common.py` (which already imports
  `QuoteCallable` from `protocol.py`).

Precedent: the `engine-to-domain-frozen` change already deleted `PEngine` and
`PEngineRepository` from this same module, replacing them with the domain
`Engine`/`EngineRepository` types. The `platform-adapters` spec records that
removal as scenarios. This change applies the same pattern to `PProcessInfo`
and `PNode`.

Constraint: public API stability (AGENTS.md). `ProcessInfo` is in the package
`__all__` (`yascheduler/infra/ssh/platform/__init__.py:139`); its public name
must not change. Only its source module within the package changes.

## Goals / Non-Goals

**Goals:**

- Make `protocol.py` the single canonical location for the platform layer's
  data contracts (both callable shapes and the `ProcessInfo` struct).
- Remove `PProcessInfo` and `PNode` Protocol classes and their re-exports.
- Preserve the exact public surface `yascheduler.infra.ssh.platform.ProcessInfo`
  under the same name.
- Preserve all runtime behavior — pure type relocation + dead code removal.
- Keep the `protocol ↔ common` import graph acyclic.

**Non-Goals:**

- Touching the domain `Node` dataclass or its consumers.
- Refactoring the callable `Protocol` classes (`RunCallable`,
  `ListProcessesCallable`, etc.) — they stay as-is.
- Touching `run`/`run_bg` behavior in `common.py` — only the `ProcessInfo`
  class leaves that file.
- Re-export reorganization beyond the two removed names and the one moved
  import source.
- Any DB, config, CLI, or SSH-protocol behavior change.

## Decisions

### Decision 1: Move `ProcessInfo` into `protocol.py` (Variant B)

**Choice:** Relocate the frozen dataclass
`ProcessInfo(pid: int, name: str, command: str)` from `common.py` to
`protocol.py`. Delete `PProcessInfo`. Update all consumers to import
`ProcessInfo` from `.protocol` (or the unchanged package re-export) and to
annotate generators as `AsyncGenerator[ProcessInfo, None]`.

**Alternatives considered:**

- **Variant A — status quo.** Keep `PProcessInfo` as the cycle-breaker. Pros:
  zero churn. Cons: two definitions of the same three fields; `protocol.py`
  is not the single contracts location; the `P`-prefix Protocol is a
  structural duplicate, not a behavioral contract. Rejected because moving
  the dataclass breaks the cycle *and* collapses the duplication.
- **Variant C — type alias `PProcessInfo = ProcessInfo` in `protocol.py`.**
  Rejected: the alias still imports `ProcessInfo` from `common.py`,
  recreating `protocol → common`, which is exactly the cycle `PProcessInfo`
  was introduced to avoid. No benefit over Variant B.

**Rationale:** `protocol.py` already hosts every other contract for this
layer. Owning the one data struct it references aligns the module with its
stated PURPOSE ("Protocol definitions for process info, SSH checks, and
adapters"). After the move, `common.py` imports `QuoteCallable` from
`protocol.py` and nothing flows back — the graph stays acyclic.

### Decision 2: Delete `PNode` with no replacement

**Choice:** Remove the `PNode` Protocol entirely. No replacement, no alias.

**Rationale:** `PNode` has zero consumers outside its own re-export (verified
by ripgrep across `yascheduler/` and `tests/`). The gateway's `connect`
signature takes `ip` and `username` as separate parameters; no code path
passes a node-like struct to a function typed against `PNode`. The domain
`Node` dataclass is the canonical node identity type and is already used
everywhere a node identity is needed. `PNode` adds no value.

### Decision 3: Keep `ProcessInfo` in the public `__all__` under the same name

**Choice:** `yascheduler/infra/ssh/platform/__init__.py` continues to export
`ProcessInfo` from `__all__`. Only the internal import source changes:
`from .common import ProcessInfo, run, run_bg` becomes
`from .protocol import ProcessInfo` plus `from .common import run, run_bg`.

**Rationale:** AGENTS.md pins the public package surface. External consumers
importing `from yascheduler.infra.ssh.platform import ProcessInfo` see no
difference. `PProcessInfo` and `PNode` are removed from `__all__` and from the
protocol re-export block — verified zero external references.

### Decision 4: Spec deltas under `platform-adapters` and `ssh-gateway`

**Choice:**

- `platform-adapters` (MODIFIED existing requirement "Platform code
  relocated"): add scenarios asserting `PProcessInfo` and `PNode` are absent
  from `protocol.py`, and that `ProcessInfo` is defined in `protocol.py` and
  imported from there (not `common.py`) by `linux.py`, `windows.py`, and the
  package `__init__.py`.
- `ssh-gateway` (MODIFIED existing requirement "SSHMachineGateway implements
  MachineGateway"): add a scenario asserting `pgrep` and `list_processes`
  return `AsyncGenerator[ProcessInfo, None]` (was `PProcessInfo`). `ProcessInfo`
  is re-exported via the package `yascheduler.infra.ssh.platform`.

**Rationale:** These are the two capabilities named in the proposal. No new
capability is introduced; behavior is unchanged at runtime, but the
contract-level type names change, so the existing requirements are modified
rather than added.

## Risks / Trade-offs

- **[Risk] A consumer outside the repo imports `PProcessInfo` or `PNode`
  directly.** → Mitigation: ripgrep confirms zero references in `yascheduler/`
  and `tests/`. The AiiDA plugin and Python client (`yascheduler` public API)
  do not re-export these names. `PProcessInfo`/`PNode` were never in any
  documented public API surface. Acceptable.
- **[Risk] Import cycle reappears if a future contract in `protocol.py`
  references a `common.py` symbol.** → Mitigation: after this change,
  `protocol.py` depends only on `asyncssh`, `yascheduler.domain`
  (`TYPE_CHECKING`), and stdlib. `common.py` depends on `protocol.py`
  (`QuoteCallable`) and `asyncssh`. The edge is one-way and stable. Adding a
  contract that needs `run`/`run_bg` would be the trigger — at that point the
  contract belongs in `common.py` or a new module, not `protocol.py`.
- **[Risk] `MagicMock(spec=ProcessInfo)` behaves differently from
  `MagicMock(spec=PProcessInfo)` in tests.** → Mitigation: `ProcessInfo` is a
  frozen dataclass; `spec=ProcessInfo` restricts the mock to the dataclass's
  attributes (`pid`, `name`, `command`), which is exactly what
  `spec=PProcessInfo` did via the Protocol. Test behavior is preserved; the
  five sites in `tests/unit/test_ssh_gateway.py` are updated mechanically.
- **[Trade-off] `protocol.py` gains a `dataclasses` import and one
  dataclass.** It loses two Protocol classes (net size reduction, and the
  module's import graph simplifies). Acceptable.
- **[Trade-off] `common.py` shrinks to just `run`/`run_bg`.** Its
  MODULE_CONTRACT SCOPE and MODULE_MAP narrow. This is honest — the module is
  now purely behavioral. Acceptable.

## Migration Plan

Single-PR, no runtime migration. Steps (each step that touches a governed
file also updates its GRACE-lite MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY
markers in the same commit; `docs/knowledge-graph.xml` is updated in step 1
and kept in sync through the rest):

1. Add `ProcessInfo` dataclass to `protocol.py`; remove `PProcessInfo` and
   `PNode` classes; update `protocol.py` GRACE markers and
   `docs/knowledge-graph.xml` `M-PLATFORM-PROTOCOL` annotations.
2. Remove `ProcessInfo` class and now-unused `dataclass` import from
   `common.py`; update its GRACE markers.
3. Update `linux.py`, `windows.py` imports and return-type annotations;
   update their GRACE markers.
4. Update `__init__.py` re-export block and `__all__`; update its GRACE
   markers.
5. Update `gateway.py` import and annotations; update its GRACE markers.
6. Update `tests/unit/test_ssh_gateway.py` (5 sites); update its GRACE
   markers if it carries any (the test file is governed and may carry
   MODULE_CONTRACT/MODULE_MAP — update if present).
7. Run `uv run pytest -m unit`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run lint-imports`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.

**Rollback:** `git revert` the single commit. No state, no schema, no config
to roll back.

## Open Questions

None. All design commitments are pinned by the explore brief and confirmed
by the proposal review.
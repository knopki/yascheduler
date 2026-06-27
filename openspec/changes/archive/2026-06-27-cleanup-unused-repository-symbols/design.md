## Context

`proposal.md` (frozen) establishes that nine methods on
`SSHMachineRepository` and six of their counterparts on the
`MachineRepository` Protocol in `domain/ports.py` have zero production
callers and will be removed. The change is a pure narrowing — no caller
migrates, no signature changes, no behavior change. This design captures
the small number of real implementation decisions worth pinning before
coding. The follow-up `session-based-machine-handle` change will do
the structural redesign; landing this cleanup first keeps that diff
honest (see proposal's "Why").

The current `MachineRepository` Protocol is `@runtime_checkable`. Any
class that satisfied the old Protocol still satisfies the narrowed one
(removing requirements is structurally non-breaking). The
`SSHMachineRepository` concrete class is the only implementer; it is
the same code that loses the methods.

Existing relevant specs: `ssh-machine-repository` (full method
inventory in the `MachineRepository port` and `SSHMachineRepository
implements MachineRepository` requirements), `domain-ports` (mirror of
the Protocol surface).

External constraints (unchanged):
- Python ≥ 3.9, `pip` and `uv` compatible, PEP 621 only.
- No new runtime dependencies.
- No DB schema change, no INI config change, no user-visible CLI change.
- GRACE-lite `docs/knowledge-graph.xml` MUST stay in sync (the
  `M-SSH-REPOSITORY` module's `<fn-*>` annotations for the removed
  symbols are deleted in the same change; `grace_check.py` must pass).

## Goals / Non-Goals

**Goals:**

- Remove the nine zero-caller methods and matching Protocol/test surface
  atomically (one change, one PR).
- Preserve the `@runtime_checkable` narrowing guarantee: any old-shape
  implementer still satisfies the new Protocol.
- Keep the diff purely subtractive in production code — no rewrite of
  surviving symbols.
- Land before `session-based-machine-handle` so that change's `tasks.md`
  does not reference removed method names.

**Non-Goals:**

- Touching any symbol with at least one production caller
  (`_get_machine_state`, `get_path`, `get_quote`, `get_hostname`,
  `occupy`/`release`/`update_machine`, `install_monitor`/`cancel_monitor`,
  etc.). Those belong to the follow-up entity-handle redesign.
- Restructuring `SSHMachineRepository` into anything different. The
  class shape, the `_machines`/`_monitors` dicts, the connect path, the
  disconnect ordering — all unchanged.
- Migrating removed-method tests to alternative APIs. The removed tests
  die with the methods they exercised; alternatives like
  `_get_machine_state` are themselves slated for replacement, and
  migrating tests onto them would create churn the follow-up change
  then has to undo.
- Touching `SSHMachineOperations`, the operations collaborators, or
  anything outside `repository.py` / `ports.py` / the listed tests.

## Decisions

### D1. Atomic single-PR removal; no transitional deprecation

The methods have zero production callers (audit-verified twice — once
in `explore-brief.md`, once by independent `k-reviewer-fast` re-audit).
There is no consumer to deprecate against. A transitional path (keep
methods one release, remove next) would require inventing a
`DeprecationWarning` policy this codebase does not have, for an internal
symbol nobody calls.

**Alternative considered (rejected):** transitional deprecation with
`DeprecationWarning`. Rejected: zero callers means zero warning
recipients; pure noise.

### D2. Protocol narrows; concrete class narrows; tests narrow — all in the same PR

The `MachineRepository` Protocol in `domain/ports.py`, the concrete
`SSHMachineRepository` in `infra/ssh/repository.py`, and the test fake
`StubMachineRepository` in `tests/unit/test_domain_ports.py` all lose
the same six Protocol methods in the same PR. The concrete class additionally loses the
three concrete-only test hooks (`keys`, `items`, `register_machine`).
The removed test methods in `test_ssh_gateway.py` (`TestPropertyHelpers`
+ `test_keys`/`test_items`/`test_register_machine`) are deleted.

**Why same-PR lockstep:** leaving the Protocol declaring methods the
concrete class no longer implements would break `@runtime_checkable`
semantics for any future implementer and produce an inconsistent
contract. The `FakeMachineRepository` test fake must mirror the
Protocol or fail at import.

**On "lockstep" vs "ordered tasks":** the per-step ordering in
`tasks.md` (concrete → Protocol → fake → tests → e2e → KG) is
authoring order for review clarity, NOT a contract that each
intermediate commit is independently runtime-checkable-consistent.
No test in the suite performs `isinstance(SSHMachineRepository(),
MachineRepository)`, so an intermediate commit with the concrete
narrowed but the Protocol not-yet is harmless. The PR as a whole
restores consistency; reviewers evaluate the PR as a whole.

### D3. `test_full_cycle.py` engines_dir migration — read from config, not accessor

The single e2e call `repository.get_engines_dir(ssh_container["host"])`
at `tests/e2e/test_full_cycle.py:64` was a round-trip check: it read
back the value that the same test had passed to `repository.connect(...)`
via `remote_defaults.engines_dir` at line 59. Replacing the accessor
call with the in-scope `remote_defaults.engines_dir` (or
`config.remote.engines_dir` per the test's actual variable name —
verified in scope at the call site) preserves the assertion intent:
the test still compares the value the daemon wired in.

**Alternative considered (rejected):** replace with a direct
`repository._machines[ip].engines_dir` reach-through. Rejected: the
follow-up change renames `_machines` and changes its value type; the
config read is stable across both changes.

### D4. `register_machine` deletion — no replacement test hook

`register_machine` was a back-door test hook allowing fixture code to
inject `_MachineState` into `_machines` without going through `connect`.
Its only caller is `test_ssh_gateway.py:649`. Tests needing
pre-populated state already use direct
`repository._machines[ip] = replace(...)` pokes
(e.g., `test_ssh_gateway_bg_tasks.py:215`,
`test_ssh_gateway_retry_rollback.py:277`). Removing `register_machine`
eliminates the back-door; the test that calls it is removed with it.

**Why not preserve as a documented test hook:** the follow-up
`session-based-machine-handle` change replaces `_machines` with
`_sessions` of a different value type; the hook would have to be
rewritten then anyway. Removing it now is strictly cleaner.

### D5. Knowledge-graph annotation cleanup in the same change

`docs/knowledge-graph.xml` carries `<fn-*>` annotations under
`M-SSH-REPOSITORY` for each of the removed methods. These annotations
are deleted in the same PR. `grace_check.py` MUST pass after the edit.
This is mechanical: the XML structure does not change, only the
annotation list narrows.

### D6. Ordering constraint vs `session-based-machine-handle`

This change MUST land before `session-based-machine-handle`. The
follow-up's `tasks.md` will reference the surviving method inventory;
if dead methods are still present, the follow-up's diff would
interleave mechanical deletions with semantic rewrites, defeating the
purpose of splitting them. If the two changes are attempted in
parallel branches, `infra/ssh/repository.py` and `domain/ports.py`
will conflict on every removed-method hunk.

## Risks / Trade-offs

### Risk: Hidden caller introduced between audit and merge
The audit (`rg` over `yascheduler/`) is point-in-time. If a parallel
branch adds a caller to one of the nine methods, this change would
silently remove that caller's target. The `@runtime_checkable`
narrowing does NOT catch this — `runtime_checkable` only checks
presence of attributes, not calls.

→ **Mitigation:** the change is reviewed and merged against
`main`/`master` HEAD; CI runs the full test suite including
integration/e2e. Any caller introduced in the same release cycle would
surface as an AttributeError during test execution. The risk window is
the review-to-merge interval.

### Risk: `FakeMachineRepository` drift in `test_domain_ports.py`
If the test fake has methods beyond the Protocol surface that other
tests transitively use, removing them would cascade.

→ **Mitigation:** D2 mandates same-PR editing; the design's tasks
explicitly enumerate the fake edits (the test fake in
`tests/unit/test_domain_ports.py` is the class `StubMachineRepository`,
not a generic "fake"). Reviewer re-audit during the
specs/tasks phase verifies no transitive dependency.

### Risk: `ssh-machine-repository/spec.md` Scenario references a deleted method
The existing `ssh-machine-repository/spec.md` Scenario
"Register and list connected machines" uses
`register_machine("10.0.0.1", state)` in its WHEN clause
(`spec.md:70-73`). If the delta spec deletes the
`register_machine` requirement but leaves the Scenario referencing it,
spec and code drift apart.

→ **Mitigation:** the `ssh-machine-repository` delta spec MUST delete
this Scenario alongside the `register_machine` inventory entry. The
tasks list this explicitly. Reviewer re-checks during specs phase.

### Trade-off: Dead-code removals are sometimes signals of design issues
Removing `get_conn` (which exists with full reconnect logic but is
never called) hides the question "should we be reconnecting?" The
follow-up `session-based-machine-handle` change re-derives the
reconnect story as part of the session lifetime design; the removal
here does not lose the question, only the dead implementation.

## Migration Plan

Pure deletion refactor — no persisted-state change, no config change,
no runtime flag. Rollback is `git revert`. Operators do nothing
differently before/after deploy.

Atomicity: the change is implemented as a single PR. The
ordered tasks in `tasks.md` (concrete class → Protocol → test fake →
test removals → e2e migration → knowledge-graph) compile and pass
tests at each step; the final commit removes nothing further.

## Open Questions

(none — all decisions captured above; Q1/Q2/Q3 from `explore-brief.md`
resolved in D2/D4 and the Capabilities section of `proposal.md`.)

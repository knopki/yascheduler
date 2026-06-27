# Review Log — cleanup-unused-repository-symbols

## proposal Round 1 — 2026-06-27

### Verdict: APPROVE WITH NOTES (k-reviewer-fast)

Zero-caller claim independently verified via `rg`. Deferred-to-later
list spot-checked — no under-cleaning. Capabilities section uses valid
existing spec names. `M-SSH-REPOSITORY` is the correct knowledge-graph
module ID. `test_full_cycle.py` migration feasible (`remote_defaults.engines_dir` in scope at line 64). Every explore-brief commitment
reflected in proposal.

### 🟡 Addressed (minor)

- **Impact file-count mismatch (proposal.md:79)**: claimed "4 files"
  but the section listed 5. Fixed: "~150 ln across 5 files" with
  explicit file enumeration.
- **Vague `register_machine`-based fixture setup claim (proposal.md:31)**:
  the `repository()` fixture does NOT use `register_machine`; tests
  requiring pre-populated state already poke
  `repository._machines[ip] = state` directly. Fixed: replaced
  "fixture setup" with an explicit note clarifying no fixture uses
  `register_machine`.

### 🔴 Outstanding

(none)

### Result

proposal.md frozen. Proceeding to design.md.

## design Round 1 — 2026-06-27

### Verdict: APPROVE WITH NOTES (k-reviewer-fast)

All six decisions (D1-D6) sound. D3 test migration claim verified:
`config.remote.engines_dir` is the in-scope identifier at
`test_full_cycle.py:48,59,64`. D4 `register_machine` single-caller
claim verified. D5 knowledge-graph annotation claim verified — all 9
`<fn-*>` entries exist under `M-SSH-REPOSITORY` (lines 935, 943-944,
947-949, 954-956). D6 ordering rationale correct. Goals/Non-Goals
faithful to proposal; no scope creep.

### 🟡 Addressed (minor)

- **D2 "lockstep" vs Migration Plan "ordered steps" tension**:
  clarified that per-step ordering is authoring order for review, not
  a runtime-checkable-consistency contract per commit. No test does
  `isinstance(SSHMachineRepository(), MachineRepository)`, so
  intermediate commits are harmless; PR-as-a-whole restores
  consistency.
- **Missing risk: `ssh-machine-repository/spec.md:70-73` Scenario
  references `register_machine`** — added explicit risk + mitigation:
  the `ssh-machine-repository` delta spec MUST delete this Scenario
  alongside the `register_machine` inventory entry.

### 🔴 Outstanding

(none)

### Result

design.md frozen. Proceeding to specs.

## specs Round 1 — 2026-06-27

### Verdict: PASS (k-reviewer-fast)

All method inventories correct. All 15 scenario lines use exactly 4
hashtags. All three MODIFIED headers match originals exactly.
`MachineRepository port` Note mentions only `_get_machine_state`.
`SSHMachineRepository implements` lists only `_get_machine_state` (down
from 4 implementation-only methods). `get_conn` paragraph removed from
`SSHMachineRepository implements` requirement. domain-ports delta drops
the 6 deleted Protocol methods from the `MachineRepository` bullet and
leaves `MachineOperations` bullet unchanged. Only the
`Register and list connected machines` scenario is removed (per D2).

### 🟡 Addressed (minor)

- **Typo in `_get_machine_state` signature in Note paragraph**:
  `_get_machine_state(ip:` → `_get_machine_state(ip)`. Fixed.

### 🔴 Outstanding

(none)

### Result

specs frozen. Proceeding to tasks.md.

## tasks Round 1 — 2026-06-27

### Verdict: PASS (k-reviewer-fast)

All proposal and design decisions covered. Task ordering correct
(pre-flight audit first; KG cleanup after code). Each task ≤2h.
All AGENTS.md validators present. No hidden coupling — `__init__.py`
does NOT re-export any deleted symbol; `M-DOMAIN-PORTS` has no
method-level annotations to clean.

### 🟡 Addressed (minor)

- **Class name mismatch**: tasks/proposal/design said `FakeMachineRepository`;
  actual class in `tests/unit/test_domain_ports.py:119` is
  `StubMachineRepository`. Fixed in `design.md` (declarative name
  correction under soft freeze) and `tasks.md` (4.1, 4.2).
- **Unused imports not called out (task 2.1)**: added explicit cleanup
  of `ItemsView`/`KeysView` from `repository.py:42` TYPE_CHECKING block
  (only used by deleted `keys()`/`items()`).
- **Intermediate e2e breakage not flagged**: added ⚠ note to task 2.1
  warning that `test_full_cycle.py:64` will fail with AttributeError
  between step 2.1 and step 5.3.
- **`grace_check.py` limitation**: task 6.3 added explicit manual
  verification — `grace_check.py` validates XML structure but not
  annotation-source consistency, so a missed annotation would not be
  caught by 7.4 alone.
- **`lint-imports` config**: 7.6 clarified to note "no project config
  file; uses packaged default rules per AGENTS.md mandate".
- **`test_keys`/`test_items`/`test_register_machine` class location**:
  5.2 corrected to specify `class TestMachineState` (line 598), not
  `TestMachineStateMethods`.

### 🔴 Outstanding

(none)

### Result

tasks.md frozen. All artifacts complete. Ready for validation.

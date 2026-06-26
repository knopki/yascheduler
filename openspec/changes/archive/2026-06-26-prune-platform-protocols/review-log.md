## proposal Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` (no prior frozen artifacts)

### Verdict: PASS (frozen after declarative clarification)

### 🔴 Outstanding
- None.

### 🟡 Addressed
- `__init__.py` `ProcessInfo` import source change was implicit in the
  blast-radius note but not called out under "What Changes". Added an
  explicit bullet: `__init__.py` imports `ProcessInfo` from `.protocol`
  (instead of `.common`); `run`/`run_bg` stay on `.common`; `ProcessInfo`
  stays in `__all__` unchanged. Declarative clarification — does not change
  what an implementer writes (the relocation was already mandated by the
  "Move ProcessInfo dataclass" bullet).

### 🟢 Confirmed
- Delete `PNode` and `PProcessInfo` Protocols — covered.
- Move `ProcessInfo` (frozen, pid/name/command) from `common.py` to
  `protocol.py` — covered.
- `common.py` retains only `run`/`run_bg` with updated GRACE markers —
  covered.
- `linux.py`/`windows.py` import + annotation updates — covered.
- `gateway.py` annotation updates — covered.
- `tests/unit/test_ssh_gateway.py` 5-site replacement — covered.
- GRACE-lite MODULE_CONTRACT/MODULE_MAP/CHANGE_SUMMARY + knowledge-graph
  `M-PLATFORM-PROTOCOL` annotation update — covered.
- Spec capability mapping: `platform-adapters` (modified, removal
  requirements) + `ssh-gateway` (modified, scenario-level note) — covered.
- Public API stability: `ProcessInfo` name unchanged in `__all__`;
  `PProcessInfo`/`PNode` have zero external consumers — covered.
- Precedent `engine-to-domain-frozen` acknowledged — covered.

### Freeze decision
Proposal frozen. Proceeding to design + specs batch.

## design+specs Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md` + frozen `proposal.md`

### Verdict: PASS (frozen after declarative fixes)

### 🔴 Outstanding
- None.

### 🟡 Addressed
- Path typo `infra/ssh.platform` (mixed conventions) in
  `specs/ssh-gateway/spec.md` and `design.md` Decision 4 prose. Fixed to
  `yascheduler.infra.ssh.platform` (dotted module, consistent with the
  public API surface name). Declarative — does not change spec semantics.
- Migration plan did not explicitly call out GRACE marker updates on every
  governed file (linux.py, windows.py, __init__.py, gateway.py, test file).
  Added a blanket note above the steps and per-step "update its GRACE
  markers" wording. Declarative — the plan already ran `grace_check.py` in
  step 7, so no behavioral change.

### 🟢 Confirmed
- PNode deletion + scenario coverage — covered (design Decision 2,
  platform-adapters scenarios "PNode Protocol removed", "PProcessInfo and
  PNode absent from package re-export").
- PProcessInfo deletion + scenario coverage — covered (design Decision 1,
  platform-adapters scenario "PProcessInfo Protocol removed").
- ProcessInfo moved to protocol.py — covered (design Decision 1,
  platform-adapters scenarios "ProcessInfo defined in protocol module",
  "Platform modules import ProcessInfo from protocol", "Package init
  imports ProcessInfo from protocol", "common.py does not define
  ProcessInfo").
- Public API surface preserved (`ProcessInfo` stays in `__all__`) —
  covered (design Decision 3, platform-adapters scenario "remains in
  __all__").
- ssh-gateway pgrep/list_processes return `AsyncGenerator[ProcessInfo,
  None]` — covered (design Decision 4, ssh-gateway MODIFIED requirement
  body + new scenario "pgrep and list_processes return ProcessInfo").
- All 6 existing platform-adapters scenarios preserved verbatim in
  MODIFIED requirement.
- All 9 existing ssh-gateway scenarios preserved verbatim in MODIFIED
  requirement.
- Requirement header text matches existing specs byte-for-byte.
- All scenarios use `####` (4 hashtags) and WHEN/THEN format.

### Freeze decision
design.md + specs/ frozen. Proceeding to tasks batch.

## tasks Round 1 — 2026-06-26

Reviewer: @k-reviewer-fast
Baseline: explore-brief + frozen proposal + frozen design + frozen specs

### Verdict: PASS (frozen after declarative task additions)

### 🔴 Outstanding
- None.

### 🟡 Addressed
- Test file `test_ssh_gateway.py` is governed (carries MODULE_CONTRACT +
  MODULE_MAP + CHANGE_SUMMARY at lines 4-25). Task 7.6 was conditional
  ("if it carries markers"). Replaced with an explicit task: update
  START_CHANGE_SUMMARY with a v1.2.0 LAST_CHANGE entry; confirm DEPENDS
  M-PLATFORM-PROTOCOL is still correct (it is — ProcessInfo now lives
  there). Declarative — the design already committed to "update GRACE
  markers on every edited governed file."
- `M-PLATFORM-COMMON` knowledge-graph entry still carries
  `<class-ProcessInfo>` and a `<purpose>` mentioning "process info".
  After the move this is stale. Added task 8.2 to remove the annotation
  and drop "process info" from the purpose. Declarative — the design
  already committed to keeping the knowledge graph current.
- `M-PLATFORM-LINUX` and `M-PLATFORM-WINDOWS` `<depends>` both list
  `M-PLATFORM-COMMON`. After the import switch, neither module imports
  from `common.py` (ProcessInfo moves to `.protocol`; run/run_bg are
  consumed via OuterRunCallable, not direct import). Added tasks 8.3
  and 8.4 to drop `M-PLATFORM-COMMON` from their `<depends>`. Declarative
  — knowledge-graph accuracy per GRACE-lite rule 3.

### 🟢 Confirmed
- All 8 blast-radius files have tasks (protocol.py §1, common.py §2,
  linux.py §3, windows.py §4, __init__.py §5, gateway.py §6,
  test_ssh_gateway.py §7, knowledge-graph.xml §8).
- All 7 design.md Migration Plan steps map to tasks.
- All platform-adapters delta scenarios implementable via §1, §2, §5, §8.
- ssh-gateway delta scenario implementable via §6.
- Task ordering correct: protocol.py defines ProcessInfo before
  consumers import it; consumers before validation.
- Granularity: each task is a single-file, minutes-scale edit (well
  under 2h).
- Format: `- [ ] N.M description` under `## N.` headings — apply-parser
  compatible.
- Verification commands from design.md all present in §8.

### Freeze decision
tasks.md frozen. All apply-required artifacts (proposal, design, specs,
tasks) are done and validated. Change is ready for `/opsx-apply`.
# Review Log

## proposal Round 1 — 2026-06-26

### Reviewer: @k-reviewer-fast

### 🔴 Fixed
- None.

### 🟡 Addressed
- Wording imprecision: proposal said "the `# type: ignore`-bridged mismatch
  disappears" — there are no `# type: ignore` comments at the cast lines; the
  `cast()` itself is the workaround. Corrected to "cast-bridged mismatch" and
  added a note that the now-unused `cast` import in `allocate_task.py` and
  `orchestrator.py` is removed (ruff flags it).
- Reviewer noted unused `cast` imports will appear after the 3 casts are
  removed — captured in the proposal note so the implementer handles it.

### 🔴 Outstanding
- None. All 6 verification claims checked out against the codebase; the
  call-site map in `explore-brief.md` is fully covered; no scope creep, no
  contradictions. Proposal is frozen.

## design + specs Round 1 — 2026-06-26

### Reviewer: @k-reviewer-fast

### 🔴 Fixed
- None.

### 🟡 Addressed
- `cloud-config-protocol/spec.md` MODIFIED requirement: the delta had condensed
  the original 6 scenarios down to 3, dropping the ISP guard scenarios
  ("All four ConfigCloud DTOs satisfy CloudConfig", "deallocate_nodes types
  against CloudConfig", "orchestrator types config_clouds and active_clouds
  against CloudConfig", "CloudConfig does not expose provider-specific
  fields"). Since MODIFIED requires full updated content and the Protocol
  itself is unchanged, restored all 6 original scenarios with their original
  wording. Only the requirement prose changed (the precedent-reference
  sentence replaced with the multi-DTO-implementer contrast rationale).

### 🔴 Outstanding
- None. All 9 verification checks passed:
  - design D2 (ports.py `TYPE_CHECKING` + `from __future__ import annotations`)
    confirmed.
  - design D2 (engine.py imports only `.exceptions`, no cycle) confirmed.
  - design D4 (3 cast sites + 2 cast imports) confirmed.
  - domain-ports MODIFIED MachineGateway requirement: all 12 scenarios
    preserved, 2 params retyped, "Start occupancy check" WHEN updated,
    CloudConfig paragraph dropped precedent sentence.
  - domain-ports REMOVED OccupancyConfig + TaskExecutionEngine: both have
    Reason + Migration.
  - cloud-config-protocol MODIFIED: 6-field list preserved, precedent
    sentence replaced, importability preserved, all 6 scenarios now present
    with `####` hashtags.
  - Scenario hashtag check: all scenarios use exactly `####` (4 hashtags).
  - design vs proposal: every decision D1–D8 maps to a "What Changes" item;
    no new scope, no contradiction.
  - explore-brief coverage: all 18 production + 3 test call sites covered;
    all 3 open questions resolved (design says "None").
- design.md and specs are frozen.

## tasks Round 1 — 2026-06-26

### Reviewer: @k-reviewer-fast

### 🔴 Fixed
- None.

### 🟡 Addressed
- Task 3.1/3.2 ordering: 3.1 says replace the two imports with `Engine`;
  3.2 then analyzes whether `Engine` belongs at runtime or under
  `TYPE_CHECKING` and concludes `TYPE_CHECKING` suffices (given
  `from __future__ import annotations`). An implementer reading both tasks
  before acting gets the right answer. Left as-is.
- Task 10.3 lists 5 source files for CHANGE_SUMMARY refresh, omitting
  `tests/unit/test_domain_ports.py`. Per GRACE-lite, test-file CHANGE_SUMMARY
  is optional ("when substantial") — acceptable.
- Task 5.7 ("Update MODULE_MAP in gateway.py IF it enumerates…") is
  conditional — appropriate since the implementer must check.

### 🔴 Outstanding
- None. All 10 verification criteria passed:
  - Every design.md decision D1–D8 and every proposal.md "What Changes" bullet
    has a corresponding task.
  - All 6 files in the explore-brief call-site map are covered.
  - Task granularity is well under 2h each.
  - Task ordering is dependency-correct (ports.py first, then consumers,
    spec deltas verify-only).
  - Verification gates present: `pytest -m unit`, `zuban check`,
    `ruff check`, `ruff format --check`, `lint-imports`, `grace_check.py`,
    `openspec validate --all --json`.
  - GRACE-lite markup tasks present (1.6, 2.3, 5.7, 7.1, 10.3).
  - Final grep task present (10.4, 2.4).
  - All tasks use `- [ ]` checkbox format.
  - No scope creep (CloudConfig, MachineGateway/CloudProvisioner/
    TaskRepository/NodeRepository Protocols, Engine dataclass, and groups B–I
    are all untouched).
  - Pre-existing `PEngineRepository` LSP error at `gateway.py:818` is in
    `CHANGE_SUMMARY` comments from the archived `engine-to-domain-frozen`
    change — not live code, not a blocker for any task.
- tasks.md is frozen. Change is apply-ready.
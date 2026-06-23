## proposal Round 1 — 2026-06-23

### 🟡 Addressed

1. **Knowledge graph depends update is incomplete** — The proposal lists `<depends>` updates for M-MAIN, M-CLIENT, M-DAEMON-SYSTEMD, M-DAEMON-SYSV, M-CLI-COMMANDS but omits four modules whose source files are updated and whose `<depends>` reference M-COMPAT:
   - `M-DB` (line 42: `M-CONFIG-DB, M-COMPAT, ...` → `M-SHARED`)
   - `M-CONFIG-CLOUD` (line 527: `M-CONFIG-UTILS, M-COMPAT` → `M-SHARED`)
   - `M-CONFIG-REMOTE` (line 518: `M-CONFIG-UTILS, M-COMPAT` → `M-SHARED`)
   - `M-CONFIG-ENGINE-REPO` (line 553: `M-CONFIG-ENGINE, M-COMPAT` → `M-SHARED`)

   All four are listed in the "Impact" code file list, so they WILL be changed — but the KG instruction must mention them to avoid stale depends references when M-COMPAT is removed.

   **Fix**: Add the four modules to the KG `<depends>` update list.

2. **Minor factual inaccuracy in "Modified Capabilities"** — Proposal says "yascheduler.compat and yascheduler.variables (listed individually today)" under the `package-facades` outside-layer-set. `yascheduler.variables` is NOT currently listed in the outside-layer-set requirement (only `yascheduler.compat` is). The end result is correct (replace `yascheduler.compat` entry with `yascheduler.shared` umbrella), but the description is inaccurate.

   **Fix**: Change to "`yascheduler.compat` (listed individually today) is replaced by `yascheduler.shared.compat` under a new `yascheduler.shared` umbrella entry; `yascheduler.variables` moves alongside it."

3. **"Out of scope" missing one item from the brief** — The brief lists "Trimming `adapters/ssh/platform/__init__.py` (already a separate acknowledged smell)" as out of scope. The proposal's out-of-scope list doesn't mention it. Minor omission.

   **Fix**: Add it to the out-of-scope list for completeness.

### 🔴 Outstanding

None — all issues are addressable in the next iteration.

### Summary

Proposal coverage of the brief is strong. The three issues above are all minor (one missing KG depends update, one inaccurate description, one omitted out-of-scope item). None block freezing.

- All scope items from the brief are present in the proposal.
- All rejected alternatives are reflected (implicitly or explicitly).
- Capabilities section correctly identifies "None" new and "package-facades" modified.
- The "no backward-compat shims" decision is consistent with AGENTS.md and the existing spec.
- Public API stability is preserved: CLI commands, Yascheduler class, INI config, DB schema, AiiDA entrypoint unaffected.
- The proposal correctly rejects compat shims and hard-enforcement of R2.
- Import rule changes (R2 applies, outside-layer-set treatment) match the brief exactly.
- The "Why" section correctly diagnoses the problem.

## proposal Round 2 — 2026-06-23

### 🟡 Addressed (Round 1 issues confirmed fixed)

1. **KG depends update incomplete** — The "What Changes" section (proposal.md:15) now lists all four formerly-missing modules (`M-DB`, `M-CONFIG-CLOUD`, `M-CONFIG-REMOTE`, `M-CONFIG-ENGINE-REPO`) alongside the original five. ✅
2. **Minor factual inaccuracy in "Modified Capabilities"** — Wording corrected to "`yascheduler.compat` (the only shared-utility module listed individually today)" — no longer falsely claims `yascheduler.variables` is individually listed. ✅
3. **"Out of scope" missing one item** — `Trimming yascheduler/adapters/ssh/platform/__init__.py` now explicitly listed at proposal.md:50. ✅

### 🟡 New

1. **KG Impact section inconsistent with What Changes section** — The "Impact > Knowledge graph" summary (proposal.md:41) still lists only 5 `<depends>` targets (`M-MAIN`, `M-CLIENT`, `M-DAEMON-SYSTEMD`, `M-DAEMON-SYSV`, `M-CLI-COMMANDS`), while the authoritative "What Changes" (proposal.md:15) correctly lists all 9. An implementer following "What Changes" does the right thing, but the Impact summary is incomplete.

   **Fix**: Update the "Impact > Knowledge graph" bullet to match the full 9-module list from "What Changes".

### 🔴 Outstanding

None — the Round 1 items are resolved. The new 🟡 inconsistency is minor and does not block freezing the proposal.

### Summary

- All 3 Round 1 🟡 items are **resolved**. ✅
- 1 new 🟡 inconsistency found (Impact summary vs. What Changes — not blocking).
- No 🔴 issues. The proposal passes Round 2 and can be **frozen**.

## design+specs Round 1 — 2026-06-23

### 🟡 Addressed

1. **design.md D5: Missing explicit "Alternative considered" section** — D5 (the "no business logic / no I/O" contract) is the only decision without a dedicated `**Alternative considered**` subsection. The rationale is present (the implicit alternative is "no clause at all" and the rejection is in the "Why this matters" paragraph), but it breaks the format pattern used by D1–D4 and D6.

   **Fix**: Add an `**Alternative considered**` block, e.g.: "Alternative considered: no explicit 'no business logic' clause, trusting developers not to add business logic. Rejected — without the clause, `yascheduler.shared` has no spec-grounded barrier against accretion, and the top-level accumulator smell would re-form."

2. **specs/package-facades/spec.md (delta): Transitional note inaccuracy** — The MODIFIED "Outside-layer-set exemptions" requirement includes this note:
   > "`yascheduler.compat` and `yascheduler.variables` (previously listed as individual outside-layer-set modules) are relocated..."

   `yascheduler.variables` was **never** listed individually in the outside-layer-set exemptions (verified: zero matches in the existing spec). Only `yascheduler.compat` was. The structural outcome (both moved under the shared umbrella) is correct, but the transitional prose is factually inaccurate.

   **Fix**: Change to "`yascheduler.compat` (previously listed as an individual outside-layer-set module) and `yascheduler.variables` (previously not listed, now also relocated) are moved under `yascheduler.shared`..."

   Note: This same inaccuracy was flagged and fixed in the proposal Round 1 (item 2). The design should inherit that correction.

### 🔴 Outstanding

None — both issues are addressable in the next iteration. No blocking correctness or consistency problems.

### Summary

**design.md** ✅ — All 4 open questions from the brief are resolved (Q1→D2, Q2→D5, Q3→D1, Q4→Non-Goals + Open Questions). Fully consistent with the frozen proposal. D1–D6 have rationale with alternatives (D5 missing the explicit "Alternative considered" label — see 🟡 1). Risks table complete with mitigations. Migration plan concrete with correct verification ladder matching AGENTS.md (`pytest -m unit`, `zuban check`, `ruff check`, `ruff format --check`, `lint-imports`, `grace_check.py`, `openspec validate`).

**specs/package-facades/spec.md (delta)** ✅ — Uses `## MODIFIED Requirements` correctly. Both modified requirements ("Outside-layer-set exemptions", "Public API stability") exist in the baseline. Full content preserved plus new clauses. All 5 new spec clauses have corresponding scenarios with correct `####` WHEN/THEN format. No contradictions with the frozen proposal. Original scenarios preserved (one "compat.py remains internal" intentionally replaced by "compat.py old path removed" — the relocation changes the behavior). Transitional prose has a minor historical inaccuracy (see 🟡 2).

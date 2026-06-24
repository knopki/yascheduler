## proposal Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: `explore-brief.md`

### ✅ Captured well
- Problem statement (Why section, lines 3-10)
- Flag matrix: all 6 rows (no-flags, --schema, --daemon, both, --help, --bogus → exit 2)
- Exit code contract (0/1/2 with sources: service write fail, missing parent dir, DatabaseError, argparse default)
- Service install: overwrite-if-exists (was silent skip), both systemd + sysv
- Service install: missing parent dir → exit 1 (was silent fail via os.access), both systemd + sysv
- systemd detection change: `Path("/run/systemd/system").is_dir()` replacing `pidof systemd`
- Schema apply: DatabaseError → exit 1, adapter untouched, schema.sql idempotent via IF NOT EXISTS
- Drop # FIXME comment (operational orchestration, not app-layer logic)
- No compat shim (infra → entrypoints would invert layer direction; daemon-launchers precedent)
- Subset selectors, not mutually exclusive (no mutually_exclusive_group)
- Files: all 10 entries (2 add, 1 remove, 7 modify) covered in Impact
- Capabilities: no new; two modified (`cli-commands`, `package-facades`); does NOT invent `entrypoints-cli-init`
- Out of scope covers: other 5 CLI commands, apply_schema/postgres_schema.py, schema-migrations, di.py/aiida_plugin.py, importlinter, package-data
- No BREAKING marker (command name + default invocation unchanged)
- Template structure correct (## Why / ## What Changes / ## Capabilities / ## Impact)

### 🟡 Addressed (minor, deferred to design.md where appropriate)
- "Force service-type choice" rejected alternative not explicitly contrasted — auto-detect conveys the decision
- sysv `chmod 0755` not called out — unchanged behavior, will note in design.md
- 3-level `install_path = Path(__file__).parent.parent.parent` invariant not stated — non-obvious correctness detail, will note in design.md
- Call-path / layer-direction diagram absent — proposal format doesn't require it; will be the core of design.md

### 🔴 Outstanding
- None

### Verdict
PASS — no blocking issues. proposal.md frozen. Move to design.md + specs/ (next batch).

### Action
The four 🟡 items are either deferred to design.md (chmod, install_path invariant, call-path diagram) or intentionally not surfaced in the proposal (force-service-type alternative is implied by the auto-detect decision). No edits to proposal.md required.

## design+specs Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: frozen proposal.md + explore-brief.md

### ✅ Captured well
- design.md: D1–D9 decisions all present with rationale + rejected alternatives; D8 (3-level install_path invariant) captured from proposal 🟡 follow-up; Context/Goals/Non-Goals/Risks/Migration Plan complete; no contradictions with frozen proposal.
- specs/package-facades: header `Within-package relative imports (R1)` matches main spec exactly (incl. `(R1)` suffix); drops `init` from infra/cli submodule list + adds "does NOT import init" clause; new `entrypoints/cli/__init__.py` scenario added; only `## MODIFIED Requirements`; no new layers introduced.
- specs/cli-commands: flag matrix fully covered (19 scenarios across 3 requirements); SHALL throughout; 4-hashtag scenarios; no ADDED/REMOVED/RENAMED.

### 🔴 Fixed
- specs/cli-commands: two `### Requirement:` headers had no match in main spec (`yainit service install overwrites existing files`, `yainit detects systemd via /run/systemd/system`) — would create new requirements, contradicting the proposal. Merged their scenarios into the existing MODIFIED `yainit uses apply_schema adapter` requirement; deleted the non-matching headers. Expanded the requirement description to cover service install + detection scope.

### 🟡 Fixed
- specs/cli-commands: `yainit uses apply_schema adapter` description now starts with normative "The `yainit` command SHALL be..." style (was "When...").

### 🔴 Outstanding
- None

### Verdict
PASS — design.md + specs/ frozen. Move to tasks.md.

## design+specs Round 2 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: frozen proposal.md + Round 1 fixes

### ✅ Fixed
- 🔴 Non-matching delta headers removed; scenarios merged under `yainit uses apply_schema adapter` (13 scenarios under that requirement; 19 total across the delta).
- 🟡 Normative description restored.

### 🟡 Remaining
- None

### 🔴 Outstanding
- None

### Verdict
PASS — design + specs frozen, ready for tasks.md.

## tasks Round 1 — 2026-06-24

Reviewer: @k-reviewer-fast
Baseline: frozen proposal.md + design.md + specs/

### ✅ Captured well
- Proposal coverage: all 11 "What Changes" bullets map to tasks.
- Design D1–D9 all reflected (D1 no shim in 5.2; D2 subset selectors in 2.2/2.4; D3 exit codes in 2.3/3.2/3.3/4.1; D4 overwrite+OSError in 3.2/3.3; D5 detection in 3.1; D6 rename+adapter-untouched in 4.1; D7 drop FIXME in 1.2; D8 3-level walk in 2.3; D9 fresh GRACE markup in 1.1/1.2).
- Spec scenario coverage: 19/19 scenarios testable.
- Verification group 10 matches AGENTS.md Verification section.
- No contradictions with frozen artifacts. Task ordering valid. Granularity under 2h.

### 🔴 Fixed
- `init()` signature mismatch: impl tasks said `init()` (no args), test tasks called `init([...])`. Resolved by adopting Option A: `init(argv: list[str] | None = None)` + `parser.parse_args(argv)`. `argv=None` default means console_script reads sys.argv; tests pass explicit lists.

### 🟡 Fixed
- Added `START_BLOCK_VALIDATE_FLAGS` (2.2) and `START_BLOCK_HANDLE_FAILURE` (2.3) block anchors per design D9.
- Added `from pg8000 import DatabaseError` to task 2.1 import list (4.1 now just references it).
- Pinned testability approach for service helpers: `_init_systemd(install_path, unit_file=...)` and `_init_sysv(install_path, startup_file=...)` with injectable params + production defaults; tests 9.11/9.12/9.13 call helpers directly with tmp_path (no /etc/ monkeypatching).
- Softened fragile absolute line-number refs to content-based patterns across 5.2, 6.1, 7.1-7.4, 8.1-8.3, 9.1, 10.2.

### 🟡 Remaining
- Test count in 10.1 said "14 tests" but tasks 9.3-9.14 defined 13 (9.14 has 2 sub-tests: 11 + 2 = 13). Also spec's "idempotent re-run" scenario had no dedicated test.

### 🔴 Outstanding
- None

### Verdict
PASS — no 🔴 blocking issues. The 🟡 test-count mismatch is a documentation-level nit.

## tasks Round 2 — 2026-06-24

Reviewer: @k-reviewer-fast (then author fix)
Baseline: frozen proposal.md + design.md + specs/ + Round 1 fixes

### ✅ Fixed
- 🟡 test-count mismatch: added task 9.15 `test_schema_idempotent_rerun` covering the spec's "yainit initializes database idempotently" scenario (no dedicated test existed). Now 14 tests total (11 single + 2 from 9.14 + 1 from 9.15), matching the 10.1 count. Updated 10.1 text to enumerate the breakdown.

### 🟡 Remaining
- None

### 🔴 Outstanding
- None

### Verdict
PASS — tasks.md frozen. Change `relocate-init-command` is apply-ready.
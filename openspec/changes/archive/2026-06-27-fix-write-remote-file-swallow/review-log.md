## proposal Round 1 — 2026-06-26

### Baseline
- Frozen artifacts: none (first batch)
- New artifacts: proposal.md
- Brief: explore-brief.md

### ✅ Captured

1. **Problem statement** — proposal "Why" matches brief "Problem" exactly: the `except Exception` swallow, silent `True` return, `start_task_on_machine` depending on exceptions not the dead bool, and the chain leading to spawn with missing/garbage inputs producing silently wrong results. Proposal adds "machine slot occupied for garbage run" — implicit in the brief, not a contradiction.

2. **Variant selection (B)** — proposal clearly commits to deleting the generic `except Exception` branch and keeping `asyncssh.misc.Error` unchanged. No ambiguity.

3. **Rejected alternatives C and D** — explicitly listed in "Out of scope" with the same rationales from the brief (aggregation = YAGNI; sftp.stat = races, extra RTTs, wrong layer). ✅

4. **Rejected alternative A** — implicitly rejected by selecting B (deletion not add-raise). Proposal's "What Changes" says "Diagnostics improve" with the same rationale (the local log line is subsumed by upstream log with task_id). ✅

5. **Rejected alternative E** — implicitly rejected by approach: the fix is deletion (no narrowing). Proposal's "Pre-validation" section says remaining exception classes "should not be" pre-validated — the opposite of the narrowing approach. "What Changes" says "no pre-validation extension." ✅

6. **Modified capability accuracy** — proposal correctly identifies `ssh-gateway` as the modified capability. Spec line 33 lists `_write_remote_file` as a private helper; no existing Requirement covers its exception contract. "Add a requirement" is the right delta type. ✅

7. **Scope completeness** — all 4 "In scope" items from the brief are in the proposal:
   - `gateway.py`: delete branch, bump VERSION, CHANGE_SUMMARY ✅
   - `openspec/specs/ssh-gateway/spec.md`: add requirement ✅
   - Knowledge graph: CHANGE_SUMMARY only, no new annotations (private-only change) ✅
   - Tests: unit test for propagation through `start_task_on_machine` ✅

8. **Open question deferrals** — all 3 open questions listed in "Out of scope" with same deferral rationale as the brief:
   - `_upload_task_data` bool return (defer to avoid scope creep) ✅
   - `Engine.validate_inputs` consolidation (separate DRY refactor) ✅
   - `fort.9` pre-decode (loud error is the correct signal) ✅

9. **No contradictions** — proposal claims no new dependency, no public-surface change, no schema change, no caller-side change. All match the brief. No active-change conflict (disjoint files verified). ✅

10. **Conciseness** — 99 lines, ~1.5 pages. Well within 1-2 page guideline. ✅

### 🟡 Addressed (minor)

- **"Touching download_outputs / occupancy / windows_list_processes"** — the brief's last "Out of scope" bullet. The proposal doesn't list it explicitly, but the "Callers" section (only `start_task_on_machine`) and "Code" section ("no other source file changes") convey the same constraint. Not a gap, but could be explicit.

- **Rejected alternatives A and E not named in "Out of scope"** — the proposal's approach (B) IS the rejection of A; the "no pre-validation extension" statement IS the rejection of E. The rationales are present even though A and E aren't cited by name. The brief itself also omits A and E from its own "Out of scope" section — so the proposal mirrors the brief faithfully.

### 🔴 Outstanding (must fix before freeze)

**None.**

### Verdict

**PASS** — No blocking issues. Proposal accurately captures every commitment from the explore brief with no gaps or contradictions.

## design+specs Round 1 — 2026-06-26

### Baseline
- Frozen artifacts: proposal.md
- New artifacts: design.md, specs/ssh-gateway/spec.md
- Brief: explore-brief.md

### ✅ Captured

1. **D1 — Delete generic branch (variant B)**: design D1 explicitly removes lines 142-144, keeps `asyncssh.misc.Error` unchanged at 134-141, and lists rejected alternatives A/C/D/E with the same rationale from the brief (A = duplicate logs without task_id, C = YAGNI, D = races/extra RTTs, E = brittle). ✅

2. **D2 — Keep `asyncssh.misc.Error` branch**: design D2 explains `err.code`/`err.reason` provide structured SFTP diagnostics absent from `str(err)` upstream, and confirms leave byte-for-byte unchanged. ✅

3. **D3 — No knowledge-graph update**: design D3 explicitly cites GRACE-lite rule 3 (private-only change, no graph update). Only a `START_CHANGE_SUMMARY` entry in `gateway.py`. Matches proposal's "GRACE-lite" impact paragraph. ✅

4. **D4 — ADDED not MODIFIED requirement**: verified against `openspec/specs/ssh-gateway/spec.md` lines 31-34: `_write_remote_file` appears only as a helper the gateway MAY use — no Requirement block specifies its exception contract. D4's claim is correct. ✅

5. **D5 — No pre-validation extension**: design D5 gives three reasons (duplicate internal shape knowledge, validation away from consumption point, non-problem today) matching the proposal's "Pre-validation" section and brief's open question 3 resolution. ✅

6. **Goals/Non-Goals cover every proposal "Out of scope" item**: bool return cleanup, Engine.validate_inputs consolidation, fort.9 pre-decode, aggregation, sftp.stat, touching other catch-alls (download_outputs, occupancy, windows_list_processes) — all present. ✅

7. **Risks coverage**: behavior-change intentional (previously-swallowed → abort), diagnostic improvement (task_id in upstream log), double-log for SFTP errors addressed (structured code + task_id = distinct info, not duplication), test-existence check (no existing test asserts swallow, codegraph blast radius confirmed). ✅

8. **Spec delta format and content**:
   - `### Requirement:` (3 hashtags) ✅
   - `#### Scenario:` (4 hashtags) for all 3 scenarios ✅
   - SHALL/MUST normative language throughout ✅
   - Three scenarios: (a) non-SFTP propagation + abort + no spawn, (b) asyncssh.misc.Error log+reraise, (c) success path ✅
   - Does NOT weaken `download_outputs` catch-all (never references it) ✅
   - Matches proposal "Modified Capabilities" entry (add requirement, three scenarios) ✅

9. **No contradictions**: no new dependency, no public-surface change, no schema change, no caller-side change, no graph update claim. All match the frozen proposal. ✅

10. **Conciseness**: design 208 lines, spec delta 55 lines. Focused, no bloat. ✅

### 🟡 Addressed (minor)

(none — all checks pass cleanly)

### 🔴 Outstanding (must fix before freeze)

**None.**

### Verdict

**PASS** — Design and spec delta faithfully implement every commitment from the frozen proposal. No contradictions, no missing coverage, no format violations.

## tasks Round 1 — 2026-06-26

### Baseline
- Frozen artifacts: proposal.md, design.md, specs/ssh-gateway/spec.md
- New artifacts: tasks.md
- Brief: explore-brief.md

### ✅ Captured

1. **Source fix (task 1.1)** — Delete the generic `except Exception` branch in `_write_remote_file`, keep `asyncssh.misc.Error` unchanged. Matches design D1, D2, and proposal "What Changes". ✅

2. **VERSION bump + CHANGE_SUMMARY** (task 1.2) — Covers proposal's "bump VERSION; add a START_CHANGE_SUMMARY entry" and brief's "In scope" for `gateway.py`. ✅

3. **No other source changes** (task 1.3) — Confirmation that `_upload_task_data` and `start_task_on_machine` need no changes. Matches proposal "No caller-side change needed." ✅

4. **Non-SFTP propagation test** (task 2.1) — Asserts a non-SFTP exception (e.g. `ValueError` via fake SFTP client) propagates out, not swallowed. Covers spec scenario 1 (propagation half). ✅

5. **asyncssh.misc.Error log+reraise test** (task 2.2) — Asserts structured `code`/`reason` log and re-raise. Covers spec scenario 2. Locks design D2. ✅

6. **start_task_on_machine abort test** (task 2.3) — Asserts `_exec_spawn_command` is NOT called when upload fails. Covers spec scenario 1 (no-spawn half). ✅

7. **Success-path test** (task 2.4) — Asserts normal return, loop continues. Covers spec scenario 3. ✅

8. **Verification block** (tasks 3.1-3.4) — Covers unit tests, static checks, grace_check, and openspec validate. Matches AGENTS.md's verification commands (with one form note below). ✅

9. **Dependency ordering** — Source fix before tests (1.x before 2.x), tests before verification (2.x before 3.x). Correct. ✅

10. **Checkbox format** — All 11 tasks use `- [ ] X.Y description` format. Parseable by the apply phase. ✅

11. **No scope creep** — No tasks mention: `_upload_task_data` return type change, `Engine.validate_inputs` consolidation, `fort.9` pre-decode, error aggregation, `sftp.stat`, or any of the 5 other catch-all sites. All strictly within the frozen scope. ✅

12. **Unit-only defensible** — The change is to a module-private helper with a clear unit-testable contract (fake SFTP client). Integration/e2e tests would test the same propagation path at higher cost with no additional coverage. Brief's unit-only scope is justified. ✅

### 🟡 Addressed (minor)

1. **Line number drift (task 1.1)** — Task says "lines 142-144" for the generic branch and "lines 134-141" for the `asyncssh.misc.Error` branch. The current file (1.7.0) has the generic branch at lines 143-144 and the SFTP branch at 135-142. The line refs are off by 1–2 lines from the actual file. Not blocking — the descriptive text ("delete the generic `except Exception as e:` branch") is unambiguous. The developer should verify line numbers against the actual file before editing.

2. **`openspec validate` form (task 3.4)** — Task uses `openspec validate fix-write-remote-file-swallow` (change-scoped form). AGENTS.md says `openspec validate --all --json`. Both are valid commands: the change-scoped form is tighter (validates only this change's delta, appropriate during implementation), while `--all --json` is for final/CI-level validation. Not a mistake, but the task could note that `--all --json` must also pass before archiving. Consider adding a parenthetical note: "Before archiving, also run ``openspec validate --all --json`` per AGENTS.md." Optional — the task is correct as-is.

### 🔴 Outstanding (must fix before freeze)

**None.**

### Verdict

**PASS** — No blocking issues. All frozen commitments are correctly reflected, no contradictions, no scope creep, and all granularity/dependency/format checks pass.

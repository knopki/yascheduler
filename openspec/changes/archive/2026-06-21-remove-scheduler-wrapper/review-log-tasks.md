# Review Log — remove-scheduler-wrapper / tasks

## tasks Round 1 — 2026-06-21

### 🔴 Serious issues (must fix)

 - **7.9 validation command raises `NameError` as written.** The one-liner
   `python3 -c "import yascheduler; import yascheduler.adapters.cli.daemonize; import yascheduler.client; assert 'yascheduler.scheduler' not in sys.modules"`
   references `sys.modules` without importing `sys`. Verified live:
   `python3 -c "print(sys.modules)"` → `NameError: name 'sys' is not defined`.
   An implementer running the gate verbatim gets a false-negative failure that
   has nothing to do with the change. The fix is trivial — prepend
   `import sys;` to the command body (e.g.
   `python3 -c "import sys, yascheduler; import yascheduler.adapters.cli.daemonize; import yascheduler.client; assert 'yascheduler.scheduler' not in sys.modules"`).
   Marked serious because a broken command in the validation gate undermines
   the reliability of the "done" signal for the whole change.

### 🟡 Minor issues (should address)

 - **No task for the CHANGELOG entry that design.md commits to.** design.md
   §"Risks / Trade-offs" states: *"CHANGELOG entry will note the removal
   under 'Internal API'"* as the mitigation for the unknown-external-consumer
   risk. `CHANGELOG.md` exists at repo root and follows a Conventional Commits
   section style (Feat/Fix/Refactor/Perf per release). No task in tasks.md
   creates this entry. Either add a task (e.g. "Append a CHANGELOG entry under
   the next-release section noting the removal of `yascheduler/scheduler.py`
   internal-API symbols (`Scheduler`, `get_logger`, `WebhookPayload`
   re-export)") or explicitly document in design.md that the entry is deferred
   to release automation. Note: proposal.md's "What Changes" does not list
   CHANGELOG, so the FROZEN artifacts are slightly inconsistent on this point.
 - **7.9 redundancy with 2.4 is unstated.** Task 2.4 already verifies
   `daemonize` imports without pulling `scheduler`. Task 7.9 widens the check
   to a three-module import chain (`yascheduler`, `daemonize`, `client`).
   That broader coverage is the justification for keeping 7.9 alongside 2.4
   (per review criterion 9). A one-line comment in 7.9 noting "broader than
   2.4 — also catches transitive imports via `yascheduler` and `client`"
   would make the intent unambiguous and prevent a future reader from
   collapsing them.

### 🟢 Confirmed solid

 - **Coverage of proposal Impact is complete.** Every item in proposal.md
   "What Changes" / "Impact" maps to a task: 3.1 (delete `scheduler.py`),
   2.1-2.4 (inline `_get_logger`), 4.2 (delete `test_scheduler.py`),
   4.3 (trim `test_characterization.py`), 4.4 (delete `mock_scheduler.py`),
   4.5 (delete `test_utils_import_does_not_import_scheduler`), 4.1 (move
   WebhookPayload tests), 6.1-6.6 (ARCHITECTURE.md six sections), 5.1-5.2
   (knowledge-graph.xml M-SCHEDULER block + CrossLinks), 5.3 (12-file LINKS
   scrub).
 - **Spec sync correctly delegated to archive.** No task edits the live
   `openspec/specs/{package-facades,testing-unit,db-wrapper}/spec.md`. The
   deltas under `openspec/changes/remove-scheduler-wrapper/specs/` are applied
   at archive time; the gate is 7.2 `openspec validate --all --json` plus 7.1
   for the change itself.
 - **D7 ordering constraint captured explicitly.** Tasks.md line 9 spells out
   "steps 2.x MUST precede step 3.1" and references design D7.
 - **GRACE-lite top-down principle honoured.** 2.1 (GRACE headers: SCOPE,
   MODULE_MAP, CHANGE_SUMMARY) precedes 2.2 (inline body). 5.1-5.2 (graph
   edits) precede 5.3 (source LINKS scrub). No inversion.
 - **Validation gate complete.** Section 7 names all AGENTS.md validators:
   7.4 `pytest -m unit`, 7.5 `ruff check`, 7.6 `ruff format --check`,
   7.7 `lint-imports`, 7.8 `zuban check`, 7.1/7.2 `openspec validate`, 7.3
   `grace_check.py`.
 - **Checkbox format uniform.** Every task is `- [ ] N.X ...` — no Markdown
   bullet variants, no prose-only items.
 - **Line refs verified accurate against live files.** Spot-checked:
   `daemonize.py:5,6,10-12,14-15,42,54` ✓;
   `scheduler.py:47-73` (get_logger body) ✓; `knowledge-graph.xml:39-52`
   (M-SCHEDULER block) ✓; `knowledge-graph.xml:882,909,910,934` (4 CrossLinks)
   ✓; `ARCHITECTURE.md:84,120,178,258,260,268,386,464` ✓. The 12-file LINKS
   list in 5.3 matches `rg "LINKS:.*M-SCHEDULER" yascheduler/` exactly.
 - **CrossLink count follows FROZEN artifacts.** Tasks correctly says four
   CrossLinks (matching proposal/design), not the stale "2" in explore-brief.
   explore-brief is informational; FROZEN artifacts govern.
 - **Line-number fragility mitigated.** Every task citing a line number also
   names the content being removed (`<M-SCHEDULER ...>` block,
   `<CrossLink from="M-SCHEDULER" ...>` entries, "scheduler.py" table row,
   etc.), so an implementer can locate the target even if line numbers drift
   within the atomic commit.
 - **D6 atomic-commit invariant compatible with tasks.** All steps land in
   one commit; no task implies a partial-state push.
 - **Verifiability.** Each task has a concrete "done" signal (grep returning
   zero hits, manual sys.modules check, validator exit code, baseline diff).
 - **Granularity within 2-hour rule.** 5.3 (12-file single-token scrub) is
   tractable — confirmed it is mechanical `M-SCHEDULER` token removal on 12
   LINKS lines.

### 🔴 Outstanding (after this round — populated only if serious issues remain)

 - Fix 7.9 by prepending `import sys;` to the one-liner (see Serious issues).
   Trivial one-token edit; expected to clear on Round 2.

## tasks Round 2 — 2026-06-21

### 🔴 Serious issues (must fix)

 - None.

### 🟡 Minor issues (should address)

 - None.

### 🟢 Round 1 resolutions verified

 - **7.9 `NameError` fixed.** tasks.md:58 now reads
   `python3 -c "import sys; import yascheduler; import yascheduler.adapters.cli.daemonize; import yascheduler.client; assert 'yascheduler.scheduler' not in sys.modules"`.
   Verified three ways: (a) `import sys;` prefix present at the start of
   the `-c` body; (b) assertion still references `'yascheduler.scheduler'
   not in sys.modules` (correct module name, correct sentinel string);
   (c) `python3 -c "import ast; ast.parse('<body>')"` returns `SYNTAX OK` —
   the one-liner is syntactically valid Python. Live execution will still
   fail pre-apply (scheduler.py exists), but that is expected and not a
   defect in the task itself.
 - **Section 8 CHANGELOG task added.** tasks.md:60-62 — new `## 8.
   CHANGELOG` section with task 8.1: "Add a CHANGELOG entry under 'Internal
   API' noting the removal of `class Scheduler`, `scheduler.get_logger`,
   and the `WebhookPayload` re-export from `yascheduler/scheduler.py`.
   Reference this change proposal." Task is specific (names section, names
   the three symbols, names the reference) and therefore actionable.
   Authoritative source confirmed: design.md:253-260 "Risks / Trade-offs"
   bullet `[Unknown external consumer of class Scheduler]` ends with
   "CHANGELOG entry will note the removal under 'Internal API'". Section
   numbering follows section 7 cleanly (no gap, no collision).
 - **7.9 redundancy with 2.4 justified.** tasks.md:58 now opens
   "Manual sanity (broader than 2.4: covers full import surface):" before
   the command. Intent is unambiguous; a future reader will not collapse
   7.9 into 2.4.

### No regressions confirmed

 - **Section numbering integrity.** `grep '^## '` returns 1..8 in order,
   no duplicates, no gaps. Sections 1-7 unchanged from Round 1.
 - **Cross-references.** No task in sections 1-7 references "section 8"
   or "task 8.1" — grep for `section 8|task 8\.1` matches only the section
   header itself. CHANGELOG is independent; no ordering confusion.
 - **Round 1 "Confirmed solid" items re-verified by spot-check.** Proposal
   coverage intact (3.1 delete, 2.1-2.4 inline, 4.x test moves/deletes,
   5.x graph+LINKS, 6.x ARCHITECTURE). D7 ordering constraint still on
   tasks.md:9. GRACE-lite top-down (2.1 before 2.2; 5.1-5.2 before 5.3).
   Spec sync still delegated to archive (no live `openspec/specs/` edits).
   All 7 validators present (7.1-7.8) plus 7.9 manual sanity. Checkbox
   format uniform. Line refs in 2.1, 2.2, 5.1-5.3, 6.1-6.6 unchanged.

PASSED — single-round pass. No serious or minor issues remain.

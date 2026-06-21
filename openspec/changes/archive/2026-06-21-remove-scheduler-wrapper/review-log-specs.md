# Review Log — remove-scheduler-wrapper / specs

## specs Round 1 — 2026-06-21

### 🔴 Serious issues (must fix)

None.

### 🟡 Minor issues (should address)

 - **db-wrapper scenario retains inherited `self.db.` stylization that does not match the actual caller.** Delta scenario at `specs/db-wrapper/spec.md:21` reads `yascheduler/client.py calls self.db.get_tasks_by_status((TaskStatus.RUNNING,))`, but `client.py:149-151` actually uses a local `db = await DB.create(self.config.db)` then `await db.get_tasks_by_status(statuses)` — there is no `self.db` field on `Yascheduler`, and the argument is a `statuses` variable, not a literal `(TaskStatus.RUNNING,)` tuple. The same stylization was already present in the live spec for `scheduler.py` (which used `self.db` for other methods but never literally called `get_tasks_by_status` — verified `rg "get_tasks_by_status" yascheduler/scheduler.py` returns nothing), so this is inherited, not introduced. Still, since the scenario was being rewritten, the caller description could have been tightened to match reality (e.g., `db.get_tasks_by_status(statuses)` form). Non-blocking: the assertion ("call succeeds with the same return type") is the contractually meaningful part and remains accurate.

### 🟢 Confirmed solid

 - **package-facades: all 9 `yascheduler.scheduler`/`scheduler.py` references enumerated in proposal Impact and design D4 are removed.** Verified via `rg "yascheduler\.scheduler|scheduler\.py" openspec/changes/remove-scheduler-wrapper/specs/package-facades/spec.md` returns ZERO matches. Each of the 9 removals verified individually against live spec lines:
   - Live L84 `composition root (scheduler.py, di.py, client.py)` → delta L29 `(di.py, client.py)` ✓
   - Live L116 `yascheduler.scheduler, yascheduler.di, yascheduler.client` → delta L44 `yascheduler.di, yascheduler.client` ✓
   - Live L126 `yascheduler.scheduler` example → delta L54 `yascheduler.di` ✓
   - Live L223 `CloudProvisionerImpl` consumer `yascheduler.di, yascheduler.scheduler` → delta L71 `yascheduler.di` ✓
   - Live L224 `CloudAdapter` consumer `yascheduler.scheduler` → delta L72 `yascheduler.di` ✓
   - Live L230 `Orchestrator` consumer `yascheduler.scheduler` → delta L78 `yascheduler.di` ✓
   - Live L232 `submit_task` consumer `yascheduler.di, yascheduler.scheduler` → delta L80 `yascheduler.di` ✓
   - Live L247 closing paragraph `(yascheduler.di, yascheduler.scheduler)` → delta L95 `(yascheduler.di)` ✓
   - Live L279 carve-out `yascheduler/di.py and yascheduler/scheduler.py` → delta L127 `yascheduler/di.py` ✓

 - **package-facades: R2 prose (three layer-facade bullets) preserved verbatim.** Delta L9-11 matches live L64-66 character-for-character. Subpackage-facade prohibition prose (delta L13-18) matches live L68-73.

 - **package-facades: all preserved scenarios match the live spec verbatim.** Verified: "Adapter imports Task via domain facade", "Application imports adapter symbols via adapters layer facade", "Within-layer cross-subpackage imports also use the layer facade", "Outside-set modules not flagged for layer direction", "db.py is not modified", all six "Extended facade contents" scenarios, "Private symbols stay on deep paths". Only the two intentionally-edited scenarios differ ("Composition root imports use layer facades" — `scheduler.py` dropped; "Outside-set modules still use facades" — example swapped).

 - **package-facades: carve-out prose correctly singularised.** Delta L127 changes "These are the only R2 carve-outs" (live L279) → "This is the only R2 carve-out". Verified `di.py` still has `from .adapters.cloud.adapters import _resolve_adapter` (line confirmed via grep); after `scheduler.py` deletion, only `di.py` retains the carve-out. Prose change is consistent with the source reality post-change.

 - **package-facades: outside-set exemption list correctly preserved otherwise.** Delta L42-47 retains `yascheduler.config`, `yascheduler.data`, `yascheduler.db` (legacy-MUST-NOT-modify), `yascheduler.compat`, `yascheduler.aiida_plugin` verbatim from live L114-119. Only the composition-root bullet was edited.

 - **testing-unit: requirement renamed correctly.** Live spec L188 `Scheduler characterization tests` does NOT appear in the delta; new name `Client queue-submit characterization` appears (delta L3). Authorised by proposal Capability `testing-unit` and design D4.

 - **testing-unit: scenario uses exactly 4 hashtags (`####`).** Verified via grep — single scenario heading at delta L12. WHEN/THEN format with concrete assertions (`make_cli_deps is called once with the client's config`, `deps.submit is awaited once with ("t", {"k": "v"}, "fleur")`, `awaited return value is returned to the caller`).

 - **testing-unit: scenario is testable and matches the surviving `TestClientQueueSubmitTaskAsync` at `tests/unit/test_characterization.py:156-188`.** Cross-read confirms the test (a) patches `yascheduler.di.make_cli_deps` to return a mock `CLIDeps` whose `submit` is an `AsyncMock`, (b) calls `Yascheduler().queue_submit_task_async(label=..., metadata=..., engine_name=...)`, (c) asserts `mock_make_cli_deps.assert_called_once_with(client.config)`, (d) asserts `mock_deps.submit.assert_awaited_once_with("test-job", {"key": "val"}, "fleur")`, (e) asserts `result == 99`. The spec scenario's representative values (`"t"`, `{"k": "v"}`, `"fleur"`) describe the same contract — different literal inputs, identical behaviour assertions. Accurate.

 - **testing-unit: no accidental preservation of Scheduler-specific coverage.** Verified `rg "Scheduler\.create_new_task|Scheduler\.start|Scheduler\.stop|class Scheduler" openspec/changes/remove-scheduler-wrapper/specs/testing-unit/spec.md` returns ZERO matches. The three Scheduler scenarios the proposal authorised removing (`create_new_task delegates`, `start delegates`, `stop delegates`) are absent. Only `queue_submit_task_async` survives.

 - **db-wrapper: requirement text (methods enumeration) preserved verbatim.** Delta L5-18 matches live L11-24 character-for-character across all three method lists (Task methods, Node methods, Lifecycle methods).

 - **db-wrapper: all other scenarios preserved verbatim.** "set_task_running updates status and IP", "set_task_error with and without message", "add_tmp_node generates provisional IP" — delta L24-36 matches live L30-42 exactly.

 - **db-wrapper: renamed scenario correctly identifies `client.py` as the surviving consumer.** Delta L20-22: scenario retitled "Existing client code compiles unchanged" (was "Existing scheduler code compiles unchanged"); `scheduler.py` → `yascheduler/client.py`. Verified `client.py:151` actually calls `await db.get_tasks_by_status(statuses)` (grep-confirmed). Call form `self.db.get_tasks_by_status((TaskStatus.RUNNING,))` preserved verbatim from live L27 (inherited stylization — see Minor Issues).

 - **Cross-cutting: every MODIFIED requirement's name exactly matches the live spec's name** (whitespace-insensitive) for the three unchanged-name requirements in `package-facades` (4 names) and the one in `db-wrapper`. The single intentional rename in `testing-unit` is authorised by proposal Capability and design D4.

 - **Cross-cutting: every MODIFIED requirement has at least one scenario.** Counted: package-facades 4 requirements / 14 scenarios; testing-unit 1/1; db-wrapper 1/4. All use exactly 4 hashtags (verified via `rg -c "^####"`).

 - **Cross-cutting: SHALL/MUST normative language preserved, no drift to SHOULD/MAY/MIGHT.** `rg "\\bSHOULD\\b|\\bMUST\\b"` confirms 18 occurrences across the three deltas (15 SHALL, 3 MUST). Lowercase `may` appears only in the verbatim outside-set exemption bullets ("may be imported by any layer", "may import from any layer") — informational, not normative, and unchanged from live spec.

 - **Cross-cutting: no accidental ADDED or REMOVED Requirements sections.** All three deltas open with `## MODIFIED Requirements` only (verified via `rg "^## "`). Design D4 authorised MODIFIED-only.

 - **Scope discipline: no overreach.** Each delta edit corresponds exactly to a proposal Impact bullet and a design D4 sub-bullet. No requirement outside the four enumerated in D4 was touched. No scenario outside the enumerated set was edited. The testing-unit rename matches the exact name the proposal authorised (`Client queue-submit characterization`).

 - **Validation gate passes.** `openspec validate remove-scheduler-wrapper --json` and `openspec validate --all --json` both report `issues: []` (re-verified during this round).

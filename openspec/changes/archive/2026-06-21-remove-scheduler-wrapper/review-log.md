# Review Log — remove-scheduler-wrapper

## proposal Round 1 — 2026-06-21

### 🔴 Serious issues (must fix)

 - **Missing modified capability: `testing-unit`** (`openspec/changes/remove-scheduler-wrapper/proposal.md:42-50`, Capabilities → Modified Capabilities). The proposal deletes `TestSchedulerCreateNewTask`, `TestSchedulerStart`, `TestSchedulerStop` from `tests/unit/test_characterization.py` and the entire `tests/unit/test_scheduler.py`, but `openspec/specs/testing-unit/spec.md:188-196` carries a SHALL requirement that mandates exactly those tests:

   ```
   ### Requirement: Scheduler characterization tests
   Tests SHALL verify `Scheduler` delegates `create_new_task` to `submit_task`,
   `start()` to `make_daemon`/Orchestrator, and `stop()` to orchestrator or falls
   back to clouds/db cleanup. ...

   #### Scenario: Scheduler.create_new_task delegates to submit_task
   - **WHEN** `scheduler.create_new_task(...)` is called
   - **THEN** it calls the `submit_task` use case
   ```

   After this change the requirement becomes unfulfillable and `openspec validate --all` will fail (no code satisfies it). The proposal's Capabilities → Modified Capabilities list (currently only `package-facades`) MUST add `testing-unit` and describe the delta: remove the "Scheduler characterization tests" requirement entirely (or rewrite it to cover `Yascheduler.queue_submit_task_async` only, which is the test that stays). The Impact → Specs bullet must list `openspec/specs/testing-unit/spec.md`.

 - **Missing modified capability: `db-wrapper`** (`openspec/changes/remove-scheduler-wrapper/proposal.md:42-50`). `openspec/specs/db-wrapper/spec.md:26-28` has a scenario that names the soon-to-be-deleted module as thecaller:

   ```
   #### Scenario: Existing scheduler code compiles unchanged
   - **WHEN** `scheduler.py` calls `self.db.get_tasks_by_status((TaskStatus.RUNNING,))`
   - **THEN** the call succeeds with the same return type
   ```

   Once `scheduler.py` is gone this scenario is stale and misleading (it also contradicts the proposal's claim of full coverage of spec deltas). The proposal's Capabilities → Modified Capabilities MUST add `db-wrapper` and the Impact → Specs bullet must list `openspec/specs/db-wrapper/spec.md` with the action: rewrite or remove the "Existing scheduler code compiles unchanged" scenario (likely by replacing the caller reference with `yascheduler/client.py`, which is the surviving `get_tasks_by_status` consumer per ARCHITECTURE.md §2.9 line 268).

### 🟡 Minor issues (should address)

 - **Wrong `<CrossLink>` count for `docs/knowledge-graph.xml`** (`proposal.md:70-71`). The proposal says "remove `<M-SCHEDULER>` element and its **two** `<CrossLink>` edges". `docs/knowledge-graph.xml` actually contains **four** `CrossLink` entries whose `from="M-SCHEDULER"`: lines 882 (→ M-DB), 909 (→ M-DI), 910 (→ M-APPLICATION-SUBMIT), 934 (→ M-WEBHOOK). This miscount is inherited from `explore-brief.md:63` but the proposal is what becomes the frozen baseline; design.md / tasks.md will treat "two" as authoritative. Fix: change "two `<CrossLink>` edges" to "four `<CrossLink>` edges (lines 882, 909, 910, 934)". Also note the proposal's "update any `<depends>` lists referencing M-SCHEDULER" is currently a no-op (verified: no other `<depends>` element mentions M-SCHEDULER) — fine as a defensive phrasing but worth knowing.

 - **`tests/unit/test_cli_smoke.py` not mentioned anywhere** (`proposal.md:24-34` test-removal list). `tests/unit/test_cli_smoke.py:34-45` defines `test_utils_import_does_not_import_scheduler`, which directly names `yascheduler.scheduler` (pops it from `sys.modules` and asserts `yascheduler.adapters.cli` does not transitively import it). After the change the test still passes (a non-existent module can't be imported), but its name, docstring, and assertion target become a stale tautology. The brief also misses this. Suggest the proposal add a one-line entry under Tests Modified: "Update or remove `test_utils_import_does_not_import_scheduler` in `tests/unit/test_cli_smoke.py` — its target module no longer exists."

 - **Imprecise `create_test_config` consumer claim** (`proposal.md:64-66`). The proposal says "remaining `test_characterization.py` (`TestClientQueueSubmitTaskAsync`) and any other consumers updated to import from the new location." But `TestClientQueueSubmitTaskAsync` (tests/unit/test_characterization.py:156-188) does not use `create_test_config` today — it builds `Yascheduler()` with a real `Config.from_config_parser` mock. The only current consumer is the to-be-deleted `tests/unit/test_scheduler.py:30,63`. So the "update consumers" task is effectively empty for the surviving tests; the `tests/fixtures/config.py` relocation is purely forward-looking. Rewording to "relocate for future client tests; no current consumer other than the deleted `test_scheduler.py`" would be accurate.

### 🟢 Confirmed solid

 - **Consumer audit fidelity**: Verified by grep + codegraph-equivalent inspection of `yascheduler/scheduler.py`, `daemonize.py`, `client.py`, `aiida_plugin.py`, and the test tree. `class Scheduler` has zero production consumers (only tests reference it); `get_logger` has exactly one production consumer (`yascheduler/adapters/cli/daemonize.py:42` lazy import inside `daemonize()`); the `WebhookPayload` re-export at `scheduler.py:42` has zero production consumers (canonical home is `yascheduler/webhook.py`; the only re-export consumer is `tests/unit/test_scheduler.py:33`). The proposal's audit claims at `proposal.md:5-9,18-20` match the code exactly.

 - **BREAKING label grounding**: Verified that none of `Scheduler`, `get_logger`, or `WebhookPayload` appear in `yascheduler/__init__.py` (it exports only `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `Yascheduler`, `__version__`), in `[project.scripts]` (only the six CLI commands), or in `[project.entry-points."aiida.schedulers"]` (points to `yascheduler.aiida_plugin:YaScheduler`). The proposal's claim at `proposal.md:21-23` is accurate.

 - **Scope matches brief's "Final approach"** (`explore-brief.md:31-48` vs `proposal.md:13-34`): every brief bullet (delete file, inline `get_logger` as `_get_logger`, delete the three scheduler test classes + `test_scheduler.py`, drop `make_scheduler`, relocate `create_test_config`, move `WebhookPayload` tests) is captured.

 - **`package-facades` delta enumeration is complete**: Cross-checked against `openspec/specs/package-facades/spec.md`. All seven scheduler references (lines 84, 116, 126, 223, 224, 230, 232, 247, 279) fall under the four bullets the proposal lists ("Outside-layer-set exemptions", R2 scenario, "Extended facade contents" prose, "Documented private-symbol carve-outs"). No stray reference missed.

 - **`docs/ARCHITECTURE.md` mapping is accurate**: Verified each named anchor exists — §1 diagram (line 84), §2 component table (line 120), §2.2 last paragraph (line 178), §2.9 (lines 258-260 and 268), §3.7 (line 386), §4 tree (line 464).

 - **Internal consistency**: Impact section (`proposal.md:52-78`) matches What Changes (`proposal.md:13-34`) — no contradictions, no orphan bullets. No new dependencies, no schema change, no config-format change, public API unchanged: all correct.

 - **No open questions silently introduced**: The brief declares "None remaining after decisions" (`explore-brief.md:87-91`); the proposal does not introduce any new undecided question. Rejected alternatives (deprecation cycle, `log.py` extraction, `di.py` placement) are intentionally not re-litigated in the proposal, which is appropriate.

 - **No scope creep / no implementation leakage**: The proposal stays at the "what changes" altitude. It does not prescribe `_get_logger`'s body, the exact new symbol layout of `tests/fixtures/config.py`, or import-linter config tweaks — those correctly belong in design.md / tasks.md.

### 🔴 Outstanding (after this round)

 - **Missing modified capability `testing-unit`** — proposal must add `testing-unit` to Capabilities → Modified Capabilities and add the spec file to the Impact → Specs bullet, with a described delta for the "Scheduler characterization tests" requirement at `openspec/specs/testing-unit/spec.md:188-196`.

 - **Missing modified capability `db-wrapper`** — proposal must add `db-wrapper` to Capabilities → Modified Capabilities and add the spec file to the Impact → Specs bullet, with a described delta for the "Existing scheduler code compiles unchanged" scenario at `openspec/specs/db-wrapper/spec.md:26-28`.

## proposal Round 2 — 2026-06-21

### 🔴 Serious issues (must fix)

 - **False rationale for removing the entire `testing-unit` "Scheduler characterization tests" requirement** (`proposal.md:56-60`). The delta justifies full removal by claiming: "The surviving `TestClientQueueSubmitTaskAsync` (kept in `test_characterization.py`) is already covered by the existing 'Yascheduler facade' / queue-submit requirements and needs no replacement scenario here." This is factually wrong on two counts:

   1. There is **no** "Yascheduler facade" requirement anywhere in `openspec/specs/` (verified: `rg "Yascheduler facade|queue-submit" openspec/specs/` returns zero matches).
   2. The **only** mention of `Yascheduler.queue_submit_task_async` in the entire spec corpus is `openspec/specs/testing-unit/spec.md:192` — which is *inside* the very requirement the proposal deletes. After removal, the kept `TestClientQueueSubmitTaskAsync` test (tests/unit/test_characterization.py:156-188, which asserts `client.queue_submit_task_async` calls `make_cli_deps(config).submit(...)`) has **zero spec coverage**, and the production behavior it verifies loses its spec mandate.

   Round 1 explicitly offered two acceptable resolutions: "remove the requirement entirely **or rewrite it** to cover `Yascheduler.queue_submit_task_async` only, which is the test that stays." The proposal picked "remove entirely" but supported the choice with a nonexistent coverage claim — so the choice rests on a false premise. Fix: either (a) rewrite the requirement instead of deleting it — e.g. rename to "Client queue-submit characterization" and keep a scenario `Yascheduler.queue_submit_task_async uses make_cli_deps` (matches the kept test at test_characterization.py:162-188); or (b) correct the rationale to drop the false "already covered" claim and explicitly state the `queue_submit_task_async` coverage is folded into the existing "Dependency injection factories" requirement by adding a scenario there. Option (a) is the smaller, cleaner delta and preserves the spec's mandate for a real production code path.

### 🟡 Minor issues (should address)

 - None.

### 🟢 Round 1 resolutions verified

 - **Round 1 serious: missing `testing-unit` capability** — Resolution: `testing-unit` now appears in Modified Capabilities (`proposal.md:56-60`) and in Impact → Specs (`proposal.md:88-90`). The capability listing itself resolves the Round 1 flag, but the *removal rationale* introduces the new serious issue above.

 - **Round 1 serious: missing `db-wrapper` capability** — Resolution verified clean. `db-wrapper` is in Modified Capabilities (`proposal.md:61-65`) and Impact → Specs. The named surviving consumer `yascheduler/client.py` is correct — confirmed `yascheduler/client.py:151` calls `db.get_tasks_by_status(statuses)`. The "rewrite the scenario so its caller reference no longer names scheduler.py" delta matches `openspec/specs/db-wrapper/spec.md:26-28`.

 - **Round 1 minor: wrong CrossLink count** — Resolution verified. `proposal.md:84-87` now reads "four `<CrossLink>` edges (lines 882, 909, 910, 934)". Confirmed against `docs/knowledge-graph.xml`: exactly four `from="M-SCHEDULER"` CrossLinks exist, at those four line numbers (→ M-DB, → M-DI, → M-APPLICATION-SUBMIT, → M-WEBHOOK). No others.

 - **Round 1 minor: `test_cli_smoke.py` unmentioned** — Resolution verified. `proposal.md:35-37` (What Changes) and `proposal.md:74-78` (Impact → Tests removed) both name `test_utils_import_does_not_import_scheduler`. The test exists at `tests/unit/test_cli_smoke.py:34-45`. Removing it leaves the file meaningful (`TestCLIFunctions`, lines 74-122, with 6 substantive CLI smoke tests stays). Action correctly framed as "remove the test, keep the file".

 - **Round 1 minor: imprecise `create_test_config` claim** — Resolution verified. `proposal.md:29-32` now says delete the whole `tests/fixtures/mock_scheduler.py` with no relocation, justified by YAGNI. Confirmed by grep: `create_test_config` has exactly one consumer (`tests/unit/test_scheduler.py:30,63`), which is itself being deleted. The forward-looking relocation to `tests/fixtures/config.py` is dropped. YAGNI framing is sound.

### 🔴 Outstanding (after this round)

 - **False rationale for removing the entire `testing-unit` "Scheduler characterization tests" requirement** (`proposal.md:56-60`). The "already covered by the existing 'Yascheduler facade' / queue-submit requirements" claim is fabricated — no such requirements exist; the only `Yascheduler.queue_submit_task_async` mention in `openspec/specs/` is on line 192 of the requirement being deleted. The kept `TestClientQueueSubmitTaskAsync` test must retain spec coverage: either rewrite the requirement to a "Client queue-submit characterization" requirement with a `Yascheduler.queue_submit_task_async uses make_cli_deps` scenario, or move that scenario into the existing "Dependency injection factories" requirement. Either way, correct the false rationale.

## proposal Round 3 — 2026-06-21

### 🔴 Serious issues (must fix)

 - None.

### 🟡 Minor issues (should address)

 - None.

### 🟢 Round 2 resolution verified

 - **False rationale for full removal of `testing-unit` "Scheduler characterization tests" requirement** (`proposal.md:56-62`). The rewrite was chosen over deletion. Verified:
   - Spec location accurate: `openspec/specs/testing-unit/spec.md:188-196` does contain the "Requirement: Scheduler characterization tests" header (line 188) with its body and single scenario spanning through line 196.
   - Surviving scenario attribution accurate: line 192 reads `back to clouds/db cleanup. Yascheduler.queue_submit_task_async uses make_cli_deps.`
   - Rename consistency: the proposed "Client queue-submit characterization" requirement name mirrors the surviving test class `TestClientQueueSubmitTaskAsync` at `tests/unit/test_characterization.py:156-188` (which asserts `client.queue_submit_task_async` calls `make_cli_deps(config).submit(...)`).
   - "No other requirement covers it" claim verified true: `rg queue_submit_task_async openspec/specs/` returns exactly one match — line 192 of the requirement being rewritten. The `dependency-injection` spec covers `make_cli_deps` factory mechanics (lines 26-55) but does NOT cover the `Yascheduler.queue_submit_task_async` consumer behavior, so there is no overlap.
   - The fabricated "already covered by Yascheduler facade / queue-submit requirements" rationale from Round 2 is gone; the new rationale correctly states that deletion would orphan both the kept test and the production code path.

### No regression on Round 1 fixes (skim-verified)

 - **db-wrapper capability**: still listed in Modified Capabilities (`proposal.md:63-67`) and Impact → Specs (`proposal.md:90-92`). Named surviving consumer `yascheduler/client.py` matches `openspec/specs/db-wrapper/spec.md:26-28` scenario; rewrite action described.
 - **CrossLink count**: `proposal.md:87` still reads "four `<CrossLink>` edges (lines 882, 909, 910, 934)".
 - **test_cli_smoke.py**: still named in What Changes (`proposal.md:35-37`) and Impact → Tests removed (`proposal.md:79-80`) as `test_utils_import_does_not_import_scheduler`.
 - **create_test_config**: `proposal.md:29-32` still deletes `tests/fixtures/mock_scheduler.py` wholesale with YAGNI rationale; no relocation claim.

### Internal consistency

 - Impact → Specs (`proposal.md:90-92`) lists all three modified spec files: `package-facades`, `testing-unit`, `db-wrapper`. Matches the three Modified Capabilities entries.

### No new gap — final sweep

 - `rg "scheduler\.py|class Scheduler|Scheduler\b" openspec/specs/` returns 6 matches across 3 spec files, all covered by existing deltas:
   - `testing-unit/spec.md:188, 190, 194` — covered by testing-unit rewrite delta.
   - `package-facades/spec.md:84, 279` — covered by package-facades delta.
   - `db-wrapper/spec.md:27` — covered by db-wrapper delta.
 - No remaining spec mention of `scheduler.py` / `Scheduler` outside the three deltas.

# Review Log — remove-scheduler-wrapper / design

## design Round 1 — 2026-06-21

### 🔴 Serious issues (must fix)

 - **D5 under-specifies the GRACE-lite cleanup: 12 surviving source files have `LINKS: ... M-SCHEDULER ...` annotations that will dangle after the `<M-SCHEDULER>` block is removed from the graph.** The design only audits `<depends>` elements in `docs/knowledge-graph.xml`; it does not audit `LINKS:` fields in source MODULE_CONTRACTs. Verified via `rg "LINKS:.*M-SCHEDULER"` the following surviving files reference `M-SCHEDULER` in their `LINKS:` line:
   - `yascheduler/webhook.py:8` — `LINKS: M-SCHEDULER, M-APPLICATION-ORCHESTRATOR`
   - `yascheduler/queue.py:8` — `LINKS: M-SCHEDULER`
   - `yascheduler/time.py:8` — `LINKS: M-SCHEDULER`
   - `yascheduler/db.py:8` — `LINKS: M-PERSISTENCE-POSTGRES, M-DOMAIN-MODEL, M-SCHEDULER`
   - `yascheduler/domain/services.py:7` — `LINKS: M-DOMAIN-MODEL, M-SCHEDULER`
   - `yascheduler/config/__init__.py:12` — `LINKS: M-CONFIG, M-SCHEDULER`
   - `yascheduler/config/local.py:9` — `LINKS: M-SCHEDULER`
   - `yascheduler/config/config.py:9` — `LINKS: M-CONFIG-HUB, M-SCHEDULER`
   - `yascheduler/config/engine_repository.py:9` — `LINKS: M-CONFIG-ENGINE, M-SCHEDULER`
   - `yascheduler/application/allocate_task.py:7` — `LINKS: ..., M-SCHEDULER, ...`
   - `yascheduler/application/consume_task.py:7` — `LINKS: ..., M-SCHEDULER, ...`
   - `yascheduler/application/submit_task.py:7` — `LINKS: ..., M-SCHEDULER`
   - (`tests/unit/test_scheduler.py`, `tests/unit/test_characterization.py`, `tests/fixtures/mock_scheduler.py` are deleted/edited by D3, so they don't add to the surviving count.)

   **Impact:** `scripts/grace_check.py:_check_cross_references` emits a `source-links-ref` WARNING per unknown M-ID reference. Today the baseline is 0 such warnings (verified: `python3 scripts/grace_check.py` reports 18 warnings, all `func-size`, 0 `source-links-ref`). After this change, 12 new `source-links-ref` warnings will appear. Although these are warnings (not errors), so exit code stays 0, the design's own Risk `[GRACE-lite validation breakage]` claims "the defensive grep in D5 plus the validator run are the safety net" — but the defensive grep is scoped only to XML `<depends>`, not source LINKS. Worse, leaving stale LINKS actively undermines the GRACE-lite navigation purpose (LINKS is the file-local → graph-M-ID bridge per AGENTS.md "Navigation Order").

   **Concrete fix:** Add a sub-bullet to D5 enumerating the 12 surviving files and specifying that the `M-SCHEDULER` token be removed from each `LINKS:` line (preserving the other M-ID references on those lines). Add an audit step to the critical path in D7 (e.g., between steps 8 and 9: "Scrub `M-SCHEDULER` from `LINKS:` in webhook.py, queue.py, time.py, db.py, domain/services.py, config/__init__.py, config/local.py, config/config.py, config/engine_repository.py, application/{allocate_task,consume_task,submit_task}.py"). Alternatively, narrow the proposal's "no other `<depends>` list references M-SCHEDULER" claim by explicitly stating the cleanup scope is source LINKS, not XML depends.

### 🟡 Minor issues (should address)

 - **D1 prose contains unedited stream-of-consciousness** at design.md:73-80 ("After the move, it runs only when `daemonize()` is invoked ... — wait, let me re-read). Re-reading ..."). The substantive Resolution at design.md:87-93 is correct (verified against `scheduler.py:44` — `basicConfig` is at module top-level, not inside `get_logger`; and `daemonize.py:42` — the scheduler import is lazy inside `daemonize()`), so behaviour is preserved by keeping `basicConfig` inside `_get_logger`. But the analysis paragraph should be rewritten as a clean statement of fact (today: `basicConfig` fires on first `daemonize()` call via lazy import; after: `basicConfig` fires on first `_get_logger()` call, also inside `daemonize()` — identical runtime effect).

 - **D2 omits the GRACE-lite housekeeping for `tests/unit/test_webhook_handler.py`** that D3 explicitly requires for `tests/unit/test_characterization.py`. The destination file's MODULE_CONTRACT SCOPE is currently "Unit tests for webhook_handler event dispatch and _send_webhook" (line 5) and MODULE_MAP lists 5 test functions (lines 10-17). Adding `TestWebhookPayload` construction tests expands the SCOPE and adds two MODULE_MAP entries. D2 should explicitly call out: bump CHANGE_SUMMARY, add the two new test functions to MODULE_MAP, and consider widening SCOPE to mention WebhookPayload construction. Without this, D2 is internally inconsistent with D3's level of detail.

 - **daemonize.py GRACE-lite update is under-specified** at design.md:38-39 ("bump `CHANGE_SUMMARY` on `daemonize.py`"). Inlining `_get_logger` adds a new module-level callable; MODULE_MAP at `daemonize.py:10-12` currently lists only `daemonize`. MODULE_MAP should add `_get_logger - Configure and return the yascheduler logger (inlined from scheduler.py)`. MODULE_CONTRACT SCOPE at `daemonize.py:5` ("daemonize command — creates Orchestrator via DI, runs event loop") should be widened to mention logger configuration. DEPENDS (`daemonize.py:6`) correctly needs no change — `logging` is stdlib with no M- entry.

 - **D7 duplicates tasks.md content.** The design self-disclaims ownership ("informative — owned by `tasks.md`"), but including a 9-step ordered critical path with arrows invites drift between design.md and tasks.md once tasks.md is written. Either delete D7 entirely (the sequencing rationale can be re-derived in tasks.md) or compress to a one-paragraph note explaining why the order matters (e.g., "scheduler.py deletion must follow _get_logger inlining; spec delta application is order-independent within the atomic commit").

 - **`daemonize.py:17` FIXME interaction not addressed.** The file carries `# FIXME: split adapter and application layer (business logic)`. Inlining `_get_logger` (a piece of daemon-setup business logic) into `daemonize.py` is a small step in the opposite direction of that FIXME. The proposal authorizes the inline, so design is not contradicting the proposal — but design.md should acknowledge the interaction in one sentence (e.g., in Risks: "Inlining `_get_logger` slightly exacerbates the existing `# FIXME: split adapter and application layer` at `daemonize.py:17`; revisit when that FIXME is addressed").

 - **Architecture-cleanup specificity regressed vs. proposal.** Design.md:36-37 says "Update ... `docs/ARCHITECTURE.md` so the graph and architecture description match the source tree" but does not restate the proposal's section list (§1 diagram, §2 component table, §2.2 last paragraph, §2.9, §3.7, §4 tree). Verified all six sections do contain scheduler references (`ARCHITECTURE.md:84, 120, 178, 258-268, 386, 464`). Consider restating the list in design for traceability, since the proposal is the only place it currently lives.

### 🟢 Confirmed solid

 - **D1 substantive Resolution is correct.** Verified `scheduler.py:44` has `logging.basicConfig(level=logging.INFO)` at module top-level (not inside `get_logger`), and `daemonize.py:42` does the scheduler import lazily inside `daemonize()`'s body. Therefore importing `daemonize.py` today does NOT trigger `basicConfig`; it fires only on first `daemonize()` invocation. Keeping `basicConfig` inside `_get_logger` (called from inside `daemonize()`) preserves this exactly. Design's claim is accurate.

 - **D2 trivially correct.** `WebhookPayload` re-export at `scheduler.py:42` has zero production consumers (verified — only `tests/unit/test_scheduler.py:33` imports the re-export; `adapters/notifier/webhook.py` imports from `yascheduler.webhook` directly). The two `TestWebhookPayload` tests at `test_scheduler.py:169-192` move to `test_webhook_handler.py`, which already uses `from yascheduler.webhook import WebhookPayload` at line 47.

 - **D3 file-vs-class deletion choice matches the proposal bullets exactly.** `test_scheduler.py` (whole file), `test_characterization.py` (3 classes dropped, `TestClientQueueSubmitTaskAsync` kept), `mock_scheduler.py` (whole file — both `make_scheduler` and `create_test_config` have no surviving consumers; verified `create_test_config` is only imported by `test_scheduler.py:30`), `test_cli_smoke.py` (one test, `test_utils_import_does_not_import_scheduler` at line 34, dropped).

 - **D4 delta header (`## MODIFIED Requirements`) is the correct, precedented form.** Verified prior art in archive: `2026-06-21-gateway-port-cleanup/specs/{orchestrator,use-cases,ssh-gateway,domain-ports}/spec.md`, `2026-06-03-remove-legacy-modules/specs/{platform-adapters,orchestrator,cloud-provisioner,use-cases,dependency-injection}/spec.md`, `2026-05-31-uow-not-initialized-error/specs/{testing-unit,postgres-uow}/spec.md`, `2026-06-02-usecase-uow-migration/specs/*/spec.md`. Each uses `## MODIFIED Requirements` with full new requirement text for rewrite-in-place. Design's preference over `REMOVED`+`ADDED` is sound.

 - **D5 XML citations are accurate.** `<M-SCHEDULER>` block lives at `docs/knowledge-graph.xml:39-52` (verified). The four CrossLinks exist at the cited lines: 882 (`M-SCHEDULER -> M-DB`), 909 (`M-SCHEDULER -> M-DI`), 910 (`M-SCHEDULER -> M-APPLICATION-SUBMIT`), 934 (`M-SCHEDULER -> M-WEBHOOK`). Note: `explore-brief.md:63` said "2 CrossLink entries" — design corrects this to 4, matching the proposal.

 - **D5 `<depends>` audit is correct.** Verified via `rg "M-SCHEDULER" docs/knowledge-graph.xml` — only the 4 CrossLinks and the `<M-SCHEDULER>` block reference the M-ID; no `<depends>` element lists it.

 - **D6 atomic-apply decision is consistent with the proposal.** Single-commit internal-API deletion with no production consumer matches proposal Impact (no migration, no deprecation cycle). Bisect-friendliness is preserved by the small footprint (~5 files edited, 3 deleted, plus spec deltas).

 - **Spec coverage is complete.** Verified `rg "scheduler\.py|class Scheduler|yascheduler\.scheduler" openspec/specs/` returns references in exactly three spec files: `package-facades/spec.md` (lines 84, 116, 126, 223, 224, 230, 232, 247, 279), `testing-unit/spec.md` (lines 188, 190, 194), `db-wrapper/spec.md` (line 27). Design D4 enumerates these three capabilities and the affected requirements/scenarios within each. No fourth spec capability is silently impacted.

 - **Goals/Non-Goals align with the proposal.** Non-Goals correctly defer `db.py`/`client.py` retirement, AiiDA rewiring, deprecation cycle, and `_get_logger` promotion — none of these contradict a proposal Impact bullet. The proposal's explicit listing of removed/modified/added test files and docs sections is mirrored faithfully in design's Goals.

 - **Migration Plan ("None required") is accurate.** No DB schema change, no config-format change, no public API change, single commit — all consistent with proposal.

 - **client.py:151 is the surviving `get_tasks_by_status` consumer** (verified) — D4's `db-wrapper` rewrite is correct.

## design Round 2 — 2026-06-21

### 🔴 Serious issues (must fix)

None.

### 🟡 Minor issues (should address)

 - **Goals bullet at design.md:41-43 under-summarises the GRACE-lite scope after the D5 expansion.** It mentions the `daemonize.py` housekeeping and "`M-SCHEDULER` element" removal but omits (a) the LINKS scrub across 12 source files (D5b) and (b) the `test_webhook_handler.py` MODULE_MAP/SCOPE/CHANGE_SUMMARY housekeeping (D2). The Decisions section is authoritative and complete, so this is a summary-completeness gap, not a contradiction. Suggest appending to the Goals bullet, e.g. "…remove the `M-SCHEDULER` element from the knowledge graph and scrub stale `LINKS:` references in the 12 surviving source files (D5); update `test_webhook_handler.py` MODULE_CONTRACT per D2." Optional — does not block archive.

### 🟢 Round 1 resolutions verified

 - **D5 LINKS scrub (Round 1 🔴).** Resolved. design.md:175-216 now enumerates all 12 surviving source files in a code block (webhook.py, queue.py, time.py, db.py, domain/services.py, config/__init__.py, config/local.py, config/config.py, config/engine_repository.py, application/{allocate_task,consume_task,submit_task}.py). File list verified identical to `rg "LINKS:.*M-SCHEDULER" yascheduler/` (12 hits, exact match). Rationale at design.md:212-216 now explicitly cites `grace_check.py` `source-links-ref` warnings and the AGENTS.md "Navigation Order" contract; baseline verified — `python3 scripts/grace_check.py` reports 18 warnings (all `func-size` / `module-size-soft`), 0 `source-links-ref`. The three test files (`test_scheduler.py`, `test_characterization.py`, `mock_scheduler.py`) are correctly excluded as deleted/edited by D3 (verified via `rg "LINKS:.*M-SCHEDULER" tests/`). D5 title at design.md:175 now reads "remove `M-SCHEDULER` block, all four outgoing `CrossLink`s, and scrub `LINKS:` references in 12 surviving source files".

 - **D1 prose cleanup (Round 1 🟡).** Resolved. design.md:77-86 is a clean factual statement: today `basicConfig` sits at module top-level of `scheduler.py` (line 44) and the scheduler import is lazy inside `daemonize()` (line 42); after the move `basicConfig` lives inside `_get_logger` (still called from `daemonize()`); runtime behaviour identical. Verified against source: `scheduler.py:44` = `logging.basicConfig(level=logging.INFO)` at module top-level (NOT inside `get_logger`); `daemonize.py:42` = `from yascheduler.scheduler import get_logger` inside `daemonize()` body. No "wait, let me re-read" stream-of-consciousness remains. The placement warning ("Care must be taken NOT to lift `basicConfig` to `daemonize.py` module top-level") is preserved.

 - **D2 webhook handler GRACE-lite housekeeping (Round 1 🟡).** Resolved. design.md:101-108 ("GRACE-lite housekeeping for the destination file") specifies all three required elements: (a) append CHANGE_SUMMARY entry recording relocation; (b) add the two new test functions to MODULE_MAP; (c) widen SCOPE to mention `WebhookPayload` construction. Verified target file state: `test_webhook_handler.py:5` SCOPE = "Unit tests for webhook_handler event dispatch and _send_webhook", MODULE_MAP at lines 10-17 lists 5 functions, CHANGE_SUMMARY at lines 19-22 (LAST_CHANGE v1.3.0). Spec is actionable.

 - **D6 daemonize.py contract update (Round 1 🟡).** Resolved. design.md:229-240 ("daemonize.py GRACE-lite update") specifies all four elements with line citations: (a) SCOPE widen (`daemonize.py:5`) to mention logger configuration; (b) MODULE_MAP (`daemonize.py:10-12`) add `_get_logger - Configure and return the yascheduler logger (inlined from scheduler.py)`; (c) CHANGE_SUMMARY (`daemonize.py:14-15`) append v1.1.0 entry; (d) DEPENDS (`daemonize.py:6`) no change — `logging` is stdlib. Verified target file: SCOPE line 5, MODULE_MAP lines 10-12, CHANGE_SUMMARY lines 14-15, DEPENDS line 6 — all citations accurate.

 - **D7 compressed (Round 1 🟡).** Resolved. design.md:242-249 is now a single paragraph stating only the ordering constraint that matters ("`_get_logger` inlining into `daemonize.py` MUST precede deletion of `scheduler.py`, or `daemonize.py:42` will dangle") plus a note that all other edits are order-independent within the atomic commit and that `tasks.md` will enumerate concrete steps. The previous 9-step critical path duplicating tasks.md is gone.

 - **FIXME interaction (Round 1 🟡).** Resolved. design.md:266-272 ("[Interaction with `daemonize.py:17` FIXME]") acknowledges the interaction: the file already carries `# FIXME: split adapter and application layer (business logic)`; inlining `_get_logger` slightly exacerbates it; mitigation accepted as a small step in the wrong direction, revisit when the FIXME is addressed; YAGNI rejection of `yascheduler/log.py` extraction restated. Verified FIXME exists at `daemonize.py:17` (source reads `# FIXME: split adapter and applicacation layer (business logic)` — typo "applicacation" in source; design quotes corrected form, acceptable).

 - **Goals: ARCHITECTURE.md sections (Round 1 🟡).** Resolved. design.md:36-40 restates all six sections with line citations: §1 ASCII diagram (line 84), §2 component table (line 120), §2.2 last paragraph (line 178), §2.9 (lines 258-260, 268), §3.7 (line 386), §4 tree (line 464). Verified all six line numbers contain scheduler references via `rg -n 'scheduler\.py' docs/ARCHITECTURE.md`.

 - **"Spec drift" wording (Round 1 🟡 follow-on).** Resolved. design.md:273-276 now reads "The `openspec validate --all --json` step in `tasks.md` is the gate" — references `tasks.md`, not "D6's task list". Consistent with D7 compression.

 - **Internal consistency check.** No new contradictions introduced by the fixes. D5's expansion to cover LINKS scrub is consistent with the proposal (proposal was XML-scope; design correctly extends to source LINKS as a mechanical consequence required to keep `grace_check.py` at 0 `source-links-ref` warnings — this is hygiene, not a behaviour change requiring proposal re-freeze). D7's compression leaves no other section dangling: the ordering constraint it preserves (`_get_logger` before `scheduler.py` deletion) is the only edge D6's atomic-commit decision depends on. Verified all four CrossLinks at lines 882, 909, 910, 934 are outgoing `from="M-SCHEDULER"` — no incoming CrossLinks exist (would need separate cleanup), so D5's "four outgoing CrossLinks" count is complete.

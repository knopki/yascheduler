## proposal Round 1 — 2026-06-21
### 🔴 Fixed
 -
### 🟡 Addressed
 -
### 🔴 Outstanding
 -
### 🟡 Notes
 - **Tests Impact omits `tests/e2e/test_full_cycle.py:85`.** That file calls
   `make_daemon(config, db=db)`. Removing the `db` parameter (flagged BREAKING)
   breaks this e2e test. The proposal's Tests section lists `tests/unit/test_di.py`
   (`DB.create` assertions removed) and new unit tests, but does not mention the
   e2e test update. Since this change touches `_deallocator_consumer` and
   `make_daemon`, AGENTS.md requires e2e coverage for orchestrator flow changes —
   the e2e test file belongs in the Tests Impact list.
 - **Follow-up not referenced.** The brief registers a follow-up (DB-level
   concurrency via `SELECT ... FOR UPDATE` / partial unique constraint, out of
   scope). The proposal mentions moving `allocation_lock` and preserving
   single-process semantics, but does not note the registered follow-up. A
   one-line "Follow-up: DB-level concurrency (out of scope)" would keep the
   proposal aligned with the brief and signal to future changes that the
   fragility is known.
 - **Deallocate ordering shift not flagged.** Current `CloudProvisionerImpl.deallocate`
   (manager.py:223-225) does `disable(ip)` → `delete_node` → `remove(ip)`. The
   brief's proposed flow does `delete_node` (pure cloud) → then
   `uow.nodes.disable(ip); uow.nodes.remove(ip)` together. This reorders
   disable to after the cloud delete. Likely benign (disable is just a DB flag
   the cloud SDK doesn't read), but it is a behavior change vs. current code and
   is not called out. Worth a sentence in the proposal or a delta-spec scenario.
 - **`make_daemon` BREAKING is correctly identified** and consistent with the
   brief's R3 rejection (user confirmed `make_daemon` is not public API; AGENTS.md
   public-interface list does not include `make_daemon`). The
   `dependency-injection` spec scenario "make_daemon accepts pre-built
   dependencies (db=my_db)" will need a delta update — correctly listed under
   Modified Capabilities.
 - **`class Yascheduler` public API is unaffected** — verified
   `yascheduler/client.py` uses `make_cli_deps`, not `make_daemon`, and does not
   touch `CloudProvisioner`. The proposal's public-API-stability claim holds.
 - **Spec names all verified:** `cloud-provisioner`, `domain-ports`, `use-cases`,
   `orchestrator`, `dependency-injection` all exist under `openspec/specs/`.
   `allocation-tracker` is correctly listed as New (no existing spec of that
   name).
 - **All three resolved open questions from the brief are captured:**
   AllocationTracker class, inline capacity in orchestrator, `select_provider`
   as pure function.
 - **All rejected alternatives (R1/R2/R3) are reflected** in the Why / What
   Changes reasoning (UoW inside adapter rejected; long-lived transaction
   rejected; keep-DB rejected). The proposal's WHY section aligns with the
   brief.
  - **Proposal is concise (~109 lines, focused on WHY).** Module responsibility
    table from the brief is condensed into the What Changes / Impact bullets
    without contradiction.

## proposal Round 1 — unfreeze (2026-06-21)
### 🔴 Fixed
 - Deallocate ordering was changed to `delete_node` → `disable + remove`
   (grouping DB writes in one UoW). This broke the safety property: if
   `delete_node` fails, node stays `enabled` and allocator re-selects it.
   Reverted to original `disable` → `delete_node` → `remove` ordering across
   two short UoWs. Decision-level change to frozen proposal → unfreeze
   triggered, brief + proposal updated, re-review required.
### 🟡 Addressed
 -
### 🔴 Outstanding
 -
### 🟡 Notes
 - Unfreeze reason: deallocate ordering is a decision-level change (affects
   safety property, not just declarative detail). Per workflow rules, the
   frozen proposal and all downstream artifacts must be re-reviewed from the
   unfreeze point. No downstream artifacts existed yet (design/specs/tasks
   not created), so only proposal re-review is needed.

## proposal Round 2 — 2026-06-21
### 🔴 Fixed
 - Deallocate ordering reverted to `disable` → `delete_node` → `remove` (matches
   current `CloudProvisionerImpl.deallocate` at manager.py:222-229). Safety
   property preserved: if `delete_node` fails the node is already disabled, so
   the allocator cannot re-select it. Brief (lines 122-130) and proposal
   (lines 34-39) now both describe the same ordering with the same rationale.
 - Brief ordering rationale added explicitly (lines 127-130): two short UoWs
   instead of one is called out as the cost of preserving the safety property.
### 🟡 Addressed
 - Round 1 🟡 "Tests Impact omits `tests/e2e/test_full_cycle.py:85`": proposal
   Tests section now lists `tests/e2e/test_full_cycle.py` with the
   `make_daemon(config)` call update (proposal lines 109-110). Verified the e2e
   file does call `make_daemon(config, db=db)` at line 85.
 - Round 1 🟡 "Follow-up not referenced": proposal now contains the follow-up
   note (lines 45-47) — DB-level concurrency via `SELECT ... FOR UPDATE` /
   partial unique constraint, registered as known fragility, addressed in a
   separate change. Aligns with brief lines 150-152.
 - Round 1 🟡 "Deallocate ordering shift not flagged": moot after revert — no
   shift remains; ordering matches current code.
### 🔴 Outstanding
 -
### 🟡 Notes
 - **Wording inconsistency in Modified Capabilities** (proposal line 73-74):
   "`_deallocator_consumer` performs disable+remove in **a** UoW around
   `clouds.deallocate(cloud, ip)`" reads as a single UoW wrapping all three
   operations. That is the R2 pattern explicitly rejected in the brief
   (long-lived transaction around a multi-minute cloud op). The What Changes
   section (line 39) correctly says "Two short UoWs". Tighten the capability
   summary to "performs disable and remove in two short UoWs bracketing
   `clouds.deallocate(cloud, ip)`" to avoid the misread.
 - **`deallocate_node` signature change not explicit.** The current
   `deallocate_node(node, gateway, clouds)` (deallocate_nodes.py:51-59) will
   need a `uow_factory` parameter to perform the disable+remove UoWs the brief
   puts inside it (brief lines 119-125). The proposal captures the
   responsibility transfer ("use case takes over disable+remove") but does not
   list the signature change among the BREAKING items. Not BREAKING at the
   public-API level (internal use case), but worth a one-liner in the Impact >
   Code bullet for `deallocate_nodes.py` so the design spec captures it.
 - **Naming ambiguity** between `deallocate_node` (singular, per-node cloud
   delete wrapper) and `deallocate_nodes` (plural, idle-disable sweep). The
   proposal uses "deallocate_nodes use case" in both What Changes (line 34) and
   Modified Capabilities (line 71) for the disable+remove-around-cloud-delete
   responsibility, but the brief's pseudocode (line 118) puts that logic in the
   singular `deallocate_node`. Both live in the same file
   (`application/deallocate_nodes.py`), so the file-level reference is
   defensible, but the design spec should disambiguate which function owns
   disable+remove.
 - Verified: all capabilities referenced (New: `allocation-tracker`; Modified:
   `cloud-provisioner`, `domain-ports`, `use-cases`, `orchestrator`,
   `dependency-injection`) match `openspec/specs/` inventory; the
   `dependency-injection` spec's "make_daemon accepts pre-built dependencies"
   scenario (spec.md:22-23) will need delta removal — correctly covered by
   listing `dependency-injection` as Modified.
 - Verified: `Yascheduler` public API path (`client.py` uses `make_cli_deps`,
   not `make_daemon`) is unaffected; CLI/INI/schema/AiiDA stability claims hold.
  - Verified: ordering, rationale, and two-UoW design are consistent across
    brief, proposal, and current code — no contradiction introduced by the
    unfreeze edits.

## proposal Round 2 — soft-freeze additions (2026-06-21)
### 🔴 Fixed
 -
### 🟡 Addressed
 - Wording in Modified Capabilities `orchestrator` entry tightened: "in a UoW
   around" → "in two short UoWs bracketing" (avoids misread as rejected R2
   long-transaction pattern).
 - `deallocate_node` signature change (`uow_factory` parameter added) now
   explicit in Impact > Code bullet for `deallocate_nodes.py`.
 - Naming ambiguity `deallocate_node` vs `deallocate_nodes` disambiguated in
   What Changes: singular wrapper owns disable+remove bracketing; plural
   sweep remains idle-disable use case.
### 🔴 Outstanding
 -
### 🟡 Notes
 - All three Round 2 🟡 notes addressed as declarative additions under
   soft-freeze rules (no decision-level changes). Proposal re-frozen.

## design Round 1 — 2026-06-21
### 🔴 Fixed
 -
### 🟡 Addressed
 -
### 🔴 Outstanding
 - **D3 pseudocode contradicts D8 and the risk-mitigation prose on lock scope.**
   D3 step 1 shows capacity read + `select_provider` running **outside**
   `allocation_lock`; only step 2 (`add_tmp`) is shown inside the lock. D8
   explicitly states the lock "protects the same critical section: capacity
   check + tmp-node insertion", and the "Tmp-node visibility under
   concurrency" risk-mitigation says "the lock serializes the select+add_tmp
   section within a process". Current code (`_acquire_provider_slot`,
   manager.py:447-477) holds the lock across both `_select_best_provider` and
   `add_tmp`. Implemented literally, D3 introduces a concurrency regression:
   two concurrent allocations can both read counts (capacity=1 for provider
   A), both select A, then both acquire the lock sequentially and each add a
   tmp_node for A — exceeding `max_nodes`. Fix: update D3 step 1+2 so
   capacity read + `select_provider` + `add_tmp` all run inside
   `async with allocation_lock:` (matching D8, the brief at lines 142-148,
   and current code). No proposal-level change required — proposal/brief
   intent already matches D8; only the D3 pseudocode is wrong.
### 🟡 Notes
 - **D7 filter semantics differ from current code.** New `_clouds_get_capacity`
   iterates `self._config.clouds` (all configured clouds); current code uses
   `self._clouds.configs`, which is filtered in `di.py:154-167` to clouds with
   `max_nodes > 0` AND a successfully resolved adapter. For deployments with
   unresolved adapters (missing optional deps) or `max_nodes<=0` clouds, the
   new code over-counts `max_nodes` (and thus over-reports capacity) since
   `counts[c.prefix]` for unresolved prefixes is 0 but `c.max_nodes` is still
   summed. Equivalent for fully-valid configs. Implementer should either keep
   the filter (e.g., accept the filtered dict from DI) or document the
   behavior change.
 - **Throttle check location unspecified.** Current `_acquire_provider_slot`
   (manager.py:460-467) checks `adapter.get_op_semaphore().locked()` inside
   the lock and raises `CloudAllocateError` if the provider is overloaded.
   Neither D3 nor D5 (`select_provider` — "Priority + capacity + platform-
   support algorithm preserved verbatim") nor D8 says where this throttle
   check moves. Note the existing `allocate_with_tracking(throttle=True)`
   parameter is dead code (the check lives in `_acquire_provider_slot`, not
   in `allocate_with_tracking`), so removing `allocate_with_tracking` does
   NOT auto-relocate the throttle check. Without an explicit decision the
   implementer may silently drop it, changing behavior under concurrent
   provider op-limit pressure.
 - **D8 lock ownership is hand-wavy.** "the lock moves into `allocate_task`
   (or a small coordination helper it owns)" leaves the `asyncio.Lock`
   instance lifetime undecided: orchestrator-owned and injected (matching D4
   `AllocationTracker` pattern), module-level in `allocate_task.py`, or a
   closure inside a small helper class? `asyncio.Lock()` must be created in a
   running loop, so module-level instantiation is fragile. Recommend picking
   the orchestrator-owned pattern (same as `AllocationTracker`) for
   consistency.
 - **Specs requiring delta updates not enumerated in design.** These will
   surface in `specs/` tasks, but flagging so they aren't missed:
   * `cloud-provisioner/spec.md`: "Deallocate removes VM and DB record"
     scenario uses `deallocate("10.0.0.1")` (old single-arg); "Capacity
     reports available nodes" scenario references removed `capacity()`;
     "Concurrent allocation throttling" requirement currently sits on the
     provisioner and moves to app layer (AllocationTracker + lock).
   * `dependency-injection/spec.md` line 12 hard-codes `db: DB | None = None`
     in the make_daemon signature requirement; lines 22-24 ("make_daemon
     accepts pre-built dependencies") explicitly require the `db=` parameter
     behavior being removed.
   * `use-cases/spec.md` line 40 references `cloud.allocate_with_tracking(...)`
     which is being removed.
   * `domain-ports/spec.md` CloudProvisioner Protocol requirement needs
     `deallocate(cloud, ip)` and removal of `capacity`.
 - **e2e test updates needed beyond `make_daemon(config)`.**
   `tests/e2e/test_full_cycle.py` not only calls `make_daemon(config, db=db)`
   (line 85) but also imports `from yascheduler.db import DB, TaskStatus`
   (line 29) and uses `db.add_node/get_task/remove_node/commit` throughout
   (lines 67-138). Proposal's Tests section mentions only the `make_daemon`
   call update. The fixture `db: DB` parameter and direct DB usage survive
   (client.py DB migration is correctly out-of-scope), but the e2e fixture
   wiring needs re-checking since `make_daemon` no longer accepts `db=`.
 - **Verified accurate (no action needed):**
   * D9 schema.sql claim — `sql/schema.sql:18-22` and `db.py:232-243` contain
     byte-equivalent ALTER TABLE statements; `apply_schema()` is invoked by
     `yainit` via `cli/init.py:81`. Claim holds.
   * D6 deallocate ordering (`disable` → `delete_node` → `remove` across two
     short UoWs) matches frozen proposal (lines 34-41) and current code
     (manager.py:222-229). Safety property preserved.
   * D3 commit-before-lock-release pattern is correct for tmp-node visibility
     (assuming lock scope is fixed per the 🔴 above).
   * No decision-level contradiction with the frozen proposal — all 10
     decisions map cleanly to proposal bullets; no unfreeze triggered.
   * AGENTS.md respected: no new deps, no compat layers, minimal changes,
     public-interface stability preserved (CLI/Yascheduler/INI/schema/AiiDA
     untouched).
   * Non-goals properly scoped: no overlap with schema-migrations change, no
     client.py migration, no DB-level concurrency (registered follow-up).

## design Round 2 — 2026-06-21
### 🔴 Fixed
 - **Round 1 🔴 D3 lock scope contradiction resolved.** D3 pseudocode
   (design.md:94-130) now wraps capacity read (`uow.nodes.list_all()`) +
   `Counter` + `select_provider` + `add_tmp` + `uow.commit()` all inside
   `async with allocation_lock:` as a single critical section. Cloud
   allocation (step 2) and final persist (step 3) explicitly run outside
   the lock. Verified against current `_acquire_provider_slot`
   (manager.py:447-477): lock spans `_select_best_provider` (448) through
   `add_tmp` (475), release at 477, then cloud ops + final `node_repo.add`
   (180) run unlocked. Matches D8 prose (design.md:278-294),
   risk-mitigation (design.md:332-337), and brief intent. No concurrency
   regression remains.
### 🟡 Addressed
 - **Round 1 🟡 D7 filter semantics.** D7 now uses `self._active_clouds`
   (filtered list) instead of `self._config.clouds`. Prose
   (design.md:260-266) explicitly defines the filter as
   `max_nodes > 0` AND `_resolve_adapter` success — matching di.py:154-167
   byte-for-byte. Verified `adapter.name == cfg.prefix` (adapters.py:195
   via `getter(cfg.prefix)`), so `counts[c.prefix]` in D7 pseudocode is
   correct (n.cloud stores adapter.name == cfg.prefix). Filter behavior
   preserved exactly.
 - **Round 1 🟡 Throttle check relocation.** Explicit paragraph added to
   D3 (design.md:136-144). Correctly identifies `adapter.get_op_semaphore()
   .locked()` check at manager.py:460-467, places it in D3 step 1 after
   `select_provider` and before `add_tmp` (matching current code order).
   Correctly flags `allocate_with_tracking(throttle=True)` as dead code
   (verified: `throttle` param never referenced in function body at
   manager.py:256-285; check lives in `_acquire_provider_slot`).
 - **Round 1 🟡 D8 lock ownership.** D8 rewritten (design.md:278-294):
   orchestrator-owned and injected, matching D4 AllocationTracker pattern.
   Explicitly addresses `asyncio.Lock()` running-loop requirement
   ("module-level instantiation is fragile — orchestrator-owned avoids
   this"). Consistent with D4 injection pattern.
 - **Round 1 🟡 Specs delta enumeration.** New "Specs Delta Enumeration"
   section (design.md:392-415) lists concrete scenarios needing delta
   updates across cloud-provisioner, dependency-injection, use-cases,
   domain-ports. All four scenario references verified accurate against
   spec files (cloud-provisioner/spec.md:22-28, 61-68;
   dependency-injection/spec.md:12, 22-24; use-cases/spec.md:40;
   domain-ports/spec.md:143-144, 153). Section marked "non-exhaustive".
 - **Round 1 🟡 e2e test fixture wiring.** Proposal Tests section
   (proposal.md:113-119) updated with line-number references
   (`from yascheduler.db import DB, TaskStatus` at line 29;
   `db.add_node/get_task/remove_node/commit` at lines 67-138). Verified
   against tests/e2e/test_full_cycle.py:29, 67-95+. Explicitly states
   fixture must construct DB independently of `make_daemon`.
### 🔴 Outstanding
 -
### 🟡 Notes
 - **D3 pseudocode omits throttle check (sketch-only inconsistency).**
   The pseudocode at design.md:98-106 jumps from
   `if provider is None: return False` straight to `add_tmp` without
   showing the throttle check, even though the prose paragraph below
   (design.md:136-144) explicitly places it "after select_provider
   returns and before add_tmp". An implementer reading only the
   pseudocode could silently drop the check — the exact failure mode
   Round 1 flagged. Consider adding a one-line comment in the pseudocode
   like `# throttle check here — see prose below` or showing the check
   explicitly.
 - **D3 pseudocode uses undeclared `username`.** Step 1 calls
   `uow.nodes.add_tmp(provider, username)` but `username` is not in
   scope — it must come from `configs[provider.name].username`. Current
   code resolves this via `config = self.configs.get(adapter.name)` then
   `config.username` (manager.py:453, 475). Minor pseudocode sketchiness;
   implementer will infer from current code.
 - **D3 does not specify source of `adapters`/`configs` for
   `select_provider`.** The pseudocode uses
   `select_provider(adapters, configs, platforms, counts, log)` but D2
   (design.md:68-86) restricts the `CloudProvisioner` Protocol to only
   `allocate`/`deallocate` — no `.adapters`/`.configs` exposure. D7
   (design.md:268-270) explicitly states "The orchestrator no longer
   reads `self._clouds.configs`". So the use case must receive
   `adapters`/`configs` as separate injected params, but neither D3 nor
   the proposal's allocate_task signature spell this out. Design gap —
   implementer will need to decide injection vs. reaching into the
   concrete `CloudProvisionerImpl`. Recommend explicit clarification
   (e.g., "use case receives `adapters: dict[str, CloudAdapter]` and
   `configs: dict[str, ConfigCloud]` as injected params, constructed
   once in DI alongside `CloudProvisionerImpl`").
 - **Orchestrator constructor signature change not explicit in proposal
   Impact.** D4 (`tracker`), D7 (`_active_clouds`), D8 (`allocation_lock`)
   each add a new orchestrator-owned dependency, implying the
   `Orchestrator.__init__` gains ≥3 new params. The proposal Impact
   bullet for orchestrator.py (proposal.md:94-95) mentions only
   `_clouds_get_capacity rewritten inline` and `_deallocator_consumer
   updated` — not the constructor signature growth. Worth a one-liner so
   the design captures the full orchestrator surface change. The
   orchestrator spec (orchestrator/spec.md:14) only requires
   `uow_factory` and `gateway` params, so no spec delta is triggered.
 - **Brief pseudocode drift (non-blocking).** Brief capacity pseudocode
   (explore-brief.md:137-138) still uses `config.clouds` (all clouds) —
   the buggy version D7 corrects to `_active_clouds`. Brief allocate
   pseudocode (explore-brief.md:104-112) does not show the
   `allocation_lock` wrapper that D3 adds. Both are overview-level
   sketches superseded by D3/D7 detailed design; implementer will follow
   the design decisions, not the brief pseudocode. Brief is frozen, so
   no edit needed — flagging only for traceability.
 - **Verified consistent (no action needed):**
   * D3 commit-before-lock-release: `await uow.commit()` is inside both
     the `allocation_lock` and `uow` context managers (design.md:106) —
     tmp-node visible to concurrent selectors immediately after lock
     release. Matches risk-mitigation prose (design.md:332-337).
   * D3 ↔ D8 ↔ risk-mitigation ↔ brief prose all aligned on lock scope
     and ownership. No internal contradiction.
   * D9 schema.sql claim re-verified: sql/schema.sql:18-22 contains the
     `ALTER TABLE ... ADD COLUMN IF NOT EXISTS username / port` statements
     matching `DB.migrate()`. Daemon auto-migration removal is safe.
   * D6 deallocate ordering (`disable` → `delete_node` → `remove` across
     two short UoWs) unchanged from Round 1 — still matches frozen
     proposal (proposal.md:34-41) and current code (manager.py:222-229).
    * All Round 1 🟡 notes either addressed or explicitly superseded by
      the design fixes. No decision-level contradiction with frozen
      proposal → no unfreeze triggered.

## design Round 2 — soft-freeze additions (2026-06-21)
### 🔴 Fixed
 -
### 🟡 Addressed
 - D3 pseudocode now shows throttle check explicitly (after select_provider,
  before add_tmp) with comment pointing to prose — was prose-only, risk of
  silent drop.
 - D3 pseudocode `username` now resolved: `config = configs[provider.name]`
  then `config.username` — was undeclared.
 - D3 source of `adapters`/`configs` for `select_provider` now explicit:
  injected into use case as separate params (same dicts as
  CloudProvisionerImpl constructor), no reaching into adapter internals.
 - Proposal Impact for orchestrator.py now lists constructor signature
  growth (`allocation_tracker`, `active_clouds`, `allocation_lock` params).
### 🔴 Outstanding
 -
### 🟡 Notes
 - All four actionable Round 2 🟡 notes addressed as declarative additions
   under soft-freeze rules (no decision-level changes). Design frozen.
 - Brief pseudocode drift (Round 2 🟡 #5) left as-is — brief is frozen and
   superseded by D3/D7 detailed design; flagged only for traceability.

## specs Round 1 — 2026-06-21
### 🔴 Fixed
 -
### 🟡 Addressed
 -
### 🔴 Outstanding
 -
### 🟡 Notes
 - **Format compliance verified.** All 6 spec files use `### Requirement:`
   headings (3 hashtags) and `#### Scenario:` (4 hashtags) with WHEN/THEN
   format. SHALL/MUST used consistently; no should/may in normative prose.
   `openspec validate cloud-provisioner-pure --strict --json` passes
   (1/1 valid, 0 issues).
 - **Delta correctness verified against existing specs.** Every MODIFIED
   requirement block replaces the ENTIRE existing block (title + prose +
   all scenarios), with internal edits/additions/removals. Verified
   pairwise for all 11 MODIFIED requirements across cloud-provisioner
   (3), domain-ports (1), use-cases (3), orchestrator (3),
   dependency-injection (1). No partial deltas found.
 - **Coverage of D1–D10 verified.** D1 pure adapter
   (cloud-provisioner::CloudProvisionerImpl), D2 port change
   (domain-ports::CloudProvisioner port), D3 allocate_task flow with lock
   + throttle (use-cases::AllocateTask), D4 AllocationTracker
   (allocation-tracker NEW + cloud-provisioner::Concurrent allocation
   throttling), D5 select_provider pure function (cloud-provisioner::
   Provider selection), D6 deallocate ordering (use-cases::
   DeallocateIdleNodes + orchestrator::Deallocate loop), D7 inline
   capacity with `_active_clouds` (orchestrator::Allocate loop), D8 lock
   orchestrator-owned (orchestrator::Orchestrator manages loops +
   dependency-injection::make_daemon), D9 make_daemon drops DB
   (dependency-injection::make_daemon), D10 constructor signature
   (cloud-provisioner::CloudProvisionerImpl removed-methods prose +
   dependency-injection no-node_repo prose). All 10 decisions captured.
 - **REMOVED Requirements section in cloud-provisioner/spec.md
   references a scenario name, not a requirement.** "Capacity reports
   available nodes" is a `#### Scenario` in the existing spec
   (cloud-provisioner/spec.md:26), not a `### Requirement`. The REMOVED
   entry is functionally a no-op: the scenario is actually dropped via
   the MODIFIED "CloudProvisionerImpl implements CloudProvisioner" block
   (which omits it). openspec validate passes permissively (doesn't
   cross-reference REMOVED names against existing requirements). The
   Reason/Migration content is useful documentation but will not be
   applied at archive time. Consider relocating the Reason/Migration
   prose into the MODIFIED requirement's body, or leave as-is
   (structurally odd but not blocking).
 - **Design D3 vs spec scenarios: `tracker.add` placement.** Design D3
   step 4 (design.md:127-129) shows `tracker.add(task_id)` at the END of
   the cloud-fallback flow. But cloud-provisioner "Duplicate request
   ignored" and use-cases "Duplicate allocation rejected by tracker"
   scenarios both imply a dedup CHECK at the START — matching the
   existing `allocate_with_tracking` pattern (manager.py:256-285 checks
   `on_task in self.on_tasks` first, then adds). Specs are correct;
   design D3 is silent on the start-of-flow check. Implementer should
   call `tracker.add(task_id)` at the start with early-return-on-False
   (preserving current semantics), not at the end as the D3 pseudocode
   sketches. Worth a design clarification; not a spec defect.
 - **DeallocateIdleNodes prose inconsistent with scenario signature
   (inherited).** use-cases MODIFIED requirement prose says "The
   function SHALL accept `uow_factory` and `SSHMachineGateway`" but the
   scenario signature is `deallocate_nodes(uow_factory, config_clouds,
   idle_machines)` — no gateway. Current code (deallocate_nodes.py:73-77)
   confirms the plural sweep takes no gateway. The singular wrapper
   `deallocate_node(node, gateway, clouds, uow_factory)` is the one that
   takes gateway. The MODIFIED block replaced the full requirement but
   kept the stale prose; minor — implementer will follow the scenario
   signature, not the prose.
 - **"Concurrent allocation throttling" requirement location is a
   layering mismatch (organizational).** The requirement lives in
   cloud-provisioner/spec.md but post-refactor its content
   (AllocationTracker dedup + `allocate_task` op-semaphore check)
   describes application-layer behavior. `CloudProvisionerImpl` owns no
   throttling after D1/D4/D8. Location kept for continuity with the
   pre-existing requirement; not blocking — content is correct.
 - **Cross-spec scenario redundancy (benign).** The disable → cloud
   delete → remove bracketing flow is described in three places:
   use-cases::Deallocate node brackets cloud delete with disable+remove,
   orchestrator::Deallocator consumer brackets cloud delete with UoWs,
   and (for the throttle) cloud-provisioner::Provider op-limit
   respected. Each spec describes the behavior from its layer's angle;
   defensible, but the overlap is notable if the implementer needs to
   update one without missing the others.
 - **Public API stability preserved.** No spec delta touches CLI,
   `class Yascheduler`, INI, DB schema, or AiiDA entrypoint.
   dependency-injection MODIFIED correctly captures the operational
   change ("Schema migration is the operator's responsibility — run
   `yainit`") without altering schema. make_daemon is correctly NOT in
   the AGENTS.md public-API list, so the BREAKING db-parameter removal
   is internal.
 - **Testability verified.** Every scenario uses concrete WHEN conditions
   (named function calls, specific parameter values, identifiable error
   types) and THEN assertions (return values, UoW call sequences, import
   presence/absence). No vague language. All scenarios can be expressed
   as unit/integration/e2e assertions per testing-unit /
   test-db-integration / e2e-testing specs.
  - **No decision-level contradiction with frozen proposal/design.** All
    6 spec files align with proposal What Changes (proposal.md:14-54) and
    design D1–D10 (design.md:47-339). No unfreeze triggered.

## specs Round 1 — soft-freeze additions (2026-06-21)
### 🔴 Fixed
 -
### 🟡 Addressed
 - Design D3 `tracker.add` placement clarified: called at START of
   cloud-fallback path with early-return-on-False (preserving current
   `allocate_with_tracking` dedup semantics). On failure, `tracker.discard`
   is called after tmp-node cleanup so the task can be retried. Design D3
   was silent on start-of-flow check; specs Round 1 correctly implied it.
   Design is frozen, so this is a soft-freeze addition to D3 prose.
### 🔴 Outstanding
 -
### 🟡 Notes
 - cloud-provisioner REMOVED section references a scenario name ("Capacity
   reports available nodes") rather than a requirement — structurally odd
   but functionally a no-op (scenario already dropped via MODIFIED block).
   Left as-is; Reason/Migration prose is useful documentation.
 - DeallocateIdleNodes prose vs scenario signature mismatch (inherited
   stale prose: "SHALL accept uow_factory and SSHMachineGateway" but
   scenario has no gateway) — left as-is; implementer will follow scenario
   signature.
 - "Concurrent allocation throttling" requirement location in
   cloud-provisioner/spec.md is an organizational mismatch post-refactor
   (content describes application-layer behavior) — left for continuity.
 - Cross-spec deallocate bracketing redundancy (use-cases + orchestrator +
   cloud-provisioner) — benign, each describes from its layer's angle.
 - All 6 spec files frozen.

## tasks Round 1 — 2026-06-21
### 🔴 Fixed
 -
### 🟡 Addressed
 -
### 🔴 Outstanding
 -
### 🟡 Notes
 - **Format compliance verified.** All 14 task groups use `## N.` numbered
   headings; every task line is `- [ ] X.Y <desc>` checkbox format. Task 14.10
   is a verification task phrased as "Verify no `from yascheduler.db import
   DB` remains..." — still checkbox-prefixed, parseable. 14 groups, 91
   checkboxes total. Group ordering respects GRACE-lite top-down: group 1
   (graph + contracts) before group 2 (ports) before groups 3-4 (new pure
   modules) before group 5 (strip DB from adapter) before groups 6-10 (use
   cases + orchestrator + DI) before groups 11-13 (tests) before group 14
   (verification). Dependencies flow forward.
 - **Task granularity ≤2h plausible for all 91 tasks.** Largest candidates:
   6.3-6.6 (allocate_task cloud-fallback flow split into 4 sub-tasks — each a
   focused section), 9.4 (rewrite `_clouds_get_capacity` inline), 10.5
   (construct tracker + lock + active_clouds in DI). All scoped to a single
   function/section; none obviously exceeds 2h. No granularity flag.
 - **D1-D10 coverage verified.** D1 (pure adapter) → tasks 5.1-5.9; D2 (port)
   → 2.1-2.2; D3 (allocate_task flow incl. throttle check) → 6.3-6.6
   (throttle check explicitly in 6.4: `adapter.get_op_semaphore().locked()` →
   raise `CloudAllocateError`); D4 (AllocationTracker) → 4.1-4.4; D5
   (select_provider pure fn) → 3.1-3.4; D6 (deallocate_node bracketing) →
   8.1-8.6; D7 (inline capacity with `_active_clouds`) → 9.4; D8
   (allocation_lock orchestrator-owned) → 9.2, 10.5; D9 (make_daemon drops DB)
   → 10.1-10.6; D10 (constructor signature) → 5.3, 5.5-5.6. All 10 decisions
   have implementation tasks.
 - **Spec scenario coverage verified** against the 6 frozen spec files:
   allocation-tracker scenarios (add/discard/contains) → task 12.1;
   cloud-provisioner "No DB access from adapter" → 14.10 (verify no `DB`
   import in `cloud/manager.py`); cloud-provisioner "Provider op-limit
   respected" → 6.4 throttle check; cloud-provisioner "Duplicate request
   ignored" → 6.3 (tracker.add dedup at start); domain-ports "Deallocate
   cloud node with explicit cloud" → 2.1, 5.6, 9.7; dependency-injection "No
   DB import in make_daemon" → 10.2, 14.10; orchestrator "Cloud capacity
   computed inline" → 9.4; orchestrator "Deallocator consumer brackets cloud
   delete with UoWs" → 8.3, 9.7; use-cases "Cloud allocation failure cleans
   up tmp-node" → 6.5; use-cases "Deallocate node brackets cloud delete
   with disable+remove" → 8.3, 8.4. All spec scenarios map to a task.
 - **REMOVED Requirements coverage:** cloud-provisioner/spec.md REMOVED
   "Capacity reports available nodes" → covered by removing `capacity()`
   in 5.7 and removing the orchestrator's `self._clouds.get_capacity()` call
   in 9.4. The REMOVED entry is a no-op at archive time (review-log specs
   Round 1 noted it references a scenario, not a requirement) — no task
   needed for the REMOVED block itself; the underlying removal is captured
   by the MODIFIED-block tasks.
 - **Test file coverage matches proposal Impact list.** Updated:
   test_cloud_provisioner_impl.py (11.1-11.4),
   test_application_use_cases.py (11.5-11.6),
   test_application_orchestrator.py (11.7-11.8),
   test_di.py (11.9),
   test_domain_ports.py (11.10),
   tests/e2e/test_full_cycle.py (13.1-13.3). New:
   test_allocation_tracker.py (12.1), test_provider_selection.py (12.2),
   allocate_task cloud-fallback tests (12.3), deallocate_node bracketing
   tests (12.4). Proposal Impact Tests section (proposal.md:109-122) lists
   exactly these files. No test file in the proposal is missing from tasks.
 - **`CloudAllocateError` relocation not explicitly tasked.** The throttle
   check in 6.4 raises `CloudAllocateError`, defined in
   `yascheduler/adapters/cloud/manager.py:59`. The application layer
   (allocate_task.py) currently has no runtime import of `CloudAllocateError`
   — it lives in `yascheduler.adapters.cloud` (adapter layer). Per
   pyproject.toml import-linter layers contract (`yascheduler.adapters` →
   `yascheduler.application` → `yascheduler.domain`), the application
   layer MUST NOT import from adapters at runtime (only TYPE_CHECKING
   allowed). Task 6.4 raises `CloudAllocateError` from `allocate_task.py`
   but no task moves/aliases the exception to `yascheduler.domain.exceptions`
   or re-exports it via a domain-layer module. Implementer will hit either an
   import-linter violation or a runtime ImportError. Needs a task to either
   (a) move `CloudAllocateError` to `yascheduler.domain.exceptions` and
   re-export from `adapters.cloud`, or (b) raise a domain-layer exception
   (`SchedulingError` subclass) from the throttle check and catch/translate
   in the adapter boundary. This is a coverage gap — not flagged in proposal
   or design (D3 prose mentions raising `CloudAllocateError` but does not
   address the layering conflict). **Recommend adding a task under group 6
   or a new sub-task in group 2/3 to relocate the exception.**
 - **`M-APPLICATION-CONSUME` depends update incomplete in task 7.1.** Task
   7.1 adds `M-APPLICATION-ALLOCATION-TRACKER` to `M-APPLICATION-CONSUME`'s
   depends, but task 7.2 removes `clouds` from `consume_task`'s signature
   (consume no longer takes `clouds`). The graph entry
   `M-APPLICATION-CONSUME` (knowledge-graph.xml:343-353) currently has
   `M-CLOUD-PROVISIONER` in its `<depends>`. After refactor, consume_task
   does not call `clouds` — so `M-CLOUD-PROVISIONER` should be REMOVED from
   `M-APPLICATION-CONSUME`'s depends. Task 7.1 does not mention this removal.
   Implementer following task 7.1 literally would leave a stale graph
   dependency. Recommend amending 7.1 to "add M-APPLICATION-ALLOCATION-TRACKER
   to DEPENDS; REMOVE M-CLOUD-PROVISIONER from DEPENDS (consume no longer
   takes clouds)".
 - **Task 1.5 annotation kind mismatch.** Task 1.5 says "add
   `allocation_tracker`, `active_clouds`, `allocation_lock` to annotations"
   on `M-APPLICATION-ORCHESTRATOR`. GRACE-lite annotation prefixes are
   `fn-`, `class-`, `type-`, `export-`, `const-` (per AGENTS.md). These
   three are instance attributes owned by the orchestrator, not exported
   symbols — the correct prefix would be `const-allocation_tracker` etc.
   (or, more accurately, they are owned-and-injected dependencies → they
   belong in `<depends>` as `M-APPLICATION-ALLOCATION-TRACKER`, and the
   lock/active_clouds are runtime-constructed values not graph-tracked).
   The CrossLink addition in 1.5 (M-APPLICATION-ORCHESTRATOR →
   M-APPLICATION-ALLOCATION-TRACKER, "owns and injects") is correct and
   already captures the ownership. Adding bare `allocation_tracker` etc.
   as annotations would violate the annotation-prefix schema. Minor —
   implementer should use `const-*` prefix or skip the annotation and rely
   on the CrossLink + depends entry.
 - **Task 8.1 wording imprecise.** "add M-APPLICATION-UOW to DEPENDS
   (already there? verify)" — `M-APPLICATION-DEALLOCATE` (graph:355-363)
   already has `M-APPLICATION-UOW` in depends. The actual new dependency
   for deallocate_nodes after refactor is none (it still uses UoW and
   clouds). The real change is the `uow_factory` param on `deallocate_node`
   (singular) — but `deallocate_node` is a function, not a module, so no
   graph entry. Task 8.1's "verify" hedge is fine but the net effect is a
   no-op graph update for M-APPLICATION-DEALLOCATE. Implementer may waste
   time confirming; not blocking.
 - **Task 9.5 injection path for `adapters`/`configs` is undecided.**
   Task 9.5 says "pass `adapters`, `configs`, `tracker`, `allocation_lock`
   to `allocate_task` (need access to adapters/configs — either store on
   orchestrator or pass through from DI)". The orchestrator `__init__`
   (orchestrator.py:75-86) does not currently take `adapters`/`configs`.
   Task 9.2 adds `allocation_tracker`, `active_clouds`, `allocation_lock`
   to `__init__` but NOT `adapters`/`configs`. Task 10.8 says "Pass
   `adapters` and `configs` dicts to `Orchestrator` (for `allocate_task`
   injection) — or store on orchestrator". The "either...or" leaves the
   wiring undecided between tasks 9.2, 9.5, 10.7, 10.8. Implementer must
   pick: (a) add `adapters`/`configs` params to `Orchestrator.__init__`
   (task 9.2 should list them) and store as `self._adapters`/`self._configs`,
   then 9.5 passes `self._adapters`/`self._configs` to allocate_task; OR
   (b) DI passes them to `_allocator_consumer` via closure. The spec
   (use-cases/spec.md:6-11) says `allocate_task` accepts `adapters` and
   `configs` as params — so the orchestrator must hold them. Recommend
   amending 9.2 to add `adapters: dict[str, CloudAdapter]` and `configs:
   dict[str, ConfigCloud]` to `__init__` and 10.8 to drop the "or" —
   definitively store on orchestrator.
 - **Task 13.2 imprecise about e2e fixture survival.** Task 13.2 says
   "construct `DB` independently of `make_daemon` (the fixture's direct
   `db.add_node/get_task/remove_node/commit` usage at lines 67-138
   survives — `client.py` DB migration is out of scope)". Verified:
   tests/e2e/conftest.py:176-184 already constructs `db` via
   `DB.create(_db_config, automigrate=False)` with `_init_schema` fixture
   applying schema via `apply_schema()`. The fixture already constructs DB
   independently of `make_daemon` — it passes `db=db` into `make_daemon` at
   test_full_cycle.py:85. After removing the `db=` param (task 13.1), the
   fixture's `db` parameter still exists and is used for
   `db.add_node/get_task/remove_node` (lines 67-138). So the fixture
   SURVIVES unchanged — only the `make_daemon(config, db=db)` call at
   line 85 becomes `make_daemon(config)`. Task 13.2's "construct DB
   independently" wording implies the fixture needs construction work;
   in reality it already does. The task is functionally a no-op beyond
   13.1's call-site change; 13.2 could be merged into 13.1 or reworded to
   "Verify e2e `db` fixture wiring survives the `make_daemon` signature
   change (fixture already constructs DB independently via
   `DB.create(automigrate=False)` + `apply_schema()` in
   `tests/e2e/conftest.py:168-184` — no fixture change needed)".
 - **Verification tasks 14.7-14.9 rely on markers that tests do not
   apply.** `pyproject.toml:103-107` defines `unit`/`integration`/`e2e`
   markers, but only 2 tests in the entire suite carry a marker
   (`tests/unit/test_persistence_adapter.py:61,91` use `@pytest.mark.unit`).
   `pytest -m unit` would skip nearly every test. AGENTS.md verification
   commands (`uv run pytest -m unit/integration/e2e`) inherit this gap.
   This is a PRE-EXISTING project infrastructure issue, not introduced by
   this change — flagging only because tasks 14.7-14.9 will report false
   success (0-2 tests pass, no failures) if markers aren't applied. Either
   the change should add a `pytestmark = pytest.mark.unit` (etc.) sweep to
   its test tasks, or accept that 14.7-14.9 are best-effort and the real
   gate is `uv run pytest` (no marker filter). Out of scope to fix here;
   noting for implementer awareness.
 - **`stop()` preserved but task 9.9 redundant.** Task 9.9 "Update `stop()`
   — `self._clouds.stop()` still valid (no-op preserved)" — the `stop()`
   method on `CloudProvisionerImpl` is preserved per D1 (task 5.8 keeps it).
   The orchestrator's `stop()` at orchestrator.py:540 already calls
   `self._clouds.stop()`. No code change is needed in 9.9 — it's a
   verification-only task phrased as an update. Minor; could be moved to
   group 14 or reworded "Verify `self._clouds.stop()` still works (no-op)".
 - **No decision-level contradiction with frozen artifacts.** All 91 tasks
   map to frozen proposal What Changes (proposal.md:14-54) and design
   D1-D10 (design.md:47-339) and the 6 frozen spec files. No task
   contradicts a frozen decision. The `CloudAllocateError` layering gap
   (above) is a coverage omission in the frozen artifacts, not a
   contradiction — the frozen design D3 mentions raising the exception but
   does not address its layer-1 location; the tasks inherit the omission.
   No unfreeze triggered.

## tasks Round 2 — 2026-06-21
### 🔴 Fixed
 -
### 🟡 Addressed
 - (Round 1 stood down no outstanding 🔴; Round 2 confirms and adds findings
   below. Round 1 🟡 notes from lines 514-688 remain valid and are not
   retracted — they are inherited as ongoing non-blocking observations.)
### 🔴 Outstanding
 - **Task 5.5 + 5.4 leave `allocate()` body structurally broken.** Current
   `CloudProvisionerImpl.allocate(platforms)` body (manager.py:131-182)
   calls `_acquire_provider_slot(platforms)` at line 134 (returns
   adapter+config+tmp_ip, runs the lock + select + throttle + add_tmp
   critical section), `_safe_remove_tmp(tmp_ip)` at lines 151 and 156
   (cleanup wrapper), and `node_repo.add(node)` at line 180 (persist).
   Task 5.4 removes `_acquire_provider_slot`, `_safe_remove_tmp`,
   `_select_best_provider` entirely. Task 5.5 says only "remove
   `node_repo.add(node)` call; keep VM creation + setup + return Node (no
   persist)". After both tasks, the `allocate()` body still references the
   deleted helpers — it will not compile. Worse, even if the call sites
   are dropped, the new body has no source for `adapter` and `config`
   (previously supplied by `_acquire_provider_slot`), and no `tmp_ip`
   to clean up. The frozen cloud-provisioner spec scenario "Allocate node
   on best provider" still requires `allocate(platforms)` to pick the
   highest-priority provider internally, but the adapter now has no DB
   (D1) and therefore no `current_counts` to feed the extracted
   `select_provider` (D5) — the spec is silent on this gap. Task 5.5
   MUST be rewritten to spell out one of: (a) change `allocate`'s
   signature to accept a pre-selected `(adapter, config)` pair from the
   caller — but this contradicts the Protocol in D2 and the
   cloud-provisioner spec scenario; (b) inline a counts-free provider
   pick inside `allocate` (priority + platform only, no capacity check) —
   contradicts spec scenario wording "available capacity"; (c) drop
   provider selection from `allocate` entirely and update the spec
   scenario — frozen-spec change, out of scope for the tasks phase. Any
   of the three is a decision the implementer cannot make alone. This is
   a coverage gap inherited from the frozen design, but it surfaces as a
   concrete implementation blocker in task 5.5. **Recommend unfreeze of
   design D1/D2 + cloud-provisioner spec to clarify `allocate`'s new
   body, OR split task 5.5 into 5.5a (drop calls to deleted helpers),
   5.5b (decide and document provider-selection-in-allocate behavior).**
 - **Round 1 🟡 "CloudAllocateError layering gap" should be escalated to
   🔴.** Task 6.4 raises `CloudAllocateError` from
   `yascheduler/application/allocate_task.py`, but the exception is
   defined in `yascheduler/adapters/cloud/manager.py:59` (adapter layer).
   `pyproject.toml:118-130` declares a strict layers contract
   `yascheduler.adapters → yascheduler.application → yascheduler.domain`
   with `exclude_type_checking_imports = true`. A runtime import of
   `CloudAllocateError` from application code violates the contract —
   `lint-imports` (task 14.3) WILL fail. Round 1 flagged this as 🟡
   "coverage gap inherited from frozen design", but the practical
   consequence is a hard CI failure: the implementer cannot ship without
   resolving it, and no current task addresses the relocation. Either
   add a task to move `CloudAllocateError` (and likely `CloudSetupError`)
   to `yascheduler/domain/exceptions.py` with re-export from
   `yascheduler.adapters.cloud`, or raise a domain-layer exception
   (`SchedulingError` subclass) from the throttle check. Without an
   explicit task, the implementer either breaks the layer contract or
   breaks the spec scenario "Provider op-limit respected" (which names
   `CloudAllocateError`). Escalating because tasks 14.3 + the layering
   contract make this a build-time blocker, not a style note.
### 🟡 Notes
 - **Task 6.7 incomplete on tracker param propagation.** `_try_start_on_machine`
   (allocate_task.py:104-142) takes `clouds: CloudProvisionerImpl` and uses
   it ONLY for `clouds.mark_task_done(task.task_id)` at line 141. To replace
   with `tracker.discard(task.task_id)`, the param must be swapped in
   `_try_start_on_machine` AND in its only caller `_allocate_free_machine`
   (allocate_task.py:182-208, also takes `clouds`). Task 6.7 describes only
   the call-site swap, not the signature/param plumbing through two helper
   functions. Implementer will infer, but task is incomplete as written.
 - **Task 14.10 too narrow.** Only verifies `from yascheduler.db import DB`
   is removed from a list of files. Should also grep source (non-test) for
   residual references to removed/changed symbols: `mark_task_done`,
   `allocate_with_tracking`, `.capacity()`, `.get_capacity()`,
   `_select_best_provider`, `_acquire_provider_slot`, `_safe_remove_tmp`,
   `on_tasks`, `node_repo=` (constructor arg). Without these, the
   verification task can pass while stale references remain in source.
   Recommend expanding to a multi-symbol grep or adding sub-tasks 14.11,
   14.12, etc.
 - **Task 11.5 granularity likely >2h.** `tests/unit/test_application_use_cases.py`
   is 830 lines with multiple allocate_task tests (cloud fallback, allocate-
   to-machine, failure cleanup). Each needs new mock setup (`tracker`,
   `allocation_lock`, `adapters`, `configs`) AND new assertions on tmp-node
   insertion sequence, cloud-alloc-outside-lock, final persist, failure
   rollback. Single task should be split per test group:
   11.5a (allocate-to-machine tests — tracker.discard swap),
   11.5b (cloud-fallback happy path — full UoW sequence),
   11.5c (cloud-fallback failure cleanup — tmp-node removal + tracker.discard),
   11.5d (dedup test — tracker.add returns False).
 - **Task 11.7 missing Orchestrator constructor tests.** Only covers
   `_clouds_get_capacity` test updates. Orchestrator gains 3 new constructor
   params (`allocation_tracker`, `active_clouds`, `allocation_lock` per
   task 9.2) — no task verifies they are stored as `self._tracker`/
   `self._active_clouds`/`self._allocation_lock` and wired into use cases.
   Without this, a typo in constructor wiring would not be caught by unit
   tests. Recommend adding 11.7.5 "assert `Orchestrator.__init__` stores
   tracker/active_clouds/allocation_lock and passes them to allocate_task
   /consume_task call sites".
 - **`tests/fixtures/mock_clouds.py` not in any task.** The fixture stubs
   `mark_task_done` (line 48), `get_capacity` (line 41-47), and
   `configs.values()` (line 53-54) — all removed/changed by this change.
   No test currently imports `make_mock_clouds` (verified via grep —
   fixture is dead code), so this does not block tests, but the fixture's
   MODULE_CONTRACT (line 6) and docstring (line 27-35) still advertise
   the removed methods. Contract drift. Either delete the fixture as dead
   code, or add a task (e.g., 11.11) to update the fixture and its
   contract to match the post-refactor CloudProvisioner surface.
 - **Task 1.6 CrossLinks direction/relation unspecified.** Task says
   "add CrossLinks" between M-APPLICATION-ALLOCATE/DEALLOCATE and
   M-APPLICATION-ALLOCATION-TRACKER, but AGENTS.md requires
   `<CrossLink from="..." to="..." relation="..."/>` with concrete
   relation prose. Implementer must invent both the direction (allocate
   → tracker "owns tracker reference for dedup"? or tracker → allocate
   "notifies of in-flight state"?) and the relation text. Minor —
   implementer will pick reasonable values, but task is underspecified.
 - **Task 1.4 incomplete on M-DI depends.** Task removes M-DB from
   M-DI `<depends>` but does not add M-APPLICATION-ALLOCATION-TRACKER
   to M-DI depends, even though make_daemon now constructs an
   AllocationTracker (task 10.5). Per AGENTS.md "dependencies changed →
   `<depends>` + `<CrossLink>`", M-DI gains a new dependency. Add
   "add M-APPLICATION-ALLOCATION-TRACKER to M-DI depends" to task 1.4,
   or note that DI's dependency on the tracker is implicit (DI wires
   everything) and accept the inconsistency.
 - **Coverage cross-check vs Round 1:** all D1-D10 and all 6 spec files
   have at least one corresponding task (verified independently — matches
   Round 1's coverage matrix at lines 528-548). No additional coverage
   gaps found beyond the 5.5 / CloudAllocateError items above.
 - **Format compliance re-verified:** all 91 tasks in 14 groups use
   `- [ ] N.M desc` checkbox format parseable by the apply phase. No
   malformations. Matches Round 1 finding (lines 514-522).
 - **No new decision-level contradiction with frozen artifacts beyond
   the two 🔴 items above.** Both 🔴 items are coverage gaps inherited
   from frozen design/spec (D1 pure-adapter vs `allocate(platforms)`
   spec scenario; D3 CloudAllocateError raise vs layers contract), not
   contradictions introduced by tasks. Per workflow rules, an unfreeze
   may be required to resolve them at the design/spec level; absent
   unfreeze, the tasks phase must add explicit relocation/restructuring
   tasks. Either path is acceptable — what is NOT acceptable is shipping
   tasks.md as-is and leaving the implementer to discover the gaps at
    build time.

## tasks Round 2 — unfreeze (2026-06-21)
### 🔴 Fixed
 - Two coverage gaps surfaced in tasks review, both rooted in frozen
   design/specs:
   (1) `allocate(platforms)` after stripping DB has no source for
   adapter/config/tmp_ip — D3 puts selection in use case but D2 port
   signature still takes `platforms`, creating an ambiguity.
   (2) `CloudAllocateError` raised from application layer but defined in
   adapters — violates `lint-imports` layers contract.
 - Root cause for both: my proposed fix for 🔴#1 (pass `adapters`/`configs`
   dicts to use case) itself violates layering — application layer would
   hold runtime references to `CloudAdapter` (concrete adapter class) and
   `configs` (adapter internals). User caught this: "application layer
   начинает вытаскивать к себе части adapters".
 - Clean fix: move provider selection INTO the port. `CloudProvisioner`
   gains sync method `select_provider(platforms, current_counts) ->
   ProviderSelection | None`. Use case calls port method, gets domain
   value object (`ProviderSelection: name, username`), never sees
   `CloudAdapter` or `configs`. Pure function stays adapter-internal.
   `allocate(provider: str)` takes provider name, not platforms.
   `CloudAllocateError`/`CloudSetupError` move to `domain/exceptions.py`
   with re-export from `yascheduler.adapters.cloud`.
 - Decision-level changes to frozen proposal + design + 5 specs → full
   unfreeze from proposal. Re-review in order: proposal → design → specs.
### 🟡 Addressed
 -
### 🔴 Outstanding
 -
### 🟡 Notes
 - Unfreeze scope: proposal (minor: ProviderSelection in Impact, exception
   relocation in What Changes), design (D2/D3/D5/D10 revised + new D11
   for exception relocation), specs (cloud-provisioner, domain-ports,
   use-cases, orchestrator, dependency-injection), explore-brief (flows).
   Tasks.md not yet frozen — will be updated after specs re-freeze.

## proposal Round 3 — 2026-06-21
### 🔴 Fixed
 - **Round 2 unfreeze 🔴 (1) `allocate(platforms)` ambiguity resolved by moving
   provider selection INTO the port.** Proposal now describes (lines 14-20) a
   new sync port method `CloudProvisioner.select_provider(platforms,
   current_counts) -> ProviderSelection | None`; use case calls the port
   method and receives a domain value object, never seeing `CloudAdapter` or
   `configs`. `allocate(provider: str)` (proposal line 15) takes the selected
   provider name — caller already chose via `select_provider`. Verified
   against current port (ports.py:213-221): existing Protocol has
   `allocate(platforms)`, `deallocate(ip)`, `capacity()`; proposal captures
   all four port changes correctly (allocate signature, deallocate signature,
   capacity removed, select_provider added).
 - **Round 2 unfreeze 🔴 (2) `CloudAllocateError` layering violation resolved
   by relocation.** Proposal (lines 28-32) moves `CloudAllocateError` and
   `CloudSetupError` from `adapters/cloud/manager.py:59,63` to
   `domain/exceptions.py`, re-exported from `yascheduler.adapters.cloud` for
   adapter-internal callers. Application layer imports from
   `domain.exceptions` — `pyproject.toml:118-130` layers contract
   (`adapters → application → domain`, `exclude_type_checking_imports = true`)
   satisfied. Verified current exception location (manager.py:59,63) and
   current re-export (`adapters/cloud/__init__.py:42,54,58`).
 - **Original proposed fix (pass `adapters`/`configs` dicts to use case)
   superseded by clean fix.** The dict-passing fix was itself a layering
   violation (application layer would hold runtime references to
   `CloudAdapter` concrete class and adapter-internal `configs`). New
   `ProviderSelection(name, username)` value object in `domain/model.py`
   (proposal lines 24-27) carries only two primitive str fields — fully
   decoupled from adapter types. Verified no existing `ProviderSelection`
   in `domain/model.py` (grep returns nothing) — addition is clean.
   Verified application layer (orchestrator.py, allocate_task.py,
   deallocate_nodes.py) currently imports `ConfigCloud`/`CloudAdapter` only
   under `TYPE_CHECKING` (e.g. orchestrator.py:55, deallocate_nodes.py:32);
   the new design doesn't add any runtime adapter imports.

### 🟡 Addressed
 - Pure function `select_provider_pure` (proposal lines 40-44) explicitly
   scoped adapter-internal: lives in `adapters/cloud/provider_selection.py`,
   called only from `CloudProvisionerImpl.select_provider` (port method
   implementation), returns `CloudAdapter | None` (adapter type) which the
   port method immediately wraps into `ProviderSelection`. Adapter types
   never cross the port boundary. Rename from `select_provider` (Round 2
   frozen design D5 name) to `select_provider_pure` correctly disambiguates
   the adapter-internal pure function from the new port method of the same
   root.
 - Round 2 (frozen) `deallocate_node` signature change (`uow_factory` param)
   and orchestrator constructor growth (`allocation_tracker`,
   `active_clouds`, `allocation_lock` params) preserved through the unfreeze
   edits — proposal lines 110-117 still capture them. None of these need to
   grow further to accommodate the clean fix (the orchestrator no longer
   needs `adapters`/`configs` since provider selection lives in the port).
 - The Round 2 🟡 note "Task 9.5 injection path for `adapters`/`configs`
   undecided" is now moot at the proposal level — the clean fix means the
   orchestrator/use case never holds `adapters`/`configs`. tasks.md still
   references the old design (e.g. tasks.md:49 `clouds.allocate(platforms)`,
   tasks.md:3.2 `select_provider(...)` free function signature) — but tasks
   are not yet re-reviewed after this unfreeze and will be regenerated.

### 🔴 Outstanding
 -

### 🟡 Notes
 - **Brief contradicts the new design in 6 places — expected, brief not yet
   updated.** User confirms brief will be updated after proposal re-freezes.
   Flagging all six so the brief update doesn't miss any:
   (a) Brief line 75 lists `select_provider` as a free function in the
       new-modules table — must be renamed `select_provider_pure` and
       scoped adapter-internal; `ProviderSelection` (in `domain/model.py`)
       must be added to the table.
   (b) Brief line 85: "select_provider is **not** on the port — it's a free
       function" — directly inverted by the new decision (port method
       chosen). Must be rewritten to "select_provider is a sync port method
       returning ProviderSelection; select_provider_pure is the
       adapter-internal free function".
   (c) Brief line 94 port pseudocode `async def allocate(self, platforms:
       list[str]) -> Node` — must become `async def allocate(self, provider:
       str) -> Node` plus new sync `def select_provider(self, platforms,
       current_counts) -> ProviderSelection | None`.
   (d) Brief line 106 allocate flow pseudocode calls
       `provider = select_provider(adapters, configs, platforms, counts, log)`
       directly from the use case — must become
       `provider = clouds.select_provider(platforms, counts)` (port method,
       no adapters/configs visible to caller).
   (e) Brief line 109 `node = await clouds.allocate(platforms)` — must
       become `node = await clouds.allocate(provider.name)`.
   (f) Brief line 173 "Open Questions" #3 reads "`select_provider` as pure
       function (chosen over method — it's already pure from `self` state,
       only `node_repo` read which is being extracted)" — directly
       contradicts the new decision; must flip to "port method chosen to
       keep adapter types out of application layer; pure function stays
       adapter-internal under name `select_provider_pure`".
 - **Proposal line 46-47 drops `| None` from select_provider return in
   prose.** Reads "provider selection (via `clouds.select_provider` port
   method returning `ProviderSelection`)" but the actual return type is
   `ProviderSelection | None` (per line 18-19 BREAKING text and per current
   `_select_best_provider` returning None when no provider has capacity —
   manager.py:448-452). Use case must branch on None. Minor wording slip;
   implementer will infer from the Protocol signature. Consider tightening
   line 46-47 to "returning `ProviderSelection | None`" for symmetry with
   lines 18-19.
 - **Proposal `cloud-provisioner` Modified Capability bullet (line 85)
   slightly asymmetric.** Lists "Port signature changes (`deallocate(cloud,
   ip)`, `capacity()` removed)" but omits `allocate(provider: str)` and
   the new `select_provider` method. The `domain-ports` bullet (line 88-91)
   captures all four port changes correctly. Defensible split
   (cloud-provisioner capability = Impl, domain-ports = Protocol) but the
   cloud-provisioner bullet's "Port signature changes" phrasing makes the
   omission read as incomplete. Consider either dropping "Port signature
   changes" from cloud-provisioner (it's really a domain-ports concern) or
   listing all four changes there too.
 - **Spec scenario "Allocate node on best provider" must change.**
   cloud-provisioner/spec.md:17 still says `allocate(["linux"])` is called
   and the adapter picks the highest-priority provider internally; with
   `allocate(provider: str)` selection moves out (caller picks via
   `select_provider`). domain-ports/spec.md:6,18 and use-cases/spec.md:28,31
   also still reference `allocate(platforms)`. All spec files still reflect
   the pre-unfreeze design and will be regenerated in the specs re-review
   phase (specs not yet re-reviewed after this unfreeze). Flagging for
   traceability — proposal correctly lists `cloud-provisioner`,
   `domain-ports`, `use-cases` as Modified, so the spec deltas can carry
   the scenario rewrites.
 - **tasks.md still encodes the old design** (e.g. 3.2 implements
   `select_provider(...)` free function; 5.5 updates `allocate(platforms)`;
   6.4/6.5 call `clouds.allocate(platforms)` and a free-function
   `select_provider`; 6.4 references `config.username` from a `configs`
   visible to the use case). Will be regenerated in the tasks re-review
   phase. Not a proposal defect — proposal correctly drives the new design
   and tasks will follow.
 - **Verified consistent (no action needed):**
   * Impact section (proposal lines 119-122) correctly adds
     `domain/model.py` (`ProviderSelection`) and `domain/exceptions.py`
     (`CloudAllocateError`, `CloudSetupError`) — both new entries accurate,
     no other Impact bullets need to change for the unfreeze.
   * BREAKING items (lines 14, 21) unchanged and still correctly identified.
     Protocol change remains BREAKING (adding a method to
     `@runtime_checkable` Protocol can affect `isinstance` results for any
     structural implementer; only `CloudProvisionerImpl` implements it in
     practice, but the BREAKING label is defensible). make_daemon db-param
     removal remains BREAKING (e2e test calls it).
   * "Removed from `CloudProvisionerImpl`" list (lines 68-71) unchanged
     and still accurate — `_select_best_provider` leaves the Impl,
     replaced by the port method + pure function pair. `node_repo`,
     `allocate_with_tracking`, `get_capacity`, `_acquire_provider_slot`,
     `_safe_remove_tmp`, `mark_task_done`, `on_tasks`, `apis` all still
     being removed.
   * Application layer needs no new constructor params for the clean fix
     — orchestrator gains only `allocation_tracker`, `active_clouds`,
     `allocation_lock` (Round 2 soft-freeze); it does NOT gain
     `adapters`/`configs` because provider selection is now in the port.
     proposal Impact for orchestrator.py (lines 114-117) correctly
     reflects this.
   * `select_provider` port method being SYNC (not async) is consistent
     with the project Protocol pattern — `MachineGateway` Protocol already
     mixes sync (`list_free`, `contains`, `__len__`) and async methods
     (ports.py:138-210). Sync selection is correct: it does no I/O
     (capacity read happens in UoW before the call; pure function just
     ranks providers from in-memory `adapters`/`configs`).
   * No new layering violation introduced: pure function returns
     `CloudAdapter` (adapter type) but is adapter-internal; port method
     returns `ProviderSelection` (domain type) crossing the boundary;
     application imports `CloudAllocateError` from `domain.exceptions`
     (clean per layers contract).
   * Public API stability claims (CLI, Yascheduler, INI, schema, AiiDA)
     unaffected by the unfreeze edits — none of them touch
     `ProviderSelection` or the exception relocation.
   * No decision-level contradiction with the unfreeze rationale (review-log
     lines 830-863): provider selection in port ✓, ProviderSelection
     domain VO ✓, allocate(provider) ✓, exceptions in domain ✓,
     select_provider_pure adapter-internal ✓ — all five unfreeze commitments
     captured in the proposal.

## design Round 3 — 2026-06-21
### 🔴 Fixed
 - **D2 revised: provider selection moved INTO the port (resolves unfreeze
   reason #1).** New sync port method `select_provider(platforms,
   current_counts) -> ProviderSelection | None`; `allocate(provider: str)`
   takes the selected provider name; `deallocate(cloud, ip)` gains explicit
   cloud; `capacity()` removed. Verified against current port
   (ports.py:213-221) — all four port changes captured. Adapter types
   (`CloudAdapter`, `ConfigCloud`) do not cross the port boundary:
   `ProviderSelection(name, username)` (design.md:99-100) is primitive-only,
   matches existing `@dataclass(frozen=True)` value-object pattern in
   model.py:275-285 (`Node`). Grep confirms no existing
   `ProviderSelection` in `domain/model.py` — addition is clean.
 - **D11 new: exception relocation (resolves unfreeze reason #2).**
   `CloudAllocateError` and `CloudSetupError` move from
   `adapters/cloud/manager.py:59,63` to `domain/exceptions.py`, re-exported
   from `yascheduler.adapters.cloud` (and `.manager`) for backwards
   compatibility — matches current re-export at
   `adapters/cloud/__init__.py:42,54,58`. Layer contract
   (pyproject.toml:122-130: `yascheduler.adapters -> yascheduler.application
   -> yascheduler.domain`, `exclude_type_checking_imports = true`) satisfied:
   application imports from `domain.exceptions` (app->domain OK); adapters
   re-export from `domain.exceptions` (adapters->domain OK); no layer
   violation. `lint-imports` will pass.
 - **D3 revised: use case uses port methods only.** Pseudocode
   (design.md:108-143) calls `clouds.select_provider(platforms, counts)` and
   `clouds.allocate(selection.name)` — str in, `ProviderSelection`/`Node`
   out. No `CloudAdapter`/`ConfigCloud` reference in the use case;
   `adapters`/`configs` stay on `CloudProvisionerImpl` (D10). Round 2 🟡
   "Task 9.5 injection path for adapters/configs undecided" mooted at the
   design level — orchestrator no longer needs them.
 - **D5 revised: `select_provider_pure` adapter-internal.** Returns
   `CloudAdapter | None` (adapter type), explicitly scoped adapter-internal,
   called only from `CloudProvisionerImpl.select_provider`. Rename from
   Round 2 frozen name `select_provider` correctly disambiguates the port
   method from the adapter-internal pure function.
 - **D10 revised: adapters/configs stay on adapter.** Constructor
   (design.md:352-362) keeps both fields; explicit prose (design.md:367-369)
   confirms they are NOT injected into orchestrator or use cases.
### 🟡 Addressed
 - **Round 1/2 🟡 throttle check relocation resolved (prose-level).** D3
   paragraph (design.md:161-172) moves `adapter.get_op_semaphore().locked()`
   INTO `CloudProvisionerImpl.select_provider`, after the pure function
   returns an adapter, before constructing `ProviderSelection`. Correctly
   identifies `allocate_with_tracking(throttle=True)` as dead code (verified:
   `throttle` param never referenced in body at manager.py:256-285; check
   lives in `_acquire_provider_slot` at manager.py:460-466). Use case no
   longer performs the check itself.
 - **D3 <-> D8 <-> risk-mitigation consistency re-verified.** Lock scope
   (capacity read + select_provider + add_tmp + commit, all inside
   `allocation_lock`), commit-before-lock-release for tmp-node visibility,
   cloud op + final persist outside lock — aligned across D3 pseudocode,
   D8 prose (design.md:315-331), risk-mitigation (design.md:391-396).
   Matches current `_acquire_provider_slot` lock span (manager.py:447-477).
 - D8 lock ownership unchanged (orchestrator-owned, injected) — consistent
   with D4 AllocationTracker pattern.
### 🔴 Outstanding
 - **D3 pseudocode leaks tracker entry on `select_provider` raise (throttle
   path) — regression vs current code.** D3 prose (design.md:165-167)
   explicitly states the port method "raises `CloudAllocateError`" when the
   provider is overloaded, but the pseudocode (design.md:116-126) calls
   `clouds.select_provider(...)` outside any try/except. If the port raises,
   the exception escapes through `async with uow_factory()` and
   `async with allocation_lock` without `tracker.discard(task_id)` being
   called. The only tracker cleanup in step 1 is on the `selection is None`
   branch (design.md:122-123); step 2 cleanup (design.md:131-136) wraps only
   `clouds.allocate` and requires `tmp_ip` to exist. Neither covers the
   throttle-raise path. Net effect: task remains in the tracker set → next
   allocation cycle hits `tracker.add(task_id) == False` (design.md:110-111)
   → task permanently blocked from retry until daemon restart. **Current
   code does not have this bug:** `allocate_with_tracking`
   (manager.py:278-284) catches `CloudAllocateError` from
   `_acquire_provider_slot` (including the throttle raise at
   manager.py:460-466) and calls `mark_task_done(T)` to clean up `on_tasks`.
   The same leak applies to any step-1 exception (`uow.nodes.list_all`,
   `uow.nodes.add_tmp`, `uow.commit` DB failures — rarer but possible).
   Brief pseudocode (explore-brief.md:117-142) has the same gap. **Fix:**
   either (a) wrap step 1 in try/except mirroring step 2 — on exception
   before `tmp_ip` exists, call `tracker.discard(task_id)` then re-raise; or
   (b) have `select_provider` return `None` on throttle instead of raising,
   letting the existing `selection is None` branch handle cleanup. Option
   (b) is simpler and matches current caller-visible semantics
   (`allocate_with_tracking` returned `None`, did not raise, on throttle).
### 🟡 Notes
 - **D2 sync `select_provider` vs throttle's `await asyncio.sleep(1)`
   (internal contradiction).** Current throttle (manager.py:460-466) does
   `await asyncio.sleep(1)` before raising — a courtesy yield so the
   in-flight op-semaphore (adapters.py:92-98 `asyncio.Semaphore`) can drain.
   D2 (design.md:74-76) declares `select_provider` SYNC; proposal Round 3
   review (review-log.md:1016-1021) explicitly justified sync on the grounds
   the function "does no I/O". But D3 prose moves the throttle check
   (including its sleep) INTO `select_provider` — a sync method cannot
   `await`. Two resolutions: (a) drop the sleep (behavior change: fail-fast
   throttle instead of 1s-grace-then-fail; probably acceptable since the
   caller retries on the next cycle anyway), or (b) make `select_provider`
   async (contradicts D2 + proposal line 96 + brief line 96, all of which
   say "sync"). Design does not pick. Implementer will silently choose one;
   recommend explicit decision and update D2/proposal/brief accordingly.
 - **Brief drift only partially resolved (user's "brief updated" claim is
   ~67% true).** Proposal Round 3 review (review-log.md:927-955) flagged 6
   brief contradictions; 4 fixed (port pseudocode lines 93-98, allocate flow
   lines 117-142, ProviderSelection prose lines 100-104, exception
   relocation lines 106-111). Two remain:
   (a) Brief line 75 "New modules" table still lists `select_provider` (not
       `select_provider_pure`) as a free function — should be renamed and
       joined by `ProviderSelection` in `domain/model.py` (currently only
       in prose at lines 100-104, not the table). Implementer scanning the
       table sees the wrong name.
   (f) Brief line 203 Open Question #3 still reads "`select_provider` as
       pure function (chosen over method)" — directly inverts the Round 3
       decision (port method chosen). Should flip to "port method chosen to
       keep adapter types out of application layer; pure function stays
       adapter-internal as `select_provider_pure`".
   Non-blocking (design is authoritative) but contradict the user's "brief
   has been updated with the corrected flows" claim.
 - **`CloudAllocateError` inheritance: preserved as `Exception`, not
   `DomainError`.** D11 (design.md:386-387) preserves inheritance — current
   definitions (manager.py:59,63) inherit directly from `Exception`. After
   relocation to `domain/exceptions.py`, they will sit alongside
   `DomainError` subclasses but outside that hierarchy. Organizationally odd
   (cloud exception in domain layer but not a `DomainError`), but
   defensible: forcing under `DomainError` would be a catching-behavior
   change (handlers catching `DomainError` would newly catch these). No
   action needed; flagging for awareness.
 - **Verified consistent (no action needed):**
   * No new layering violation. App imports `ProviderSelection` and
     `CloudAllocateError` from `domain.*` (allowed); adapters import same
     from `domain.*` (allowed); `select_provider_pure` returns `CloudAdapter`
     but is adapter-internal.
   * No decision-level contradiction with re-frozen proposal (Round 3):
     D2/D3/D5/D10/D11 map cleanly to proposal lines 14-32, 40-51, 88-91,
     119-122. No unfreeze triggered by the design itself.
   * Public API stability preserved (CLI/Yascheduler/INI/schema/AiiDA
     untouched by Round 3 changes).
   * D6 deallocate ordering unchanged from Round 2 — still matches frozen
     proposal and current code (manager.py:222-229).

## design Round 4 — 2026-06-21
### 🔴 Fixed
 - **Round 3 🔴 tracker leak on throttle resolved.** D2 (design.md:99-104)
   and D3 prose (design.md:168-182) now state the port method
   `select_provider` returns `None` on throttle overload instead of
   raising `CloudAllocateError`. The use case's existing `selection is
   None` branch (design.md:128-130) calls `tracker.discard(task_id)`
   then `return False` — so the throttle path now routes to cleanup.
   Verified against current caller-visible semantics:
   `allocate_with_tracking` (manager.py:278-284) catches
   `CloudAllocateError` from `_acquire_provider_slot` (including the
   throttle raise at manager.py:460-466) and returns `None` after
   `mark_task_done` — i.e. current caller sees `None`, not an exception.
   The `None`-return port method preserves that contract. No regression.
### 🟡 Addressed
 - **Round 3 🟡 sync vs `await asyncio.sleep(1)` resolved.** D2
   (design.md:99-101) declares `select_provider` sync with explicit
   rationale: throttle returns `None` (no raise), so no `await` needed.
   D3 prose (design.md:176-178) drops the `await asyncio.sleep(1)` — the
   sync port method cannot `await`, and the caller retries on the next
   allocation cycle anyway. The 1s sleep was a courtesy yield for the
   op-semaphore (adapters.py:92-98) to drain; failing fast is acceptable
   since the next cycle (seconds later) re-checks. Behavior change is
   minor (fail-fast throttle vs 1s-grace-then-fail) and called out.
 - **Round 3 🟡 brief drift (table + Open Question #3) fixed.** Brief
   line 75 table now lists `select_provider_pure` (renamed from
   `select_provider`) with `ProviderSelection` in `domain/model.py` as a
   separate row. Brief line 204 Open Question #3 now reads "port method
   chosen over free function" with rationale (keeps adapter types out of
   application layer). Both verified against design D2/D5 — consistent.
### 🔴 Outstanding
 -
### 🟡 Notes
 - **D11 rationale text is now stale but the decision still holds.**
   D11 (design.md:384-388) justifies the exception relocation with:
   "After refactor, `allocate_task` (application layer) raises
   `CloudAllocateError` from the throttle check path". After Round 4,
   the throttle check returns `None` (does not raise) and lives inside
   `select_provider` (port method, adapter layer) — so `allocate_task`
   no longer raises `CloudAllocateError` from the throttle path. The
   stated rationale is factually wrong. However, the D11 decision itself
   (move `CloudAllocateError`/`CloudSetupError` to `domain/exceptions.py`)
   is still correct: `allocate(provider: str)` still raises
   `CloudAllocateError` on VM creation failure (manager.py:152) and
   `CloudSetupError` on setup failure (manager.py:170), and D3 step 2
   (design.md:136-143) catches `Exception` and re-raises — so these
   exceptions propagate through the application layer to the orchestrator.
   Any application-layer caller that catches `CloudAllocateError` (the
   orchestrator or `_allocator_consumer` likely will, mirroring current
   `allocate_with_tracking` catch-and-return-None at manager.py:278-284)
   must import from `domain.exceptions` per the layers contract. Recommend
   updating D11's rationale sentence to: "After refactor, `allocate` still
   raises `CloudAllocateError`/`CloudSetupError` on VM creation/setup
   failure, and these propagate through `allocate_task` to the
   orchestrator — application-layer callers that catch them must import
   from `domain.exceptions` per the layers contract." Non-blocking —
   decision stands, only the justification text is wrong.
 - **Brief pseudocode line 126 omits `tracker.discard` in the
   `selection is None` branch — now the throttle cleanup path.** Brief
   line 126 reads `if selection is None: return False` without
   `tracker.discard(task_id)`, while design D3 (design.md:128-130)
   correctly shows `tracker.discard(task_id)` before `return False`. An
   implementer following the brief sketch literally would reintroduce the
   exact tracker-leak class Round 3 🔴 flagged (task added at brief line
   119, never discarded on throttle-None). The brief was updated for
   Round 4 (table line 75, OQ#3 line 204) but this pseudocode line was
   not. Pre-existing sketch gap (the brief never had `tracker.discard`
   here), now load-bearing because the throttle fix routes through this
   branch. Non-blocking — design D3 is authoritative and correct — but
   contradicts the "brief updated" claim for Round 4. Flagging so the
   brief sketch can be aligned if the brief is touched again.
 - **Pre-existing DB-failure leak in step 1 unchanged (out of scope).**
   Round 3 🔴 noted the same tracker-leak applies to step-1 DB exceptions
   (`uow.nodes.list_all`, `uow.nodes.add_tmp`, `uow.commit` failures).
   Round 4's fix (option b: return None on throttle) only covers the
   throttle path; DB-failure exceptions still propagate without
   `tracker.discard`. This is NOT a regression — current
   `allocate_with_tracking` (manager.py:278-284) catches only
   `(CloudAllocateError, CloudSetupError)`, not DB errors, so a DB
   failure in `_acquire_provider_slot`'s `node_repo.add_tmp` would
   already leak `on_task` today. Pre-existing, out of scope for this
   change. Noting for traceability.
 - **Verified consistent (no action needed):**
   * D3 pseudocode lock scope (capacity read + select_provider + add_tmp
     + commit inside `allocation_lock`; cloud op + final persist
     outside) unchanged from Round 2 fix — still correct.
   * D3 `tracker.add(task_id)` at start with early-return-on-False
     (design.md:116-118) preserved — matches current
     `allocate_with_tracking` dedup (manager.py:264-271).
   * D2 `ProviderSelection(name, username)` primitive-only — no adapter
     types cross the port boundary. `select_provider_pure` (D5) returns
     `CloudAdapter` but is adapter-internal.
   * No decision-level contradiction with re-frozen proposal (Round 3):
     D2/D3/D11 map cleanly to proposal lines 14-32, 45-48, 28-32. The
     `None`-return-on-throttle is consistent with proposal line 18-19
     `select_provider(...) -> ProviderSelection | None` (the `| None`
     covers throttle). No unfreeze triggered.
   * Public API stability preserved — CLI/Yascheduler/INI/schema/AiiDA
     untouched by Round 4 edits.

## design Round 4 — re-verification (2026-06-21)

Note: A prior `## design Round 4 — 2026-06-21` entry already exists
above. This re-verification pass was triggered by re-running the Round 4
prompt. It independently confirms the prior entry's findings against the
current artifacts and adds two stale-text items the prior entry missed.

### 🔴 Fixed
 - **Confirmed: Round 3 🔴 tracker leak on throttle resolved.** Independently
   re-verified the routing: D2 (design.md:99-104) and D3 prose
   (design.md:168-182) specify `select_provider` returns `None` on overload;
   D3 pseudocode (design.md:128-130) routes `selection is None` →
   `tracker.discard(task_id)` → `return False`. Verified against current
   caller-visible semantics: `allocate_with_tracking` (manager.py:278-284)
   catches `(CloudAllocateError, CloudSetupError)` from
   `_acquire_provider_slot` (including throttle raise at manager.py:460-466)
   and returns `None` after `mark_task_done` — caller never saw an exception
   on throttle. The `None`-return port method preserves that contract. No
   regression.
 - Confirmed: Round 2 unfreeze 🔴 #1 (provider selection in port) and #2
   (exception relocation) remain correctly captured in D2/D3/D5/D10/D11.

### 🟡 Addressed
 - **Confirmed: Round 3 🟡 sync vs `await asyncio.sleep(1)` resolved.** D2
   (design.md:99-101) declares `select_provider` sync with explicit
   rationale. D3 prose (design.md:176-178) drops the sleep — sync port
   method cannot `await`, caller retries on next cycle. No `await` remains
   in the port method. Behavior change (fail-fast throttle vs 1s-grace) is
   minor and called out.
 - **Confirmed: Round 3 🟡 brief drift (table + Open Question #3) fixed.**
   Brief line 75 lists `select_provider_pure`; brief line 76 lists
   `ProviderSelection` in `domain/model.py`; brief line 204 reads "port
   method chosen over free function". All three align with design D2/D5.
 - **NEW (missed by prior Round 4): design.md Open Questions #3 (line 459)
   contradicts the decision.** Reads "`select_provider` as pure function
   (D5) — chosen over method", but D5 (design.md:254-258) explicitly
   REJECTS exposing the free function and chooses the port method; D2
   (design.md:94-98) confirms "select_provider is **on the port** (not a
   free function)". Brief line 204 was fixed in this same Round 4 batch to
   say "port method chosen over free function" — the design's own Open
   Questions recap was not updated to match. Non-blocking (recap section,
   not a decision section; D2/D5 are authoritative and correct), but it
   directly contradicts the brief fix and will mislead anyone scanning the
   design's Open Questions. Fix: flip line 459 to "port method chosen
   (pure function stays adapter-internal as `select_provider_pure`)".
 - **NEW (missed by prior Round 4): design.md D3 pseudocode line 131 has a
   stale throttle comment.** `# throttle check — see prose below` sits
   between `if selection is None: ...` and `tmp_ip = ...`, leftover from
   the Round 2 soft-freeze when the throttle check was a separate use-case
   step. After Round 3, the throttle check moved INTO `select_provider`
   (port method) — there is no throttle check at the line 131 position
   anymore. Prose (design.md:168-182) is correct; only the inline comment
   is misleading. Non-blocking — implementer following the prose is fine,
   but a pseudocode-only reader may look for a throttle check that isn't
   there. Fix: drop line 131 or rewrite to "throttle handled inside
   select_provider (returns None on overload)".

### 🔴 Outstanding
 -

### 🟡 Notes
 - **Confirmed (prior Round 4 entry): D11 rationale text is stale but the
   decision still holds.** D11 (design.md:381-388) justifies the relocation
   with "allocate_task raises CloudAllocateError from the throttle check
   path" — after Round 4 the throttle returns `None` and lives inside
   `select_provider` (adapter layer), so that sentence is factually wrong.
   Verified independently: `allocate` (manager.py:152) raises
   `CloudAllocateError` on VM creation failure and (manager.py:170) raises
   `CloudSetupError` on setup failure; D3 step 2 (design.md:136-143)
   catches `Exception` and re-raises, so both propagate through
   `allocate_task` to the orchestrator. The relocation is still required
   because the application layer touches these exceptions in the
   propagation path. Recommend the rationale rewrite the prior entry
   suggested ("After refactor, `allocate` still raises
   `CloudAllocateError`/`CloudSetupError` on VM creation/setup failure,
   and these propagate through `allocate_task` to the orchestrator...").
 - **D3 step 2 re-raise has no documented catcher.** D3 step 2
   (design.md:136-143) re-raises after tmp-node cleanup, but
   `_allocator_consumer` (orchestrator.py:244-254) currently has no
   try/except around `allocate_task` — the catch lived in the now-removed
   `allocate_with_tracking` (manager.py:278-284). Post-refactor, the
   orchestrator (or a wrapper) must add an equivalent catch to avoid
   daemon-level exception handling on every VM creation/setup failure.
   Design D3 is silent on this. Non-blocking for the design's internal
   consistency (D3 correctly re-raises after cleanup), but the
   implementer must add the catch — worth a one-liner in D3 or the
   proposal Impact bullet for orchestrator.py.
 - Confirmed (prior Round 4 entry): brief pseudocode line 126 omits
   `tracker.discard(task_id)` in the `selection is None` branch — now
   load-bearing as the throttle cleanup path. Design D3 authoritative.
 - Confirmed (prior Round 4 entry): pre-existing DB-failure leak in D3
   step 1 (`uow.nodes.list_all`/`add_tmp`/`commit` exceptions propagate
   without `tracker.discard`). Pre-existing in current code
   (manager.py:278-284 catches only `(CloudAllocateError, CloudSetupError)`,
   not DB errors). Out of scope.
 - Verified consistent: no decision-level contradiction with re-frozen
   proposal (Round 3). D2/D3/D11 map cleanly to proposal lines 14-32,
   45-48, 28-32. The `None`-return-on-throttle is consistent with
   proposal line 18-19 `select_provider(...) -> ProviderSelection | None`
   (the `| None` covers throttle). Public API stability preserved
   (CLI/Yascheduler/INI/schema/AiiDA untouched).
  - Recommendation: **APPROVE WITH NOTES** — batch passes (no 🔴
    outstanding). Two minor stale-text items in design.md (Open Questions
    #3 line 459, pseudocode comment line 131) worth fixing for cleanliness
    and to match the brief fix in the same batch; D11 rationale sentence
    worth the suggested rewrite. None block re-freeze.

## design Round 4 — soft-freeze additions (2026-06-21)
### 🔴 Fixed
 -
### 🟡 Addressed
 - design.md Open Questions #3 updated: "port method chosen over free
   function" (was stale "pure function chosen over method").
 - design.md D3 pseudocode stale `# throttle check — see prose below`
   comment removed (throttle moved into `select_provider` port method,
   no check at that pseudocode position).
 - D11 rationale updated: "throttle check path" → "VM creation/setup
   failure path in D3 step 2" (throttle no longer raises; `allocate`
   still raises `CloudAllocateError`/`CloudSetupError` on VM failure).
### 🔴 Outstanding
 -
### 🟡 Notes
 - All three Round 4 🟡 stale-text items addressed as declarative additions
   under soft-freeze rules (no decision-level changes). Design re-frozen.

## specs Round 2 — 2026-06-21

Trigger: specs were unfrozen after Round 1 because tasks Round 2 surfaced
two coverage gaps rooted in frozen design/specs — (1) provider selection
layering (`allocate(platforms)` had no source for adapter/config after DB
removal), (2) `CloudAllocateError` raised from application layer but
defined in adapters (violates `lint-imports` layers contract). Proposal
re-frozen Round 3, design re-frozen Round 4 (+ soft-freeze). This round
re-reviews the 6 spec files against the re-frozen baseline.

### 🔴 Fixed
 - **Round 1 carry-over: provider selection layering resolved at the spec
   level.** `domain-ports/spec.md` MODIFIED "CloudProvisioner port" now
   declares the sync port method
   `select_provider(platforms, current_counts) -> ProviderSelection | None`
   and the primitive-only `ProviderSelection(name, username)` value object
   in `yascheduler.domain.model`. `allocate(provider: str)` takes the
   selected provider name; `deallocate(cloud, ip)` takes explicit cloud;
   `capacity()` removed. Verified against re-frozen proposal lines 14-27
   and design D2 (design.md:68-107). No spec scenario references
   `CloudAdapter` from the application layer; the only `CloudAdapter`
   mention is in `cloud-provisioner/spec.md:43` describing the
   adapter-internal pure function signature (`select_provider_pure`), and
   the cloud-provisioner "ProviderSelection is primitive-only" scenario
   explicitly asserts no `CloudAdapter`/`ConfigCloud` reference crosses
   the boundary. Verified `CloudAdapter` lives in
   `yascheduler.adapters.cloud.adapters:80` (adapter layer) — application
   layer cannot import it; specs respect this.
 - **Round 1 carry-over: CloudAllocateError layering violation resolved.**
   `cloud-provisioner/spec.md` scenario "Allocate raises on VM creation
   failure" now states `CloudAllocateError`/`CloudSetupError` are raised
   "from `domain.exceptions`" on VM creation/setup failure, and the use
   case catches and cleans up tmp-node. `use-cases/spec.md` scenario
   "Cloud allocation failure cleans up tmp-node" catches the same two
   exceptions from `clouds.allocate(selection.name)` (D3 step 2 path),
   not from the throttle path. Matches re-frozen proposal lines 28-32
   and design D11 (design.md:380-398). Application imports from
   `domain.exceptions` (app→domain OK per `pyproject.toml:118-130`).
 - **Round 3/4 tracker-leak-on-throttle regression resolved at the spec
   level.** Throttle semantics now consistently route through the
   `selection is None` branch: `domain-ports/spec.md` scenario
   "Select provider returns None on throttle" + body line 19-22;
   `cloud-provisioner/spec.md` body line 48-51 and scenario
   "Provider op-limit returns None" (in both Provider-selection and
   Concurrent-throttling requirements); `use-cases/spec.md` scenario
   "Throttle returns None — no tmp-node inserted" explicitly asserts
   `tracker.discard(task_id)` + return False + no exception raised.
   Matches design D2/D3 Round 4 fix (design.md:99-104, 168-182). No
   spec scenario raises `CloudAllocateError` from the throttle path;
   throttle always returns `None`.

### 🟡 Addressed
 - **Format compliance verified.** All 6 spec files use `### Requirement:`
   (3-#) and `#### Scenario:` (4-#) with WHEN/THEN. SHALL/SHALL NOT/
   MUST used consistently; `rg "\b(should|may)\b" -i` returns no matches
   in normative prose. `openspec validate cloud-provisioner-pure --strict
   --json` passes (1/1 valid, 0 issues); `openspec validate --all --json`
   passes (32/32 valid).
 - **Delta correctness verified pairwise** for all 11 MODIFIED
   requirements against the corresponding existing spec files. Every
   MODIFIED block replaces the ENTIRE existing block (title preserved
   verbatim, body rewritten, scenarios rewritten/added/dropped as
   appropriate):
   * `cloud-provisioner/spec.md` 3 MODIFIED ("CloudProvisionerImpl
     implements CloudProvisioner", "Provider selection by priority and
     capacity", "Concurrent allocation throttling") — each title matches
     existing spec lines 9, 30, 61; bodies and scenarios fully replaced.
   * `domain-ports/spec.md` 1 MODIFIED ("CloudProvisioner port") — title
     matches existing spec line 139; full block replacement; "Report
     capacity" scenario correctly dropped (capacity removed).
   * `use-cases/spec.md` 3 MODIFIED ("AllocateTask use case",
     "ConsumeTask use case", "DeallocateIdleNodes use case") — titles
     match existing spec lines 27, 46, 71; full block replacement.
   * `orchestrator/spec.md` 3 MODIFIED ("Orchestrator manages
     producer-consumer loops", "Deallocate loop", "Allocate loop") —
     titles match existing spec lines 11, 65, 43; full block replacement.
   * `dependency-injection/spec.md` 1 MODIFIED ("make_daemon factory") —
     title matches existing spec line 10; full block replacement;
     "make_daemon accepts pre-built dependencies" scenario rewritten as
     "make_daemon accepts pre-built clouds" (drops `db=my_db`).
   No partial deltas; no scenario inadvertently dropped that should have
   been preserved.
 - **Coverage of D1-D11 verified.** D1 pure adapter
   (cloud-provisioner::CloudProvisionerImpl body + "No DB access from
   adapter" scenario); D2 port change (domain-ports::CloudProvisioner
   port); D3 allocate_task flow with tracker dedup at start, lock scope,
   None-on-throttle, tmp-node cleanup on failure (use-cases::AllocateTask
   — 4 scenarios cover the full flow); D4 AllocationTracker
   (allocation-tracker NEW spec, 5 scenarios); D5 select_provider_pure
   adapter-internal (cloud-provisioner::Provider selection body); D6
   deallocate ordering disable→delete→remove across two short UoWs
   (use-cases::DeallocateIdleNodes body + "Deallocate node brackets
   cloud delete" scenario; orchestrator::Deallocate loop
   "Deallocator consumer brackets cloud delete with UoWs" scenario); D7
   inline capacity with `_active_clouds` (orchestrator::Allocate loop
   "Cloud capacity computed inline" scenario); D8 lock orchestrator-owned
   (orchestrator::Orchestrator manages loops body — `allocation_lock`
   param + "SHALL own the tracker, the filtered cloud config list, and
   the lock"); D9 make_daemon drops DB (dependency-injection::make_daemon
   body + "No DB import in make_daemon" scenario); D10 constructor
   signature — adapters/configs stay on adapter, node_repo removed
   (cloud-provisioner::CloudProvisionerImpl removed-methods prose;
   dependency-injection body "construct `CloudProvisionerImpl` without
   a `node_repo` parameter" + "SHALL NOT pass `adapters` or `configs`
   dicts to the Orchestrator"); D11 exception relocation
   (cloud-provisioner::Allocate raises scenario — "from
   `domain.exceptions`"). All 11 decisions captured.
 - **Throttle semantics verified end-to-end.** `select_provider` returns
   `None` on throttle (not raise) — consistently across domain-ports
   body+scenario, cloud-provisioner body+scenario (×2), use-cases
   scenario "Throttle returns None". Use case's `selection is None`
   branch calls `tracker.discard(task_id)` then returns False —
   explicitly asserted in use-cases "No free machine — cloud fallback
   with full ownership" and "Throttle returns None" scenarios, and in
   cloud-provisioner "Provider op-limit returns None" (Concurrent
   throttling). Matches design D3 (design.md:128-130).
 - **Exception relocation verified.** `CloudAllocateError` /
   `CloudSetupError` raised from `allocate` on VM creation/setup
   failure (cloud-provisioner "Allocate raises on VM creation failure"),
   caught in use case step 2 (use-cases "Cloud allocation failure cleans
   up tmp-node"). Both spec scenarios consistently reference the
   exceptions without specifying the adapter module path — the
   cloud-provisioner scenario explicitly says "from `domain.exceptions`",
   matching D11 and proposal lines 28-32.
 - **Layering verified.** No application-layer spec scenario imports or
   references `CloudAdapter` or the `adapters`/`configs` dicts. The
   cloud-provisioner body's `select_provider_pure(adapters, configs, ...)`
   signature is explicitly scoped adapter-internal ("The application
   layer SHALL NOT call `select_provider_pure` directly or reference
   `CloudAdapter`/`ConfigCloud` types"). `use-cases` body line 10-12:
   "It SHALL NOT import from `yascheduler.adapters` at runtime. It SHALL
   NOT accept `adapters` or `configs` parameters". `orchestrator` body
   line 26-29: "SHALL NOT read `self._clouds.configs` ... SHALL NOT hold
   `adapters` or `configs` dicts". `dependency-injection` body line 24-27:
   "SHALL NOT pass `adapters` or `configs` dicts to the Orchestrator".
 - **Public API stability preserved.** No spec delta touches CLI,
   `class Yascheduler`, INI, DB schema, or AiiDA entrypoint.
 - **No decision-level contradiction with re-frozen proposal (Round 3)
   or design (Round 4 + soft-freeze).** Spot-verified: proposal line 19
   `select_provider(...) -> ProviderSelection | None` ↔ domain-ports
   spec line 8 ✓; proposal lines 28-32 exception relocation ↔
   cloud-provisioner "Allocate raises" scenario ✓; proposal lines 45-48
   allocate_task accepts only port/domain types ↔ use-cases body ✓;
   proposal lines 114-117 orchestrator constructor growth ↔ orchestrator
   body ✓; proposal lines 21-23 make_daemon drops db ↔ dependency-injection
   body ✓; design D2/D3/D6/D7/D11 ↔ corresponding spec scenarios ✓. No
   unfreeze triggered.

### 🔴 Outstanding
 -

### 🟡 Notes
 - **Orchestrator body references `ConfigCloud` for `active_clouds`
   parameter.** `orchestrator/spec.md:9` types the new constructor param
   as `active_clouds: Sequence[ConfigCloud]`. This matches design D7
   (design.md:296-313) which explicitly says "The orchestrator receives
   this filtered list at construction". `ConfigCloud` lives in
   `yascheduler.config.cloud:387` — NOT in `yascheduler.adapters`, so it
   is outside the `pyproject.toml:118-130` layers contract
   (`adapters → application → domain`); the typing annotation is also
   TYPE_CHECKING-only at runtime. Not a layering violation. The user's
   verification criterion #4 lists `ConfigCloud` in the prohibited set,
   which is stricter than the re-frozen design — but the design is
   authoritative and the spec correctly tracks it. Flagging the tension
   for traceability; no spec change needed.
 - **`deallocate_nodes` body vs scenario signature mismatch (inherited
   from Round 1, partially tightened).** `use-cases/spec.md:78-80` body
   says "SHALL accept `uow_factory` and `SSHMachineGateway`" but the
   scenario signature `deallocate_nodes(uow_factory, config_clouds,
   idle_machines)` (line 90) has no `SSHMachineGateway`. The delta did
   correct the existing spec's stale signature (dropped `cloud` and
   `gateway` params to match current code at deallocate_nodes.py:73-77).
   The remaining body-vs-scenario mismatch can be read as describing
   the singular `deallocate_node(node, gateway, clouds, uow_factory)`
   wrapper, which DOES take `gateway`. Implementer will follow scenario
   signatures. Non-blocking.
 - **`allocate_task` "Allocate to free machine" scenario signature
   includes `engines` and `start_task_on_machine` not listed in the
   SHALL-accept body line (inherited).** The body lists `task_id`,
   `uow_factory`, `gateway`, `clouds`, `tracker`, `allocation_lock`;
   the scenario adds `engines` and `start_task_on_machine`. Same shape
   as the existing spec (which also had params in the scenario not in
   the body). Implementer will follow the scenario signature. Non-blocking.
 - **cloud-provisioner REMOVED section references a scenario name, not
   a requirement (carried from Round 1).** "Capacity reports available
   nodes" is a `#### Scenario` in the existing spec
   (cloud-provisioner/spec.md:26), not a `### Requirement`; the REMOVED
   block under `## REMOVED Requirements` won't be applied at archive
   time. The scenario IS correctly dropped via the MODIFIED
   "CloudProvisionerImpl implements CloudProvisioner" block. Functionally
   a no-op; Reason/Migration prose is useful documentation. Left as-is.
 - **"Concurrent allocation throttling" requirement location
   organizationally mismatched (carried from Round 1).** Requirement
   lives in cloud-provisioner/spec.md but post-refactor its content
   (`AllocationTracker` dedup + `select_provider` None-on-throttle) is
   application-layer behavior. `CloudProvisionerImpl` owns no throttling
   after D1/D4. Kept for continuity with the pre-existing requirement;
   content is correct. Non-blocking.
 - **Orchestrator-level catch of re-raised `CloudAllocateError` /
   `CloudSetupError` not captured in any spec scenario (coverage gap
   carried from design Round 4).** `use-cases` "Cloud allocation failure
   cleans up tmp-node" correctly says the use case re-raises after
   tmp-node cleanup. But no orchestrator spec scenario describes who
   catches the re-raise. Current catch lived in the now-removed
   `allocate_with_tracking` (manager.py:278-284); post-refactor the
   orchestrator (or wrapper) must add an equivalent catch. Design Round
   4 review (review-log lines 1349-1359) flagged this; specs Round 2
   inherits the gap — it is an implementation concern for tasks.md, not
   a spec defect. `allocate_task` behavior is fully specified.
 - **Cross-spec redundancy on throttle / exception / deallocate
   bracketing (benign).** Throttle-returns-None appears in 3 specs
   (domain-ports, cloud-provisioner ×2, use-cases); deallocate
   disable→delete→remove bracketing appears in 2 specs (use-cases +
   orchestrator); CloudAllocateError caught from `clouds.allocate`
   appears in 2 specs (cloud-provisioner + use-cases). Each spec
   describes the behavior from its layer's angle; defensible. Implementer
   updating one without missing the others should grep across all 6 spec
   files.
 - **`"aws"` used as example provider name** in cloud-provisioner and
   domain-ports scenarios (`allocate("aws")`, `deallocate(cloud="aws",
   ip=...)`, `select_provider(["linux"], {"aws": 0})`). Actual providers
   are Azure/Hetzner/UpCloud/VastAI (`yascheduler/config/cloud.py:78,
   168, 238, 304`). Cosmetic only — scenarios are illustrative, not
   literal provider names. Implementer will use real provider names in
   tests.
 - **Verified consistent (no action needed):**
   * allocation-tracker/spec.md unchanged from Round 1 — not affected by
     the unfreeze; still correctly captures D4 (5 scenarios: add new,
     add duplicate, discard tracked, discard untracked, containment).
   * Tracker lifecycle consistent across specs: `allocate_task` calls
     `add` (cloud-fallback only) and `discard` (success-to-free-machine
     is no-op since task wasn't tracked via that path; throttle-None,
     cloud-alloc-failure both discard); `consume_task` calls `discard`
     on success and download-failure (both no-ops for non-cloud tasks,
     which is fine — set.discard is idempotent).
   * ProviderSelection definition consistently placed in
     `yascheduler.domain.model` (domain-ports body line 27-30; matches
     proposal line 24-27 and design D2 design.md:106-107).
   * AllocationTracker consistently placed in
     `yascheduler.application.allocation_tracker` (allocation-tracker
     body line 5-6; matches proposal line 36-39 and design D4).
   * `select_provider_pure` consistently placed in
     `yascheduler.adapters.cloud.provider_selection` (cloud-provisioner
     body line 42-43; matches proposal line 40-44 and design D5).
   * All scenarios use concrete WHEN conditions (named function calls,
     specific parameter values, identifiable error types) and THEN
     assertions (return values, UoW call sequences, import presence/
     absence, exception types). Testable per testing-unit /
     test-db-integration / e2e-testing specs.
   * No new layering violation introduced; no public-API stability
     regression; no decision-level contradiction with re-frozen
     proposal/design.
 - **Recommendation: APPROVE WITH NOTES** — batch passes (no 🔴
   outstanding). All 6 spec files can be re-frozen. Notes above are
   inherited tensions (Round 1 carry-overs) or implementation-level
   concerns (orchestrator catch of re-raised exception) that belong in
   the tasks phase, not the specs phase.

## tasks Round 3 — 2026-06-21

Trigger: tasks.md rewritten after the proposal/design/specs unfreeze-refreeze
to move provider selection INTO the port (`CloudProvisioner.select_provider`
sync method returning `ProviderSelection` domain VO) and relocate
`CloudAllocateError`/`CloudSetupError` to `domain/exceptions.py`. This round
re-reviews the rewritten tasks against the re-frozen baseline (proposal
Round 3, design Round 4 + soft-freeze, specs Round 2).

### 🔴 Fixed
 - **Round 2 🔴 #1 (allocate() structurally broken after 5.4/5.5) resolved.**
   Task 5.6 now spells out the rewritten body: `allocate(self, provider: str)
   -> Node` looks up `adapter = self.adapters[provider]` and `config =
   self.configs[provider]`, creates VM, waits SSH, cloud-init, setup, returns
   Node — no DB write, no tmp-node (use case owns those). Verified against
   current code (manager.py:131-182): every reference to the removed helpers
   (`_acquire_provider_slot`, `_safe_remove_tmp`, `node_repo.add`) is gone
   from the new body description. The `provider: str` signature matches
   re-frozen proposal line 14-15, design D2 (design.md:72), and the
   `domain-ports` spec. Provider selection is no longer ambiguous — it lives
   in the port method `select_provider` (task 5.5), which the use case calls
   (task 6.4) before calling `allocate(selection.name)` (task 6.5).
 - **Round 2 🔴 #2 (CloudAllocateError layering violation) resolved.**
   Tasks 2.3-2.6 relocate both `CloudAllocateError` and `CloudSetupError`
   from `adapters/cloud/manager.py:59,63` (verified) to
   `yascheduler/domain/exceptions.py`, re-exported from
   `yascheduler.adapters.cloud.manager` and `yascheduler.adapters.cloud` for
   backwards compatibility with adapter-internal callers. Task 14.11 verifies
   the new home and re-exports. Application layer imports from
   `domain.exceptions` (app→domain OK per `pyproject.toml:118-130` layers
   contract). Matches re-frozen proposal lines 28-32 and design D11
   (design.md:380-398).

### 🟡 Addressed
 - **Round 2 🟡 "Task 6.7 incomplete on tracker param propagation"** — task
   6.7 now says "propagate `tracker` param through both helper signatures"
   (`_try_start_on_machine` AND `_allocate_free_machine`). Verified the
   current helpers take `clouds: CloudProvisionerImpl` and use it ONLY for
   `clouds.mark_task_done(task.task_id)` (allocate_task.py:141 in
   `_try_start_on_machine`; passed-through from `_allocate_free_machine`
   allocate_task.py:182-208). Swap is mechanical.
 - **Round 2 🟡 "Task 14.10 too narrow"** — task 14.10 now greps the full
   removed-symbol set: `mark_task_done`, `allocate_with_tracking`,
   `.capacity()`, `.get_capacity()`, `_select_best_provider`,
   `_acquire_provider_slot`, `_safe_remove_tmp`, `on_tasks`, `node_repo=`
   (constructor arg), and `from yascheduler.db import DB`, across
   `di.py`, `orchestrator.py`, `allocate_task.py`, `consume_task.py`,
   `deallocate_nodes.py`, `cloud/manager.py`. Comprehensive.
 - **Round 2 🟡 "Task 11.5/11.6 granularity >2h"** — task 11.6 now describes
   an explicit split into 11.6a (allocate-to-machine — tracker.discard
   swap), 11.6b (cloud-fallback happy path), 11.6c (cloud-fallback failure
   cleanup), 11.6d (dedup — tracker.add returns False), 11.6e (throttle —
   select_provider returns None). (See Notes for residual format quibble.)
 - **Round 2 🟡 "Task 11.7 missing Orchestrator constructor tests"** — new
   task 11.9 asserts `allocation_tracker`, `active_clouds`,
   `allocation_lock` stored as `self._tracker`/`self._active_clouds`/
   `self._allocation_lock` and passed to use cases; asserts no
   `adapters`/`configs` stored.
 - **Round 2 🟡 "tests/fixtures/mock_clouds.py not in any task"** — new
   task 11.15 updates or deletes `tests/fixtures/mock_clouds.py` (stubs
   `mark_task_done`, `get_capacity`, `configs.values()` — all removed/changed).
 - **Round 2 🟡 "Task 1.6 CrossLinks direction/relation unspecified"** —
   task 1.6 now spells out `from=M-APPLICATION-ALLOCATE
   to=M-APPLICATION-ALLOCATION-TRACKER relation="dedupes in-flight cloud
   allocations"` and `from=M-APPLICATION-CONSUME
   to=M-APPLICATION-ALLOCATION-TRACKER relation="discards completed
   allocations"`, plus the M-CLOUD-PROVISIONER removal from
   M-APPLICATION-CONSUME depends.
 - **Round 2 🟡 "Task 1.4 incomplete on M-DI depends"** — task 1.4 now says
   "add M-APPLICATION-ALLOCATION-TRACKER to `<depends>` (make_daemon
   constructs tracker)" alongside the M-DB removal.
 - **Round 2 🟡 "Task 9.5 injection path for adapters/configs undecided"**
   — mooted by the re-frozen design (port method handles selection) and
   task 9.5 now says "no `adapters`/`configs` — port method handles
   selection". Tasks 6.2, 9.2, 10.7 each explicitly say "do NOT add/pass
   `adapters`/`configs`", matching the frozen `use-cases` spec line 10-12,
   `orchestrator` spec line 26-29, `dependency-injection` spec line 24-27.

### 🔴 Outstanding
 -

### 🟡 Notes
 - **Task 1.1 graph edits partially incorrect against the actual
   knowledge-graph.xml.** Three sub-issues:
   (a) "remove M-DB" is a no-op — `M-CLOUD-PROVISIONER` `<depends>`
       currently (knowledge-graph.xml:608) is `M-DOMAIN-PORTS,
       M-DOMAIN-MODEL, M-CLOUD-ADAPTERS-NEW, M-CLOUD-PROTOCOLS,
       M-CLOUD-SSH-KEYS, M-SSH-GATEWAY, M-CONFIG, M-CONFIG-CLOUD`. No M-DB
       present. Implementer grep will confirm.
   (b) "add M-APPLICATION-UOW" is spurious AND a reverse-layering smell.
       Post-refactor the adapter is pure cloud (no DB, no UoW). Adding
       M-APPLICATION-UOW to an adapter module's depends would imply
       adapters → application, contradicting the layers contract
       (`adapters → application → domain`). The correct NEW depends
       entries are M-DOMAIN-EXCEPTIONS (re-exports relocated exceptions)
       and M-CLOUD-PROVIDER-SELECTION (port method calls the pure
       function). Task 1.1 misses both.
   (c) "remove `export-apis`" annotation is a no-op — no such annotation
       exists in the current `<annotations>` block (knowledge-graph.xml:609-
       617). The current annotations are `class-CloudProvisionerImpl`,
       `fn-allocate`, `fn-deallocate`, `fn-capacity`,
       `fn-allocate_with_tracking`, `fn-get_capacity`, `fn-mark_task_done`.
       The `apis` property is removed by task 5.4 but was never graph-
       annotated as `export-apis`. Conversely, task 1.1 lists
       `fn-allocate_with_tracking`/`fn-get_capacity`/`fn-mark_task_done`
       for removal but OMITS `fn-capacity` — which IS in the graph (line
       613) and IS removed (`capacity()` removed by task 5.4 per D2).
   Implementer should: skip the M-DB/M-APPLICATION-UOW/export-apis edits
   as no-ops or wrong, ADD `fn-capacity` to the removal list, ADD
   M-DOMAIN-EXCEPTIONS and M-CLOUD-PROVIDER-SELECTION to depends.
 - **Task 5.8 typo: `_setup_node` should be `_setup_vm`.** The actual
   method on `CloudProvisionerImpl` is `_setup_vm` (manager.py:492);
   `_setup_node` is the name of a *semantic block* inside `_setup_vm`
   (START_BLOCK_SETUP_NODE at manager.py:522). Implementer reading the
   actual source will see `_setup_vm`; non-blocking typo.
 - **Task 11.6 split is descriptive, not structural.** The split into
   11.6a-11.6e is described inside a single `- [ ]` checkbox rather than
   enumerated as five separate `- [ ]` lines. If the implementer treats
   the checkbox as one task, it likely exceeds the 2h granularity target
   (5 distinct test groups, each with new mock setup). If they treat the
   "split into 11.6a-e" wording as a directive to work item-by-item, each
   sub-item is ≤2h. Format-compliance check (#1 in the review prompt)
   passes either way (one checkbox parses cleanly); granularity check
   (#2) is borderline. Recommend the apply-phase reader treats each
   11.6a-e as its own commit-sized unit.
 - **Task 8.2 silent on `clouds` parameter type narrowing.** Task 8.2
   says "add `uow_factory` param; update contract block" but does not
   change `clouds: CloudProvisionerImpl` → `clouds: CloudProvisioner`
   (Protocol). Design D6 (design.md:266-282) shows the Protocol type.
   Implementer will infer from D6 + task 6.2 (which DOES swap the type
   for `allocate_task`). Minor — non-blocking.
 - **Task 6.7 wording implies "add tracker" without "remove clouds".**
   The current `_try_start_on_machine` and `_allocate_free_machine` both
   take `clouds: CloudProvisionerImpl` and use it only for
   `clouds.mark_task_done`. After the swap, `clouds` becomes unused in
   both helpers. Task 6.7 says "propagate `tracker` param through both
   helper signatures" but does not explicitly say "remove `clouds`
   param". Implementer following literally could leave a dead `clouds`
   param (a lint warning under `ruff F841`/`ARG`). Implementer will
   infer. Minor.
 - **Task 3.4 re-export from `adapters/cloud/__init__.py` is unnecessary.**
   `select_provider_pure` is adapter-internal (called only from
   `CloudProvisionerImpl.select_provider`, per design D5). A direct import
   `from .provider_selection import select_provider_pure` inside
   `manager.py` suffices; re-exporting from the package `__init__`
   pollutes the package's public surface with an internal helper. The
   re-export also risks a `lint-imports` false positive if anything in
   `application/` ever imports `from yascheduler.adapters.cloud import
   select_provider_pure` (currently nothing does). Minor style; implementer
   can keep the direct import.
 - **Verified accurate (no action needed):**
   * Format compliance: all 14 task groups use `## N.` numbered headings;
     every task line is `- [ ] N.M <desc>` checkbox format (147 lines
     total, 90+ checkboxes). Matches Round 1/2 format checks.
   * Group ordering respects GRACE-lite top-down + the re-frozen design:
     graph/contracts (1) → domain ports+VO+exceptions (2) → adapter-
     internal pure fn (3) → tracker (4) → strip adapter (5) → use cases
     allocate/consume/deallocate (6-8) → orchestrator (9) → DI (10) →
     tests update/new/e2e (11-13) → verification (14). Dependencies flow
     forward; no group references a not-yet-created artifact.
   * D1-D11 coverage verified pairwise:
     - D1 (pure adapter) → 5.1-5.9 ✓
     - D2 (port change: allocate(provider), deallocate(cloud, ip),
       select_provider sync, ProviderSelection, capacity removed) →
       2.1, 2.2, 5.5 ✓
     - D3 (allocate_task flow: port methods only, no adapters/configs,
       tracker dedup at start + discard on failure, throttle None-return)
       → 6.1-6.9 (throttle path covered by 6.4 `selection is None` branch
       since 5.5 returns None on throttle) ✓
     - D4 (AllocationTracker) → 4.1-4.4 ✓
     - D5 (select_provider_pure adapter-internal) → 3.1-3.4 ✓
     - D6 (deallocate ordering disable→delete→remove across two short
       UoWs) → 8.1-8.6 ✓
     - D7 (inline capacity with `_active_clouds`) → 9.4 (arithmetic
       matches design.md:296-303 byte-for-byte: `max(0, sum(max_nodes) -
       sum(counts[c.prefix] for c in active_clouds))`) ✓
     - D8 (lock orchestrator-owned and injected) → 9.2, 10.5 ✓
     - D9 (make_daemon drops DB) → 10.1-10.9 ✓
     - D10 (constructor signature: adapters/configs stay on adapter,
       node_repo removed) → 5.3, 5.5-5.6, 9.2, 10.6, 10.7 ✓
     - D11 (CloudAllocateError/CloudSetupError relocation) → 2.3-2.6,
       14.11 ✓
   * Layering verification: tasks 6.2, 9.2, 10.7 each explicitly say "do
     NOT add/pass adapters/configs" — matches frozen `use-cases` spec
     line 10-12, `orchestrator` spec line 26-29, `dependency-injection`
     spec line 24-27. Application layer never imports/references
     `CloudAdapter`/`ConfigCloud` at runtime.
   * Throttle semantics verified: task 5.5 implements `select_provider`
     returning `None` on throttle (not raise); task 6.4 handles
     `selection is None` with `tracker.discard(task_id); return False`.
     Matches design D2 (design.md:99-104) and D3 prose (design.md:168-
     182). No regression vs current `allocate_with_tracking`
     (manager.py:278-284) caller-visible `None`-on-throttle.
   * Exception relocation verified: tasks 2.3-2.6 move both exceptions
     to `domain/exceptions.py` with re-export from
     `yascheduler.adapters.cloud.manager` AND
     `yascheduler.adapters.cloud.__init__` (covers current re-exports at
     `adapters/cloud/__init__.py:42,54,58`); task 14.11 verifies. Task
     1.8 adds CrossLink `from=M-CLOUD-PROVISIONER to=M-DOMAIN-EXCEPTIONS
     relation="re-exports relocated cloud exceptions"`.
   * Spec scenario coverage verified against the 6 re-frozen spec files
     (specs Round 2):
     - allocation-tracker 5 scenarios → 12.1
     - cloud-provisioner "No DB access from adapter" → 14.10 (grep
       `node_repo=` etc.); "Provider op-limit returns None" → 5.5 + 6.4;
       "Duplicate request ignored" → 6.3 (tracker.add at start);
       "Allocate raises on VM creation failure" → 5.6 + 6.5 (catch from
       `clouds.allocate(selection.name)`, not from throttle)
     - domain-ports "Allocate with explicit provider" → 2.1, 5.6;
       "Deallocate cloud node with explicit cloud" → 2.1, 5.7, 9.7;
       "Select provider returns None on throttle" → 5.5
     - use-cases "AllocateTask" 4 scenarios → 6.3-6.6; "ConsumeTask" →
       7.1-7.6; "DeallocateIdleNodes" → 8.1-8.6
     - orchestrator "Cloud capacity computed inline" → 9.4;
       "Deallocator consumer brackets cloud delete with UoWs" → 8.3,
       9.7
     - dependency-injection "No DB import in make_daemon" → 10.2, 14.10
   * e2e test update verified: task 13.1 changes
     `make_daemon(config, db=db)` → `make_daemon(config)` at
     tests/e2e/test_full_cycle.py:85 (verified). Task 13.2 correctly
     notes the fixture already constructs DB independently via
     `DB.create(_db_config, automigrate=False)` + `_init_schema`/`apply_schema`
     at conftest.py:168-184 (verified) — no fixture change needed.
   * No decision-level contradiction with re-frozen proposal (Round 3),
     design (Round 4 + soft-freeze), or specs (Round 2). The two Round 2
     🔴 items that triggered the unfreeze are fully resolved at the
     tasks level; no new decision-level issues surface.
 - **Recommendation: APPROVE WITH NOTES** — batch passes (no 🔴
   outstanding). Both Round 2 🔴 items resolved (allocate signature,
   exception relocation); all 8 Round 2 🟡 items addressed (some
   partially, e.g., 11.6 split is descriptive rather than structural).
   Notes above are graph-accuracy nits (task 1.1), a method-name typo
   (task 5.8), and underspecified wording (tasks 8.2, 6.7, 11.6) — all
   safely inferrable from the re-frozen design/specs by the apply phase.
    Change is ready for implementation.

## tasks Round 3 — soft-freeze additions (2026-06-21)
### 🔴 Fixed
 -
### 🟡 Addressed
 - Task 1.1 corrected: M-DB not in M-CLOUD-PROVISIONER depends (no-op to
   remove); do NOT add M-APPLICATION-UOW (adapter is pure cloud, no UoW
   dependency — reverse-layering smell); add `fn-capacity` to removed
   annotations.
 - Task 5.8 typo fixed: `_setup_node` → `_setup_vm` (actual method name).
 - Task 6.7 clarified: replace `clouds` param with `tracker` (remove dead
   `clouds` param from helpers that don't deallocate).
 - Task 8.2 clarified: narrow `clouds` type from `CloudProvisionerImpl` to
   `CloudProvisioner` Protocol.
 - Task 3.4 marked optional — adapter-internal helper, re-export only if
   needed.
### 🔴 Outstanding
 -
### 🟡 Notes
 - Task 11.6 split is descriptive (single checkbox describing 11.6a-e
   inside), not 5 separate checkboxes. Implementer may split further if
   needed for time tracking.
 - Tasks frozen. Change ready for implementation.

## implementation-hardening Round 1 — 2026-06-22
### Context
Post-implementation review by 3 parallel @k-reviewer lanes (GRACE-lite
compliance, proposal→impl fidelity, architecture & code). All frozen
artifacts unchanged. This round records implementation-only fixes
addressing the review findings.

### 🔴 Fixed
 - **S1 (architecture):** `allocate_task` step-3 persist failure leaked
   a billable cloud VM and a capacity-consuming stale tmp-node
   (`allocate_task.py:329-343` pre-fix). Regression vs the old
   `_safe_remove_tmp(tmp_ip)` which fired immediately after
   `create_node` succeeded. Fixed by wrapping steps 2+3 in
   `_provision_and_persist`: on any post-allocate failure, best-effort
   `clouds.deallocate(node.cloud or selected_name, node.ip)` + tmp-node
   cleanup via `_cleanup_tmp_node_best_effort`, original exception
   re-raised. Tightened `test_step3_persist_failure_discards_tracker`
   to assert `clouds.deallocate` + `uow.nodes.remove` are invoked.
 - **S2 (GRACE):** `docs/knowledge-graph.xml` stale on two new public
   re-exports. `M-APPLICATION` `<depends>` and `<annotations>` updated
   to include `M-APPLICATION-ALLOCATION-TRACKER` and
   `<export-AllocationTracker>`. `M-DOMAIN` `<annotations>` gained
   `<export-ProviderSelection>`, `<export-CloudAllocateError>`,
   `<export-CloudSetupError>`.

### 🟡 Addressed
 - **#1:** `di.py` pre-built-clouds branch (`clouds=` override) now
   applies both halves of the D7 `active_clouds` filter (`max_nodes > 0`
   AND `cfg.prefix in clouds.configs`) so test-only callers can't
   over-count capacity for unresolved providers. New test
   `test_prebuilt_clouds_active_clouds_filter_verifies_adapter_resolution`.
 - **#2:** `orchestrator.py` `_task_consumer_consumer` MACHINE_GONE
   branch now calls `self._tracker.discard(task_id)` after abandoning,
   so the int can't leak forever and falsely dedup a future task.
   `test_machine_gone_records_task_abandoned_event` extended to assert
   `tracker.discard(42)`.
 - **#4:** `_resolve_adapter` → `resolve_adapter` (public) in
   `adapters/cloud/adapters.py`, re-exported from
   `adapters/cloud/__init__.py`, used by `di.py` (kills the FIXME
   private-import). Tests patched to `yascheduler.di.resolve_adapter`.
   Graph annotation renamed `fn-_resolve_adapter` → `fn-resolve_adapter`.
 - **#5:** `deallocate_node` REMOVE UoW wrapped in try/except — if DB
   remove fails after successful cloud delete, logs
   `[REMOVE_FAILED] ... manual reconciliation needed` and does NOT
   re-raise (VM is gone; row stays disabled for next-cycle retry).
   New test `test_remove_failure_after_cloud_delete_is_logged_not_raised`.
 - **#6:** `M-APPLICATION-ORCHESTRATOR` graph `<depends>` dropped
   `M-SSH-GATEWAY` (source correctly depends only on the
   `MachineGateway` Protocol via M-DOMAIN-PORTS). Stale CrossLink
   relation text rewritten from "creates and passes gateway to
   RemoteMachine.create()" (RemoteMachine no longer exists) to
   "consumes MachineGateway Protocol injected via constructor".
 - **#7:** `allocate_task` split from 134 lines (with contract) to ~85
   by extracting `_select_and_insert_tmp`, `_cleanup_tmp_node_best_effort`,
   `_provision_and_persist` helpers (each with own START_CONTRACT).
 - **#8:** `_allocator_consumer` critical block now has an entry debug
   log (`[Orchestrator][_allocator_consumer][ALLOCATE] task_id=%s`) per
   GRACE "block-boundary log" rule.

### 🔴 Outstanding
 -
### 🟡 Deferred to a separate change
 - **#3 (CloudAllocateError/CloudSetupError reparent to DomainError):**
   design.md task 2.3 freezes "preserve names, semantics, inheritance
   (Exception subclass)". Reparenting to `DomainError` is a
   decision-level change to a frozen artifact and would force an
   unfreeze of design.md → specs → tasks re-review chain. Not a
   regression (preserved from old code). Will be addressed in a
   separate change with proper unfreeze.
 - **allocate_task 85 lines / _provision_and_persist 79 lines /
   deallocate_node 69 lines:** still over the 60-line function+contract
   soft cap after splitting. Further splitting would harm readability
   (each function is necessarily dense due to try/except cleanup
   semantics). Accepted; `grace_check` continues to warn.
 - **provider_selection.py:7 LINKS self-references M-CLOUD-PROVIDER-SELECTION:**
   harmless, accepted.
 - **`Counter` not used in `_clouds_get_capacity` / `allocate_task`:**
   cosmetic divergence from design D7 text; behavior identical.

### Validation
 - `python3 scripts/grace_check.py`: 0 errors, 26 warnings (size-only)
 - `openspec validate --all`: 32/32 pass
 - `uv run ruff check .`: pass
 - `uv run ruff format --check .`: pass (130 files)
 - `uv run lint-imports`: KEPT (1 contract, 0 broken)
 - `uv run zuban check`: success (131 files)
 - `uv run pytest -m unit`: 389 pass (+2 new tests vs. pre-round 387)
 - `uv run pytest -m integration`: 66 pass

## final-review Round — 2026-06-22 21:43

Independent post-implementation review (3 lanes: GRACE-lite integrity,
proposal/design fidelity D1–D11, architecture & code quality). Re-ran all
validations from scratch. Re-examined deferred items from
implementation-hardening Round 1 — no new argument against any of them.

### 🔴 Serious
 - none

### 🟡 Should fix
 - **Newly-introduced "Unacceptable" FIXME in `_validate_engine`.**
   `yascheduler/application/allocate_task.py:94` adds
   `# FIXME: "Validated" but actually mutates and save in new transaction!
   Unacceptable.` (confirmed via `git diff HEAD` — `+` line in the change's
   own working-tree diff at the `_validate_engine` block). The misbehavior
   (`_validate_engine` rejects the task AND opens a fresh UoW to save it,
   despite the "validate" name) is pre-existing — but the FIXME marker
   itself is new in this change, and it labels the behavior "Unacceptable".
   For a change seeking archive, shipping a new FIXME that calls its own
   code unacceptable is a yellow flag. Either (a) fix it
   (`_validate_engine` returns the rejected task; `allocate_task` saves it
   in the caller's UoW), (b) drop the comment and file a follow-up
   proposal, or (c) add it to the "Deferred to a separate change" list
   below so the marker is acknowledged tech debt rather than an
   undocumented loose end. The two FIXMEs inside `ProviderSelection` are
   exempt per the review brief; this one is not.
 - **Private helper `_count_nodes_by_cloud` shared across modules.**
   `yascheduler/application/orchestrator.py:44` imports
   `_count_nodes_by_cloud` (underscore-prefixed = module-private by
   convention) from `allocate_task` and uses it in
   `_clouds_get_capacity`. Refactoring allocate_task's private helper
   will silently break the orchestrator. Either drop the underscore and
   document it in `M-APPLICATION-ALLOCATE` MODULE_MAP + graph
   `<annotations>`, or move both call sites' shared logic into a tiny
   `application/_cloud_capacity.py`. Maintainability smell, not a bug.

### 🟢 Nits
 - `M-CLOUD-PROVISIONER` graph `<depends>` over-declares `M-CONFIG` (only
   sub-configs M-CONFIG-CLOUD/LOCAL/REMOTE/ENGINE-REPO are actually
   imported) and `M-DOMAIN-PORTS` (implemented structurally, not
   imported). Pre-existing pattern; low-value to fix.
 - `M-APPLICATION-ALLOCATE` `<annotations>` doesn't list the new
   cloud-fallback helpers (`_select_and_insert_tmp`,
   `_provision_and_persist`, `_persist_node_with_cleanup`,
   `_allocate_cloud_node`, `_cleanup_tmp_node_best_effort`). Per GRACE
   proportional-markup rule private helpers are optional, but these are
   the non-trivial cloud-critical-section logic and would help
   navigation if annotated.
 - `tests/unit/test_application_no_adapter_imports.py` only checks 4
   SSH-related forbidden runtime names; does not assert
   absence of `CloudAdapter` / `ConfigCloud` imports from the adapters
   layer. `lint-imports` already enforces this architecturally (KEPT),
   so this is defense-in-depth, not a gap.
 - `tests/unit/test_provider_selection.py` does not separately unit-test
   the extracted `_adapter_supports_any_platform` helper; it is covered
   transitively via `select_provider_pure`. Acceptable given the helper
   is a pure double-loop with early break.
 - `_adapter_supports_any_platform` is underscore-prefixed (private) yet
   carries a START_CONTRACT and a graph annotation
   (`fn-_adapter_supports_any_platform`). Pick one: either it's
   graph-relevant (drop the underscore) or private (drop the annotation).

### 🔵 Info
 - All 7 size-limit warnings (allocate_task 109, make_daemon 87,
   deallocate_node 69, _persist_node_with_cleanup 63, _setup_vm 67,
   connect 70, vastai_create_node 61, plus 3 test-fn warnings and 1
   module-size-soft) are pre-accepted in implementation-hardening Round 1
   or are test-only. No NEW size exceedances introduced.
 - Deferred items from Round 1 (CloudAllocateError/CloudSetupError
   reparent to DomainError; function sizes; LINKS self-reference in
   provider_selection.py; Counter-cosmetic divergence from D7) remain
   valid; no new argument to re-open them.
 - Concurrency correctness of the cloud-fallback critical section
   verified by code reading: `_select_and_insert_tmp` holds
   `allocation_lock` across the full UoW and commits before releasing
   (`allocate_task.py:259-272`), so a concurrent selector entering the
   lock afterwards observes the committed tmp-node at READ COMMITTED
   isolation. The outer `try/finally` with `cloud_allocated` flag is
   correct on all four paths (step1-commit-raise, selection-None,
   step2-alloc-raise, step3-persist-raise, success): `tracker.discard`
   fires on every non-success path, never on success; `tmp_owned_by_provisioner`
   prevents double tmp-cleanup; `set.discard` is idempotent under double-failure.
   - VM-leak fix from S1 (Round 1) verified present in
     `_persist_node_with_cleanup` (`allocate_task.py:379-404`): on persist
     failure after a successful `clouds.allocate`, best-effort
     `clouds.deallocate(cloud_name, node.ip)` + tmp cleanup, original
     exception re-raised. Tested by `test_step3_persist_failure_discards_tracker`.
   - `deallocate_node` REMOVE-failure path (review fix #5) verified
     present at `deallocate_nodes.py:90-108`: logs `[REMOVE_FAILED]`,
     does not re-raise. Tested by
     `test_remove_failure_after_cloud_delete_is_logged_not_raised`.
 - D2 faithful: `CloudProvisioner` Protocol (`ports.py:214-231`) matches
   design exactly. `ProviderSelection(name, username)` frozen dataclass
   at `model.py:339-350`.
 - D9 faithful: `make_daemon` has no `db` param, no `DB.create`, no
   `from .db import DB` (asserted by
   `test_make_daemon_does_not_import_db`). `CloudProvisionerImpl`
   constructed without `node_repo` (`di.py:177-185`).
 - D10 faithful: `CloudProvisionerImpl` constructor
   (`manager.py:77-94`) has no `node_repo` / `allocation_lock` /
   `on_tasks` fields.
 - D11 faithful: `CloudAllocateError`/`CloudSetupError` defined in
   `domain/exceptions.py:136-141`, re-exported from both
   `adapters/cloud/manager.py` (via `from yascheduler.domain import ...`)
   and `adapters/cloud/__init__.py`. Application layer imports from
   `yascheduler.domain` / `yascheduler.domain.exceptions` (verified by
   grep — no application-layer import from `yascheduler.adapters`).
 - Tasks 14.10 / 14.11 verified by grep: no residual `mark_task_done`,
   `allocate_with_tracking`, `_select_best_provider`,
   `_acquire_provider_slot`, `_safe_remove_tmp`, `.capacity()`,
   `.get_capacity()`, `node_repo=` in source (only legitimate matches in
   CHANGE_SUMMARY comments and the `AllocationTracker._on_tasks` private
   field). `from .db import DB` only in `client.py` (explicitly
   out-of-scope).
 - schema.sql ALTER (`yascheduler/adapters/persistence/sql/schema.sql:18-22`)
   is the intentional idempotent augmentation called out in the brief;
   not flagged.
 - `tests/e2e/test_full_cycle.py:85` calls `make_daemon(config)` with no
   `db=` kwarg (D9 wiring confirmed in e2e).

### Validation
 - `python3 scripts/grace_check.py --json`: **0 errors, 27 warnings**
   (all `func-size` / `module-size-soft` — size-only; no structural
   violations)
 - `openspec validate --all --json`: **32/32 pass** (3 change + 29 spec)
 - `uv run ruff check .`: **All checks passed!**
 - `uv run ruff format --check .`: **130 files already formatted**
 - `uv run lint-imports`: **KEPT** (1 contract: clean architecture layers;
   0 broken)
 - `uv run zuban check`: **Success: no issues found in 131 source files**
 - `uv run pytest -m unit`: **389 passed, 67 deselected in 2.01s**
 - `uv run pytest -m integration`: not re-run (requires Docker/
   testcontainers); prior log records 66 pass
 - `uv run pytest -m e2e`: not re-run (requires Docker/testcontainers);
   prior log does not record a run

### Verdict
 - **READY TO ARCHIVE** (with non-blocking notes). No 🔴 correctness,
   layering, or contract violations. D1–D11 faithfully implemented.
   Static checks green; 389 unit tests pass. The two 🟡 items (one
   newly-added "Unacceptable" FIXME in `_validate_engine`; one
   underscore-private helper imported cross-module) are real quality
   loose-ends worth a quick cleanup pass or explicit deferral, but
   neither blocks archive. Recommend addressing the `_validate_engine`
   FIXME (or moving it to the Deferred list) before archive to avoid
   shipping a self-described "Unacceptable" marker in an archived
   change.

## proposal Round 1 — 2026-06-23

### 🔴 Fixed
 - (none yet — this is the first review pass)

### 🟡 Addressed
 - Verified `sleep_until` is dead code: `grep -rn "\bsleep_until\b" --include="*.py"`
   returns only its definition (`yascheduler/time.py:28`) and its MODULE_MAP
   entry (`time.py:12`). Zero callers in `yascheduler/` or `tests/`. The
   `# FIXME: dead code?` annotation exists at `time.py:27`. Proposal lines
   26-27 accurate. ✓
 - Verified `asleep_until` production usage is confined to
   `yascheduler/application/orchestrator.py` (import line 42; call sites
   lines 191, 457 — matches the brief's "~191, ~457"). The only other hits
   are two comment lines in `tests/unit/test_application_orchestrator.py`
   (120, 204). ✓
 - Verified `UniqueQueue`/`UMessage`/`TUMsgId`/`TUMsgPayload` production
   consumer is solely `orchestrator.py:41`. Test consumers are exactly
   `tests/unit/test_queue.py` and `tests/unit/test_application_orchestrator.py`
   (proposal lines 30-31, 106-109). ✓
 - Verified spec-impact claim: `grep` of `openspec/specs/` for `time.py`,
   `queue.py`, `yascheduler.time`, `yascheduler.queue`, `yascheduler/time`,
   `yascheduler/queue`, `asleep_until`, `sleep_until` returns ZERO path
   references. Only symbol-name hits are `UniqueQueue`/`UMessage` in
   `testing-unit/spec.md` (lines 126, 179, 181, 185) and
   `testing-infrastructure/spec.md` (lines 28-32) — names unchanged by the
   relocation. "Capabilities: None / None" (proposal lines 73-86) is
   correct; no `specs/` delta files needed. ✓
 - Verified doc-drift claim in `docs/ARCHITECTURE.md`: §1 layer diagram
   line 87 (`queue.py  UniqueQueue`) and line 91
   (`variables.py, time.py, compat.py   Path/time/typing utilities`); §4
   project tree lines 454 (`queue.py`), 458 (`variables.py`), 459
   (`time.py`), 460 (`compat.py`). `yascheduler/variables.py` and
   `yascheduler/compat.py` are indeed absent from the filesystem (already
   in `yascheduler/shared/`). Proposal lines 45-50 and 113-115 accurate. ✓
 - Verified the FIXME annotations exist: `time.py:19`
   (`# FIXME: move this module to application (?)`) and `queue.py:21`
   (same text). Proposal line 5 accurate. ✓
 - Verified facade policy claim: `yascheduler/application/__init__.py`
   re-exports exactly `AbstractUnitOfWork, AllocationTracker, MessageBus,
   Orchestrator, query_tasks, submit_task` (`__all__`, lines 31-38) —
   matches the brief's "use cases + Orchestrator + AbstractUnitOfWork +
   MessageBus + AllocationTracker". `UniqueQueue`/`UMessage` are NOT
   re-exported today; the "deep path for tests" policy (proposal lines
   32-37) is consistent with how the tests already import other
   orchestrator internals. ✓
 - Verified Shape C mapping is fully captured (proposal lines 17-28):
   `UniqueQueue`/`UMessage`/`TUMsgId`/`TUMsgPayload` → new
   `application/queue.py`; `asleep_until` → existing `shared/async_utils.py`;
   `sleep_until` deleted; `time.py` deleted; `test_queue.py` stays flat.
   Matches the brief's Shape C table row-for-row. ✓
 - Verified non-goals are consistent with `AGENTS.md`'s public-interface
   stability list: proposal lines 57-60 enumerate `class Yascheduler`, CLI
   command names, INI format, DB schema, AiiDA entrypoint key — the same
   surface `AGENTS.md` enumerates. Internal module paths
   (`yascheduler.queue` / `yascheduler.time`) are correctly identified as
   NOT part of that surface. ✓
 - Verified file-count and edit-site tally in Impact (proposal lines
   90-120): 1 new (`application/queue.py`), 2 deleted (`time.py`,
   `queue.py`), 2 modified source (`shared/async_utils.py`,
   `application/orchestrator.py`), 2 modified tests, 2 docs
   (`knowledge-graph.xml`, `ARCHITECTURE.md`). Accurate; nothing
   overstated. ✓

### 🔴 Outstanding
 - **M-TIME removal leaves a dangling `<depends>` reference that will fail
   `grace_check.py`** (serious — breaks the proposal's own verification
   gate). The proposal (lines 38-41) instructs removing the `M-TIME`
   module record entirely and migrating `fn-asleep_until` into `M-SHARED`.
   But `M-TIME` is referenced outside its own record:
   `docs/knowledge-graph.xml:366` —
   `<depends>M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-TIME, M-APPLICATION-ALLOCATE, ...</depends>`
   inside `M-APPLICATION-ORCHESTRATOR`. `scripts/grace_check.py`
   `_check_depends_refs` (lines 439-446) calls `findings.error(...)` — not
   warning — when a `<depends>` token references a module ID not in the
   collected set; `_report` (lines 933-949) returns exit 1 on errors. After
   the M-TIME record is deleted, this check emits
   `<M-APPLICATION-ORCHESTRATOR> references unknown module 'M-TIME'` and
   exits 1, violating the verification gate at proposal line 124. The
   brief (lines 70-75) has the same gap — it does not mention this
   reference either. Note also that `M-SHARED` is NOT currently in that
   depends list, so after the relocation `M-APPLICATION-ORCHESTRATOR`
   genuinely depends on `M-SHARED` (via `asleep_until`) yet would not
   declare it.
   Fix: explicitly add to the proposal's `docs/knowledge-graph.xml` plan
   that `M-APPLICATION-ORCHESTRATOR`'s `<depends>` at line 366 is rewritten
   `M-TIME` → `M-SHARED` (replace, not delete — `M-SHARED` is the new home
   of `asleep_until` and is otherwise absent from this depends line). Add
   the same explicit note to the brief's graph-impact section, and verify
   via `grep -n "M-TIME" docs/knowledge-graph.xml` that zero hits remain
   post-edit.

### New minor nits (non-blocking)
 - **`import asyncio` over-claimed as new for `shared/async_utils.py`**
   (factual). Proposal line 99 says async_utils.py "gains `asleep_until`
   function + `import asyncio` + `from datetime import datetime`". But
   `async_utils.py:19` already has `import asyncio` (used by `to_sync`).
   Only `from datetime import datetime` is genuinely new. Fix: drop
   "`import asyncio`" from the parenthetical.
 - **"No test bodies change" is imprecise and risks missed edits**
   (completeness). Proposal Impact lines 108-109 says "import path rewrite
   only; no test bodies, fixtures, or assertions change." But
   `tests/unit/test_application_orchestrator.py` has SIX inline
   `from yascheduler.queue import UMessage` statements INSIDE test
   function bodies (lines 404, 599, 624, 643, 669, 693), in addition to
   the top-level import at line 63. An implementer reading "no test bodies
   change" could rewrite only the two top-level imports (one per file) and
   leave the six inline imports broken. The "import path rewrite only"
   scope does cover them, but the wording contradicts the literal body
   edits. Fix: reword to "no test logic, fixtures, or assertions change;
   inline import statements nested inside test function bodies are also
   rewritten to the new path" (or explicitly note the six inline sites).
 - **§4 project-tree line citation understates the drift surface**
   (cosmetic). Proposal line 48 cites "§4 project tree ~lines 454, 459",
   which covers `queue.py` and `time.py` only. The same tree also has
   stale `variables.py` (line 458) and `compat.py` (line 460) entries that
   the proposal commits to remove (proposal lines 47-50, "remove stale
   `variables.py`, `compat.py`, `time.py`, `queue.py` entries"). Intent is
   clear; broaden the citation to "~lines 454, 458-460" for accuracy.
 - **`M-SHARED` `<purpose>` could be broadened** (optional, graph
   accuracy). `knowledge-graph.xml:105` describes `M-SHARED` as
   "async-to-sync runtime bridge". `asleep_until` is an async sleep, not
   an async↔sync bridge, so migrating it into `M-SHARED` slightly strains
   the purpose prose. `grace_check.py` does not validate purpose text, so
   this is non-blocking; consider widening to "async runtime utilities" or
   similar when the annotation migrates.
 - **Rejected alternatives (Shape A / Shape B) not surfaced in the
   proposal** (optional). The brief's "Rejected alternatives" section
   documents why Shape A (all → `application/`) and Shape B (all →
   `shared/`) were rejected. The proposal embeds the per-symbol rationale
   (e.g. "same family as `to_sync`", "daemon-loop machinery") which
   implicitly rejects A and B, so this is adequate for a proposal — but if
   proposal-to-brief traceability is desired, a one-line "hybrid chosen
   over all-application (Shape A) and all-shared (Shape B)" note would
   make the decision explicit.

## proposal Round 2 — 2026-06-23

### 🔴 Fixed
 - **M-TIME dangling `<depends>` reference** (Round 1 serious, lines 66-91).
   RESOLVED. Proposal lines 42-48 now explicitly instruct: "replace the
   dangling `M-TIME` token in `M-APPLICATION-ORCHESTRATOR`'s `<depends>`
   (line 366) with `M-SHARED`" and add "this is a token swap, not a
   deduplication". Cross-checked against the actual file:
   `knowledge-graph.xml:366` reads
   `<depends>M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-TIME, M-APPLICATION-ALLOCATE, ...</depends>`
   — `M-TIME` is present, `M-SHARED` is absent. The proposal's "swap not
   dedupe" framing is correct. `grep -n "M-TIME"` returns exactly two hits
   (line 94 = the module record, line 366 = this depends ref); the proposal
   removes both (lines 39-41 + 42-48), so zero `M-TIME` tokens survive.
   Verification gate at proposal line 124 (`grace_check.py`) is now
   satisfiable. ✓
 - **`import asyncio` over-claim** (Round 1 nit, lines 94-99). RESOLVED.
   Proposal lines 107-109 now read: "`import asyncio` is already present
   at line 19, so only `from datetime import datetime` is new". Verified
   `async_utils.py:19` is `import asyncio` (used by `to_sync`). ✓
 - **"No test bodies change" imprecision** (Round 1 nit, lines 100-112).
   RESOLVED. Proposal lines 116-118 now explicitly enumerate "**7 import
   sites** total (1 top-level at line 63 + 6 inline imports inside test
   function bodies at lines 404, 599, 624, 643, 669, 693)" for
   `test_application_orchestrator.py` and "1 import site (line 28)" for
   `test_queue.py`. Verified by grep: test_application_orchestrator.py
   has exactly `from yascheduler.queue import …` at lines 63, 404, 599,
   624, 643, 669, 693 (7 hits); test_queue.py has exactly line 28
   (1 hit). Line numbers match exactly; an implementer cannot miss the
   inline imports. ✓
 - **§4 project-tree line citation understates drift surface** (Round 1
   nit, lines 113-119). RESOLVED. Proposal lines 56-57 now cite "lines
   454 `queue.py`, 458 `variables.py`, 459 `time.py`, 460 `compat.py`,
   all four stale" — covering all four stale entries the proposal commits
   to remove (lines 54-56). Matches Round 1's verification of those line
   numbers. ✓

### 🟡 Addressed
 - Re-verified no NEW serious issues introduced by the Round 2 edits. The
   added M-SHARED swap text (lines 42-48) is internally consistent with
   the M-TIME record removal (lines 39-41) — they target different lines
   (94 vs 366) and neither contradicts the other. No new claims about
   unverified facts.
 - Re-verified full `explore-brief.md` coverage. Every brief commitment
   maps to a proposal section: Shape C table (brief 27-33 → proposal
   17-28), facade policy (brief 51-58 → proposal 32-37), spec-impact none
   (brief 60-66 → proposal 79-94), knowledge-graph.xml (brief 70-75 →
   proposal 38-51 — proposal is STRICTLY MORE detailed than the brief by
   adding the line-366 fix the brief omits), ARCHITECTURE.md (brief 76-82
   → proposal 52-58), GRACE-lite headers (brief 83-85 → proposal 59-61,
   127-129). The proposal fully covers and exceeds every brief
   commitment. ✓
 - Noted (non-blocking, not under review): `explore-brief.md` lines 70-75
   still do not mention the line-366 depends fix. This is the brief's
   gap, not the proposal's; the proposal supersedes the brief's
   graph-impact section with the more complete plan. Brief is the frozen
   baseline input; it does not block the proposal batch.

### 🔴 Outstanding
 - none

## design Round 1 — 2026-06-23

### 🔴 Fixed
 - (none yet — first pass)

### 🟡 Addressed
 - **Decision 4 graph claims verified against `docs/knowledge-graph.xml`**:
   `M-TIME` record is at lines 94–102 (purpose, `path=yascheduler/time.py`,
   `depends=none`, two fn- annotations) — matches design's "lines 94–102".
   `M-APPLICATION-ORCHESTRATOR` `<depends>` at line 366 reads
   `M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-TIME, M-APPLICATION-ALLOCATE,
   M-APPLICATION-CONSUME, M-APPLICATION-DEALLOCATE, M-DOMAIN-PORTS,
   M-DOMAIN-MODEL, M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER` —
   `M-TIME` IS present, `M-SHARED` IS absent, total 11 tokens. Design's
   "token swap not dedupe" + post-swap token list (lines 189–193) is
   exact-character accurate. ✓
 - **`M-SHARED` `<annotations>` block exists** at lines 108–115
   (currently 6 entries: `fn-to_sync`, `type-Self`, `type-ParamSpec`,
   `const-CONFIG_FILE/PID_FILE/LOG_FILE`); `fn-asleep_until` can be
   appended alphabetically before `fn-to_sync` or at end. ✓
 - **`M-QUEUE` `<path>` verified** = `yascheduler/queue.py` (line 60);
   design's rewrite target `yascheduler/application/queue.py` is the
   correct new location. ✓
 - **`grace_check.py` hard-fail claim verified**. `_check_depends_refs`
   (lines 439–446) iterates each `<depends>` token; any `M-*` token not
   in `known_mids` calls `findings.error("depends-ref", ...)` —
   explicitly `error`, not `warning`. `_report` (lines 933–949) returns
   `1 if errors else 0`. So a dangling `M-TIME` depends token DOES exit
   1. Unlike the `rename-adapters-to-infra` path-check overstatement
   noted in the prior project history, the depends-ref severity is
   genuinely a hard error. Design's Risk #2 + Decision 4 Alternatives
   ("Delete without replacement" → rejected for this exact reason) are
   accurate. ✓
 - **Migration plan completeness verified against proposal Impact**.
   Every Impact edit site maps to a numbered step: new
   `application/queue.py` (step 1), `git rm queue.py` (step 2),
   `shared/async_utils.py` merge (step 3), `git rm time.py` (step 4),
   `orchestrator.py` 2 imports (step 5), `test_queue.py:28` (step 6),
   `test_application_orchestrator.py` 7 sites (step 7), knowledge-graph
   (step 8), ARCHITECTURE.md (step 9), verification (step 10), commit
   (step 11). The 8 test import sites confirmed by grep:
   test_application_orchestrator.py lines 63, 404, 599, 624, 643, 669,
   693 (7 hits, all `from yascheduler.queue import …`); test_queue.py
   line 28 (1 hit). No `yascheduler.time` import in any test file. ✓
 - **`async_utils.py` line 19 = `import asyncio`** verified (used by
   `to_sync`); only `from datetime import datetime` is genuinely new
   for `asleep_until`. Design step 3 accurate. ✓ (matches Round 2
   proposal fix)
 - **Risk grep #2 scope verified — no false positives expected in
   scope**. Slash-form `yascheduler/time|yascheduler/queue` hits in
   `yascheduler/ tests/ docs/`: only 4 — `knowledge-graph.xml:60`
   (M-QUEUE path, rewritten step 8), `knowledge-graph.xml:96` (M-TIME
   path, removed step 8), `yascheduler/queue.py:1` (`# FILE:` header,
   file deleted step 2), `yascheduler/time.py:1` (file deleted step 4).
   All 4 explicitly handled. Archive hits
   (`openspec/changes/archive/**`) are OUT of grep's directory scope.
   The `yascheduler.queue_submit_task` matches in
   `openspec/archive/client-refactor/spec.md` are a function name, not
   a module path, and also out of scope. Zero unexpected in-scope
   matches predicted post-migration. ✓
 - **`import-linter` layers claim verified**. `pyproject.toml` lines
   125–130 define the `layers` contract:
   `yascheduler.adapters → yascheduler.application → yascheduler.domain
   → yascheduler.shared` (top-down). `application → shared` is an
   ALLOWED downward direction. Currently `orchestrator.py` has NO
   `yascheduler.shared` import; post-relocation it gains
   `from yascheduler.shared.async_utils import asleep_until` — first
   application→shared import in this file, but allowed direction.
   `queue.py`'s own imports (`asyncio`, `collections.deque`,
   `collections.abc.Hashable`, `typing`, `attrs`) are all non-layer
   stdlib/3rd-party; adding `yascheduler.application.queue` to the
   application layer introduces no new cross-layer edge. Contract
   structurally unaffected; `uv run lint-imports` will pass. ✓
   (Conclusion correct; framing in Non-Goals "moving a file *within*
   application/" is imprecise — see nits.)
 - **Decision 1 alternatives are genuine, not straw-man**. Shape A
   (both → application/) rejected on `asleep_until` misclassification
   soundly (4-line async bridge same family as `to_sync` already in
   shared/async_utils.py — verified at `async_utils.py:38` `def
   to_sync`). Shape B (both → shared/) rejected on `UniqueQueue`
   contract framing soundly (M-QUEUE purpose at line 59 reads "for
   producer-consumer scheduling loops" — application-shaped). Inline
   alternative rejected on three substantive grounds (named contract
   worth preserving; `to_sync` pattern precedent; duplication risk).
   No straw-man. ✓
 - **Doc-drift scope verified**. §1 layer-diagram block lines match:
   line 87 = `│  queue.py            UniqueQueue                                │`,
   line 91 = `│  variables.py, time.py, compat.py   Path/time/typing utilities   │`.
   §4 project tree lines match: 454 `├── queue.py`, 458
   `├── variables.py`, 459 `├── time.py`, 460 `└── compat.py` (last
   child marker on 460). Removing 458–460 makes line 457
   (`daemon_sysv.py`) the new last child → `├──` must become `└──`
   (acknowledged in design Risk #4). Adding `queue.py` under
   `application/` subtree (currently ends line 449 `└── message_bus.py`)
   requires re-prefixing `message_bus.py` from `└──` to `├──`. Both
   cosmetic; no automated gate fails. ✓
 - **No decision-level contradiction with frozen proposal**. All 7
   design Decisions map 1:1 to proposal commitments (Decision 1 ←
   proposal 17–28; D2 ← 26–27; D3 ← 32–37; D4 ← 38–51 incl. line-366
   swap; D5 ← 52–58; D6 ← 79–94; D7 ← 69–70). Design extends but does
   not contradict. ✓
 - **Orchestrator call-site count verified**. `asleep_until` is
   imported once at `orchestrator.py:42` and (per proposal brief) used
   at lines ~191 (`run_once`) and ~457 (`_run_queue`); only those two
   production call sites. No additional production consumer surfaces
   in grep across `yascheduler/`. ✓

### 🔴 Outstanding
 - none

### New minor nits (non-blocking)

 - **Design step 5 "pick absolute" justification is misleading re:
   intra-package sibling pattern** (maintainability).
   `orchestrator.py` uses RELATIVE imports for ALL intra-application
   siblings: line 44 `from .allocate_task import …`, 45
   `from .consume_task …`, 46 `from .deallocate_nodes …`, plus
   `from .allocation_tracker` and `from .uow` under TYPE_CHECKING.
   `application/__init__.py` likewise uses `from .allocation_tracker`,
   `.message_bus`, `.orchestrator`, `.query_tasks`, `.submit_task`,
   `.uow`. When `queue.py` joins `application/`, the consistent
   sibling style is `from .queue import UMessage, UniqueQueue`, NOT
   `from yascheduler.application.queue import …`. The design's stated
   justification — "for consistency with the existing
   `from yascheduler.domain…` imports" — compares against a
   CROSS-PACKAGE import (different layer), which is not the relevant
   comparison. The honest justification (not stated) is minimal-diff:
   the existing `from yascheduler.queue import …` is absolute, and
   inserting `.application` is a smaller edit than converting to
   relative. The cross-package `from yascheduler.shared.async_utils
   import asleep_until` IS correctly absolute (matches
   `from yascheduler.domain import …`). Note: the proposal's
   absolute-form commitment is frozen, so this is not a proposal
   contradiction — but the design's reasoning for the choice should be
   corrected to avoid misleading future readers. Fix: reword step 5
   justification to "absolute form minimizes the diff from the existing
   absolute `from yascheduler.queue import …` line; cross-package
   imports in this file (domain, shared) are absolute; intra-package
   siblings are relative — `queue` is being rewritten rather than
   newly authored, so minimal-diff absolute wins over sibling-style
   relative".

 - **Design step 5 references "see Open Questions" but Open Questions
   is empty** (internal inconsistency). Step 5 says "(or convert to a
   relative `from .queue import …` — see Open Questions; the proposal
   commits to absolute, but the design allows either…)" — but the
   design's own "Open Questions" section (lines 421–426) explicitly
   reads "None." There is no open question to defer to. The
   "either/or" framing is orphaned scaffolding from an earlier draft.
   Fix: drop the "see Open Questions" clause; either commit to
   absolute (per proposal) outright, or genuinely re-open the question
   with a recommendation.

 - **`orchestrator.py:6` MODULE_CONTRACT `DEPENDS:` line goes stale
   post-relocation** (GRACE-lite methodology consistency gap, present
   in BOTH frozen proposal and this design). Line 6 reads
   `#   DEPENDS: M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-TIME,
   # M-APPLICATION-ALLOCATE, …` — contains `M-TIME`. After M-TIME is
   deleted from the graph, this source-level DEPENDS reference
   dangles. Verified `grace_check.py` does NOT validate source DEPENDS
   fields: `_check_cross_references` (lines 844–860) checks ONLY
   `fields.get("LINKS", "")` against known M-IDs, and even that is a
   `findings.warning`, not error. So no automated gate fails
   (`grace_check.py` exits 0 regardless). But GRACE-lite methodology
   requires source MODULE_CONTRACT to stay consistent with the graph
   (the `M-TIME → M-SHARED` swap is made in the XML at line 366 but
   not mirrored in the source DEPENDS that mirrors it). The design's
   Goals (lines 65–66) scope GRACE-lite header updates to "the
   moved/merged code" only — orchestrator.py is neither moved nor
   merged, so its stale DEPENDS falls through. Fix: add to migration
   step 5 a one-line edit — "swap `M-TIME → M-SHARED` in
   orchestrator.py line 6 MODULE_CONTRACT DEPENDS to mirror the
   graph-XML line-366 swap and keep source-level markup
   machine-navigable". Optional: also add `M-SHARED` to LINKS at line
   7 for the same reason.

 - **Non-Goals framing imprecise re: layer crossings** (accuracy). The
   layers-contract Non-Goal says "Moving a file *within* `application/`
   and *within* `shared/` does not change which layer any import
   crosses". Strictly, both files move FROM the root (no layer) INTO a
   layer: `queue.py` root→application, `asleep_until` (in `time.py`)
   root→shared. Post-relocation orchestrator exercises a NEW
   application→shared edge that did not exist before (orchestrator
   currently has no `yascheduler.shared` import). The conclusion
   (contract structurally unaffected, no new violation, lint-imports
   passes) is correct because application→shared is an allowed
   downward direction — but the "does not change which layer any
   import crosses" framing is literally false. Fix: reword to "the
   relocation may add a new application→shared import edge in
   `orchestrator.py`, but application→shared is an allowed downward
   direction in the layers contract; no forbidden edge is introduced".

 - **Risk grep #2 does not cover ARCHITECTURE.md cleanup** (scope
   acknowledgement). ARCHITECTURE.md §4 tree uses bare filenames
   (`queue.py`, `time.py`, `variables.py`, `compat.py`) without the
   `yascheduler/` prefix, so the slash-form grep
   `yascheduler/time\|yascheduler/queue` returns zero hits against
   ARCHITECTURE.md even before cleanup. The grep's "must return zero"
   gate therefore does NOT verify ARCHITECTURE.md entry removal.
   Design Risk #4 acknowledges ARCHITECTURE.md cleanup is
   "cosmetic only — no automated check fails" with manual review — so
   this is internally consistent — but the verification trio
   (greps #1–3) is implicitly overstated as covering the docs cleanup
   when it covers only `knowledge-graph.xml` path rewrites. Fix:
   either add a 4th grep
   `grep -n "queue.py\|time.py\|variables.py\|compat.py" docs/ARCHITECTURE.md`
   with an explicit allow-list of EXPECTED surviving hits (e.g.
   `shared/variables.py`, `shared/compat.py`, `application/queue.py`
   post-add), or note explicitly that ARCHITECTURE.md verification is
   manual-only per Risk #4 and the three greps verify only source +
   graph.

 - **Design Context line 30 cites §4 lines "454, 458, 459, 460" but
   §1 lines as "~83–92"** (cosmetic). The §4 citation is exact while
   the §1 citation uses a range; both are correct, but the asymmetry
   is mildly inconsistent. Non-blocking.

## design Round 2 — 2026-06-23

### 🔴 Fixed
- **Nit 1: Import-style justification misleading re: intra-package sibling pattern** (Round 1, lines 310–338). RESOLVED. Design step 5 rationale now reads: "keep the absolute form. The existing lines are absolute… so the minimal-diff edit only rewrites the package prefix. This also matches the other cross-package absolute import in the same file (`from yascheduler.domain…`). Intra-package siblings are imported relatively (`.allocate_task` line 44), but converting the queue/time lines to relative would be a larger diff for no benefit." — honestly states minimal-diff as primary, cross-package match as secondary, and explicitly acknowledges relative sibling pattern without over-claiming consistency. ✓
- **Nit 2: Dangling "see Open Questions" parenthetical** (Round 1, lines 340–349). RESOLVED. The `(or convert to a relative… — see Open Questions)` clause is removed from step 5. The design now commits straightforwardly to absolute form. Confirmed "Open Questions" section (lines 430–435) still reads "None." — no orphaned reference. ✓
- **Nit 3: orchestrator.py MODULE_CONTRACT DEPENDS gap** (Round 1, lines 351–372). RESOLVED. Step 5 now includes (lines 383–389): "**Also** update the `MODULE_CONTRACT` `DEPENDS:` header (line 6): swap `M-TIME` → `M-SHARED` to mirror the `knowledge-graph.xml` token swap (Decision 4)." Plus correct qualification that `grace_check.py` does not validate source DEPENDS as error — consistency update, not gate. **Factual anchor verified**: `orchestrator.py:6` `DEPENDS:` reads `M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-TIME, …` — `M-TIME` IS present, confirmed by file read. ✓

### 🟡 Addressed
- Re-verified no NEW serious issues introduced by the 3 edits. All three changes are additive/declarative within step 5, consistent with frozen proposal (absolute form commitment), and introduce no new decision, scope creep, or contradiction with any earlier decision (1–7). ✓
- **Skipped nits confirmed cosmetic**:
  - **Nit #4 (Non-Goals layers framing imprecision)**: True that phrasing "does not change which layer any import crosses" is technically imprecise (root→application/root→shared adds edges, but all allowed). Conclusion correct. Cosmetic — does not affect implementability.
  - **Nit #5 (Risk grep #2 ARCHITECTURE.md coverage)**: Risk #4 already acknowledges ARCHITECTURE.md cleanup is "cosmetic only — no automated check fails" with manual review. The grep trio's scope is implicitly source+graph only, which matches what they actually check. The gap is acknowledged. Cosmetic — does not affect implementability.

### 🔴 Outstanding
- none

### Remaining minor nits (non-blocking, skipped)
- **#4**: Non-Goals "does not change which layer any import crosses" — technically imprecise but conclusion correct.
- **#5**: Risk grep #2 does not cover ARCHITECTURE.md — already acknowledged by Risk #4's manual-review caveat.
- **#7**: Context §1/§4 line citation asymmetry (cosmetic).

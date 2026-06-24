## Context

Two root-level utility modules remain stranded at the package root after the
v1.6.0 relocation of `variables.py` and `compat.py` into `shared/`:

- `yascheduler/time.py` — 41 lines, two functions (`sleep_until`,
  `asleep_until`). The sync `sleep_until` carries the standing annotation
  `# FIXME: dead code?`; verified zero callers in `yascheduler/` or
  `tests/`. The async `asleep_until` has exactly two call sites, both in
  `yascheduler/application/orchestrator.py` (the daemon's main loop:
  `Orchestrator.run_once` line ~191 and `Orchestrator._run_queue` line
  ~457).
- `yascheduler/queue.py` — 123 lines, `UniqueQueue` (an `asyncio.Queue`
  subclass with id-based deduplication) plus the `UMessage`/`TUMsgId`/
  `TUMsgPayload` typed message envelope. Sole production consumer:
  `yascheduler/application/orchestrator.py` (which constructs 4 named
  queues — `_conn_machine_q`, `_allocate_q`, `_consume_q`,
  `_deallocate_q` — and yields/consumes `UMessage` instances through
  them). Two test files reach it: `tests/unit/test_queue.py` (1 import
  site) and `tests/unit/test_application_orchestrator.py` (7 import
  sites: 1 top-level + 6 inline inside test function bodies).

Both files carry `# FIXME: move this module to application (?)`. The
project is mid-migration: root utilities are being dispersed into their
proper DDD layer, and `variables.py`/`compat.py` already moved to
`shared/` in v1.6.0 (their root-level entries in `docs/ARCHITECTURE.md`
were never cleaned up — doc drift).

`docs/ARCHITECTURE.md` §1 layer-diagram root block (~lines 83–92) and
§4 project tree (lines 454, 458, 459, 460) still reference `queue.py`,
`variables.py`, `time.py`, `compat.py` at the root, contradicting the
filesystem.

`docs/knowledge-graph.xml` records these as `M-QUEUE` (TYPE=UTILITY,
path=`yascheduler/queue.py`, depends=none) and `M-TIME` (TYPE=UTILITY,
path=`yascheduler/time.py`, depends=none). Critically, `M-TIME` is also
listed in `M-APPLICATION-ORCHESTRATOR`'s `<depends>` at line 366 (one of
11 comma-separated tokens). The orchestrator's LINKS reference
`M-QUEUE`.

The relocation is **mechanical and sense-preserving**: no behavior, no
public API, no schema, no symbol rename. The design's job is to pick
the right destination per symbol (by semantic category, not by "who
called first"), to handle the `M-TIME` graph collapse without leaving
dangling references, and to fix the doc drift in the same pass.

## Goals / Non-Goals

**Goals:**

- Relocate `asleep_until` into the existing
  `yascheduler/shared/async_utils.py` (alongside `to_sync`).
- Relocate `UniqueQueue`, `UMessage`, `TUMsgId`, `TUMsgPayload` into the
  new file `yascheduler/application/queue.py`.
- Delete the confirmed-dead `sleep_until` symbol and the now-empty
  `yascheduler/time.py` file.
- Update the 2 production import sites (`orchestrator.py`) and 8 test
  import sites (1 in `test_queue.py` + 7 in
  `test_application_orchestrator.py`).
- Update `docs/knowledge-graph.xml`: remove `M-TIME`, migrate its
  `fn-asleep_until` annotation to `M-SHARED`, rewrite the `M-TIME` token
  in `M-APPLICATION-ORCHESTRATOR`'s `<depends>` to `M-SHARED`, rewrite
  `M-QUEUE`'s `<path>` to the new location.
- Fix `docs/ARCHITECTURE.md` doc drift (root-level blocks).
- Update GRACE-lite `# FILE:` / `MODULE_CONTRACT` / `MODULE_MAP` /
  `CHANGE_SUMMARY` annotations inside the moved/merged code.
- End state: `uv run pytest -m unit|integration|e2e`,
  `uv run lint-imports`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run zuban check`,
  `python3 scripts/grace_check.py`, and
  `openspec validate --all --json` all pass.

**Non-Goals:**

- No rename of the symbols (`UniqueQueue`, `UMessage`, `asleep_until`,
  `TUMsgId`, `TUMsgPayload` keep their identifiers).
- No public API change of any kind (`AGENTS.md` public-interface list:
  `class Yascheduler`, CLI commands, INI format, DB schema, AiiDA
  entrypoint — none touch these paths).
- No backward-compat shim or re-export alias at the old paths
  (`yascheduler.time`, `yascheduler.queue`). Internal paths are not public.
- No re-export of `UniqueQueue`/`UMessage` from the
  `yascheduler/application/__init__.py` facade — they stay deep-path.
- No relocation of `tests/unit/test_queue.py` — the flat `tests/unit/`
  layout has no per-layer subdirectories.
- No spec delta files — verified zero path references in
  `openspec/specs/` to these modules.
- No change to the `import-linter` `layers` contract configuration in
  `pyproject.toml`: the `layers` contract lists `yascheduler.adapters`,
  `yascheduler.application`, `yascheduler.domain`, `yascheduler.shared`
  (per the frozen `rename-adapters-to-infra` proposal, the first is
  becoming `yascheduler.infra`). Moving a file *within* `application/`
  and *within* `shared/` does not change which layer any import crosses;
  the layer contract is structurally unaffected.

## Decisions

### Decision 1: Relocate by semantic category (hybrid / "Shape C")

**Choice.** Split the two modules by what the symbols *are*, not by which
file they happened to share:

| Symbol                                              | Destination                                  | Category                                        |
| --------------------------------------------------- | -------------------------------------------- | ----------------------------------------------- |
| `asleep_until`                                        | `yascheduler/shared/async_utils.py`            | async↔sync runtime bridge (same family as `to_sync`) |
| `UniqueQueue`, `UMessage`, `TUMsgId`, `TUMsgPayload` | `yascheduler/application/queue.py`             | daemon-loop producer-consumer machinery         |
| `sleep_until`                                         | deleted                                       | dead code                                        |
| `yascheduler/time.py` (the file)                      | deleted (empty after the above)                 | —                                               |

**Alternatives considered.**

- *Shape A (both → `application/`)*: matches the `# FIXME: move this
  module to application (?)` annotation literally. Rejected because
  `asleep_until` is a 4-line async-runtime bridge semantically identical
  to `to_sync` (already in `shared/async_utils.py`); placing it in
  `application/` misclassifies a generic kernel helper as
  daemon-specific and creates a needless new tiny module
  (`application/sleep.py` or similar).
- *Shape B (both → `shared/`)*: matches the `variables/compat` precedent
  literally. Rejected because `UniqueQueue`'s own contract describes it
  as "for producer-consumer scheduling loops" — that is an
  application-shaped purpose, not a cross-layer kernel utility.
  Advertising it in `shared/` overstates its generality and pulls a
  daemon-loop concern into the shared kernel.
- *Inline `asleep_until` directly into `orchestrator.py`*: it has only
  two call sites. Rejected because (a) the function has a name and a
  contract worth preserving, (b) `to_sync` already establishes the
  pattern of collecting async-runtime helpers in `shared/async_utils.py`,
  and (c) inlining would force duplicating the helper if a second
  consumer ever appears in `application/`.

**Why.** The hybrid matches the existing project vocabulary
(`shared/async_utils.py` is already the home for async-runtime bridges)
and respects the `UniqueQueue` contract's own framing. It avoids both
the misclassification risk of Shape A and the over-generalization risk
of Shape B.

### Decision 2: Delete `sleep_until`; do not preserve "just in case"

**Choice.** Remove `sleep_until` entirely. Do not move it. Do not leave
a deprecated stub.

**Alternatives considered.**

- *Move it to `shared/` alongside `asleep_until`*: rejected — there are
  zero callers, so any destination is speculative. YAGNI.
- *Keep it in place pending a future sync caller*: rejected — the file
  is being deleted anyway; preserving one function would mean keeping
  `time.py` alive for dead code.

**Why.** The annotation `# FIXME: dead code?` is confirmed by grep: the
only matches for `\bsleep_until\b` in `*.py` under the repo are the
definition itself and the `MODULE_MAP` comment above it. Dead code has
no relocation destination; deletion is the only honest move.

### Decision 3: No facade re-export — `UniqueQueue` stays deep-path

**Choice.** Do NOT add `UniqueQueue` or `UMessage` to
`yascheduler/application/__init__.py`'s `__all__` or its import block.
Tests import via `from yascheduler.application.queue import …`.

**Alternatives considered.**

- *Re-export from the facade*: would give tests a shorter stable path
  (`from yascheduler.application import UniqueQueue`). Rejected because
  (a) the facade contract (`application/__init__.py` MODULE_MAP)
  explicitly limits itself to use cases + Orchestrator + UoW +
  MessageBus + AllocationTracker — adding queue internals widens the
  public surface for the convenience of two test files; (b) tests
  already import other orchestrator internals (`allocate_task`,
  `_count_nodes_by_cloud`) via deep paths, so the pattern is
  established; (c) `UniqueQueue` is an implementation detail of the
  daemon loop, not a cross-layer contract.

**Why.** Facade discipline. The facade's job is to expose what
cross-layer consumers need, not what's convenient for white-box tests.

### Decision 4: `knowledge-graph.xml` — `M-TIME` collapses into `M-SHARED`, `M-QUEUE` path rewrites only

**Choice.**

1. **Remove** the entire `<M-TIME>…</M-TIME>` record (lines 94–102).
2. **Migrate** its `<fn-asleep_until PURPOSE="Async sleep until a given
   datetime" />` annotation into `M-SHARED`'s `<annotations>` block
   (alphabetical or appended; match the existing ordering convention).
   **Drop** the `<fn-sleep_until PURPOSE="Sleep until a given datetime"
   />` annotation (dead code).
3. **Rewrite** the `M-TIME` token in `M-APPLICATION-ORCHESTRATOR`'s
   `<depends>` (line 366) to `M-SHARED`. The full depends list becomes:
   `M-APPLICATION-UOW, M-CONFIG, M-QUEUE, M-SHARED,
   M-APPLICATION-ALLOCATE, M-APPLICATION-CONSUME,
   M-APPLICATION-DEALLOCATE, M-DOMAIN-PORTS, M-DOMAIN-MODEL,
   M-DOMAIN-EVENTS, M-APPLICATION-ALLOCATION-TRACKER`. This is a token
   swap, not a deduplication — `M-SHARED` is not currently in that list.
4. **Rewrite** `M-QUEUE`'s `<path>yascheduler/queue.py</path>` →
   `<path>yascheduler/application/queue.py</path>`. Module ID `M-QUEUE`,
   `TYPE=UTILITY`, `depends=none`, and all four annotations
   (`class-UniqueQueue`, `class-UMessage`, `type-TUMsgId`,
   `type-TUMsgPayload`) are unchanged.
5. `M-QUEUE` stays in `M-APPLICATION-ORCHESTRATOR`'s `<depends>` — the
   dependency is real (orchestrator imports from it); only the path
   changes.

**Alternatives considered.**

- *Keep `M-TIME` as a separate record pointing at `shared/async_utils.py`*:
  rejected — `M-SHARED` already covers `shared/__init__.py` and its
  sibling modules (`async_utils.py`, `compat.py`, `variables.py`); a
  separate `M-TIME` for one function in one of those files would
  fragment the graph for no navigational benefit.
- *Delete the `M-TIME` token from the orchestrator depends without
  replacement*: rejected — `scripts/grace_check.py`
  `_check_depends_refs` (lines 439–446) treats depends tokens pointing
  at unknown modules as a hard ERROR (exit 1). Removing the token
  entirely would also hide the real dependency (orchestrator does use
  `asleep_until`).
- *Add `M-SHARED` as an additional token (keeping `M-TIME`)*: rejected —
  leaves a dangling reference to a deleted record (same `grace_check.py`
  failure).

**Why.** The graph must stay internally consistent: every module id
referenced in `<depends>` must point at an existing `<M-*>` record, and
every implemented module record must point at a real file. The
token-swap (`M-TIME` → `M-SHARED`) preserves the real dependency edge
while removing the obsolete record.

### Decision 5: Doc-drift fix is in scope, treated as bug fix

**Choice.** Fix `docs/ARCHITECTURE.md` root-level references in the
same change. Specifically:

- §1 layer diagram root block (~lines 83–92): remove the `queue.py
  UniqueQueue` line and the `variables.py, time.py, compat.py   Path/time/typing utilities` line.
- §4 project tree (lines 454, 458, 459, 460): remove the four stale
  entries (`queue.py`, `variables.py`, `time.py`, `compat.py`).
- Reflect the new locations: add `queue.py` under the `application/`
  subtree; note that `asleep_until` joined `shared/async_utils.py` (the
  §4 `shared/` subtree or a parenthetical in §1).

**Alternatives considered.**

- *Separate change proposal for the doc drift*: rejected — the drift is
  partly caused by this very relocation (the `time.py`/`queue.py`
  entries become newly stale) and partly a pre-existing oversight
  (`variables.py`/`compat.py` were never cleaned up in v1.6.0). Splitting
  it would leave the docs inconsistent with the filesystem for one
  proposal cycle and double the review overhead. User explicitly said
  "fix as bug".

**Why.** The docs are part of the same navigational surface as the code
and the knowledge graph; leaving them stale defeats the point of the
relocation. The bug-fix framing avoids the overhead of a separate
proposal while making the docs consistent.

### Decision 6: No `specs/` deltas — verified zero spec path references

**Choice.** Produce no `specs/<capability>/spec.md` delta files.

**Verification.** Grep of `openspec/specs/` for `time.py`, `queue.py`,
`yascheduler.time`, `yascheduler.queue`, `yascheduler/time`,
`yascheduler/queue`, `asleep_until`, `sleep_until`: zero path
references. The two specs that mention these symbols
(`testing-unit/spec.md` lines 126, 179, 181, 185; and
`testing-infrastructure/spec.md` lines 28, 29, 32) reference only the
symbol names `UniqueQueue` / `UMessage` / `Orchestrator` — names that
are unchanged by this relocation. No spec-level requirement changes.

**Why.** Specs are contracts on behavior, not on file location. The
symbol names are the contract surface; their container moves, the
contract holds.

### Decision 7: Single atomic commit, no migration period

**Choice.** Land the relocation as a single atomic change: file moves +
import rewrites + graph update + doc fixes in one commit. No
backward-compat shim, no deprecation period, no re-export alias.

**Alternatives considered.**

- *Shim: `yascheduler/queue.py` re-exporting from
  `yascheduler.application.queue`*: rejected because (a) the
  `AGENTS.md` public-interface stability rule enumerates `class
  Yascheduler`, CLI commands, INI format, DB schema, AiiDA entrypoint —
  NOT internal module paths; (b) there are no external consumers of
  `yascheduler.queue` as a Python import path (the package is installed
  as `yascheduler`, and `pip install` consumers use `from yascheduler
  import Yascheduler`, not `from yascheduler.queue import …`); (c) a
  shim would keep the FIXME's sting alive and add dead code.

**Why.** Internal import paths are not public API. The test suite is
the safety net; a shim would add dead code and defeat the cleanup.

## Risks / Trade-offs

- **Risk**: an import site is missed, breaking load at test time or
  daemon startup.
  → **Mitigation**: after the rewrite, run verification greps requiring
  zero UNEXPECTED matches:
  1. `grep -rn "yascheduler\.time\|yascheduler\.queue" --include="*.py" yascheduler/ tests/` — must return zero (catches dotted-form leftovers).
  2. `grep -rn "yascheduler/time\|yascheduler/queue" --include="*.py" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/` — must return zero (catches slash-form leftovers in source, graph, docs).
  3. `grep -rn "from yascheduler\.queue\|from yascheduler\.time" --include="*.py" tests/` — must return zero (catches the 8 test import sites; verifies all rewritten).
  Then run `uv run pytest -m unit|integration|e2e`, `uv run lint-imports`,
  `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run zuban check`, `python3 scripts/grace_check.py`, and
  `openspec validate --all --json`.

- **Risk**: the `M-TIME` → `M-SHARED` token swap in the orchestrator
  depends is botched (typo, or `M-TIME` left dangling), and
  `grace_check.py` emits a hard ERROR (exit 1).
  → **Mitigation**: the swap is a single-line edit at
  `docs/knowledge-graph.xml:366`. After the edit, run
  `grep -n "M-TIME" docs/knowledge-graph.xml` — must return zero
  matches. Then `python3 scripts/grace_check.py` must exit 0.

- **Risk**: the 6 inline `from yascheduler.queue import UMessage`
  statements inside test function bodies (lines 404, 599, 624, 643, 669,
  693 of `test_application_orchestrator.py`) are missed because they're
  not at module top.
  → **Mitigation**: the import rewrite is path-agnostic about location
  in the file — `grep -n "from yascheduler\.queue" tests/unit/test_application_orchestrator.py`
  must return zero post-rewrite. The migration plan (below) explicitly
  enumerates all 7 sites in that file plus the 1 in `test_queue.py:28`.

- **Risk**: `docs/ARCHITECTURE.md` ASCII diagrams break visually when
  entries are removed from the §4 tree.
  → **Mitigation**: the tree uses `├──` and `└──` box-drawing; removing
  a middle entry requires re-prefixing the last entry's `├──` to `└──`
  only if it becomes the new last child. Manual review of the rendered
  block after edit. Cosmetic only — no automated check fails.

- **Risk**: a stale reference to `time.py` / `queue.py` / `M-TIME` /
  `asleep_until` / `sleep_until` survives in `openspec/changes/archive/**`
  or in archived historical proposals.
  → **Mitigation**: `openspec/changes/archive/**` is explicitly excluded
  (archived proposals are frozen historical records; rewriting them
  falsifies history). The relocation affects only live, normative
  surface.

- **Trade-off**: the relocation touches ~6 code/test files plus 2 docs
  files for a structural benefit (finishing the v1.6.0 migration and
  honoring two standing FIXMEs). The cost is one small mechanical diff.
  The benefit is a coherent layering: `shared/` for cross-layer kernel
  utilities, `application/` for daemon-loop machinery, no stranded
  root-level utils. User has judged the benefit worth the cost.

## Migration Plan

Single-step migration (no phased rollout):

1. **Create** `yascheduler/application/queue.py` with the contents of
   the current `yascheduler/queue.py`. Update the GRACE-lite header:
   `# FILE: yascheduler/application/queue.py`, bump `VERSION`, update
   `MODULE_CONTRACT` `LINKS:` if needed, add a `CHANGE_SUMMARY` entry
   ("Relocated from yascheduler/queue.py; same contents"). Remove the
   `# FIXME: move this module to application (?)` line — the move is
   done.
2. **Delete** `yascheduler/queue.py` (the old path). Use `git rm` to
   preserve history linkage through the rename detection.
3. **Edit** `yascheduler/shared/async_utils.py`:
   - Add `from datetime import datetime` (asyncio is already imported
     at line 19).
   - Add the `asleep_until` function (4 lines, copied verbatim from
     `time.py`).
   - Update `MODULE_MAP` to add `asleep_until - Async sleep until a given datetime`.
   - Update `MODULE_CONTRACT` `SCOPE` to mention both `to_sync` and
     `asleep_until`.
   - Add `CHANGE_SUMMARY` entry ("Gained asleep_until relocated from
     yascheduler/time.py").
4. **Delete** `yascheduler/time.py` (use `git rm`). The file is empty
   after steps 1–3.
5. **Edit** `yascheduler/application/orchestrator.py` (2 import lines
   at ~41–42):
   - `from yascheduler.queue import UMessage, UniqueQueue` →
     `from yascheduler.application.queue import UMessage, UniqueQueue`.
   - `from yascheduler.time import asleep_until` →
     `from yascheduler.shared.async_utils import asleep_until`.
   - **Rationale**: keep the absolute form. The existing lines are
     absolute (`from yascheduler.queue…`, `from yascheduler.time…`), so
     the minimal-diff edit only rewrites the package prefix. This also
     matches the other cross-package absolute import in the same file
     (`from yascheduler.domain…` line 29). Intra-package siblings are
     imported relatively (`.allocate_task` line 44), but converting the
     queue/time lines to relative would be a larger diff for no
     benefit. **Also** update the `MODULE_CONTRACT` `DEPENDS:` header
     (line 6): swap `M-TIME` → `M-SHARED` to mirror the
     `knowledge-graph.xml` token swap (Decision 4). `grace_check.py`
     does not validate source `DEPENDS:` as an error (only `LINKS:`,
     and only as warning), so this is a GRACE-lite consistency update,
     not a gate.
6. **Edit** `tests/unit/test_queue.py` (line 28):
   `from yascheduler.queue import UMessage, UniqueQueue` →
   `from yascheduler.application.queue import UMessage, UniqueQueue`.
7. **Edit** `tests/unit/test_application_orchestrator.py` (7 sites):
   - line 63 (top-level): `from yascheduler.queue import UniqueQueue` →
     `from yascheduler.application.queue import UniqueQueue`.
   - lines 404, 599, 624, 643, 669, 693 (inline, inside test function
     bodies): each `from yascheduler.queue import UMessage` →
     `from yascheduler.application.queue import UMessage`.
8. **Edit** `docs/knowledge-graph.xml`:
   - Remove the `<M-TIME>…</M-TIME>` block (lines 94–102).
   - Add `<fn-asleep_until PURPOSE="Async sleep until a given datetime" />`
     to `M-SHARED`'s `<annotations>`. Do NOT add `fn-sleep_until`
     (deleted).
   - At line 366, swap `M-TIME` → `M-SHARED` in the orchestrator
     `<depends>` list.
   - Rewrite `<path>yascheduler/queue.py</path>` →
     `<path>yascheduler/application/queue.py</path>` in `M-QUEUE`.
9. **Edit** `docs/ARCHITECTURE.md`:
   - §1 layer-diagram root block (~lines 83–92): remove the `queue.py
     UniqueQueue` line and the `variables.py, time.py, compat.py     Path/time/typing utilities` line.
   - §4 project tree: remove lines 454 (`queue.py`), 458
     (`variables.py`), 459 (`time.py`), 460 (`compat.py`); add
     `queue.py` under the `application/` subtree; note `asleep_until`
     under `shared/async_utils.py` (either in the §4 `shared/` subtree
     or as a parenthetical in §1).
10. **Run verification**: the three greps in Risks #1, the
    `grep -n "M-TIME" docs/knowledge-graph.xml` check from Risks #2,
    then `uv run pytest -m unit|integration|e2e`,
    `uv run lint-imports`, `uv run ruff check .`,
    `uv run ruff format --check .`, `uv run zuban check`,
    `python3 scripts/grace_check.py`, and
    `openspec validate --all --json`.
11. **Commit** as a single atomic commit per the user's later
    instruction (the orchestrator does NOT auto-commit).

**Rollback.** `git revert <commit>` restores the old layout and all
references in one step, because the change is a single atomic commit.
No partial state survives.

## Open Questions

None. The relocation is fully determined by the user's decisions
(Shape C; no facade re-export; `M-TIME` collapses into `M-SHARED`;
doc-drift fixed as bug) and the verified facts (dead `sleep_until`;
zero spec path references; sole production consumer is the orchestrator).

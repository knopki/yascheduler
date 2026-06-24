## Why

`yascheduler/time.py` and `yascheduler/queue.py` sit at the package root but
are consumed **only** by `yascheduler/application/orchestrator.py` (plus two
unit-test files). Both carry the standing FIXME `# FIXME: move this module to
application (?)`. They are the last two root-level utilities left after
`variables.py` and `compat.py` were relocated to `shared/` in v1.6.0 — the
root is mid-migration and these two were never boarded. Separately,
`docs/ARCHITECTURE.md` still lists `variables.py`, `compat.py`, `time.py`,
and `queue.py` at the root, contradicting the filesystem (doc drift).

This change finishes the relocation by **semantic category**, drops one
confirmed dead symbol, and fixes the doc drift in the same pass.

## What Changes

- **Relocate** `UniqueQueue`, `UMessage`, `TUMsgId`, `TUMsgPayload` from
  `yascheduler/queue.py` → **new file** `yascheduler/application/queue.py`.
  These are daemon-loop machinery (the contract calls them "for
  producer-consumer scheduling loops"); the sole production consumer is
  `orchestrator.py`.
- **Merge** `asleep_until` from `yascheduler/time.py` into the **existing**
  `yascheduler/shared/async_utils.py` (same family as `to_sync` — both are
  async↔sync runtime bridges). The MODULE_MAP of `async_utils.py` gains the
  `asleep_until` entry.
- **Delete** `sleep_until` (sync) — confirmed dead code (zero callers in
  `yascheduler/` or `tests/`; confirms the `# FIXME: dead code?` annotation).
- **Delete** the now-empty `yascheduler/time.py` file entirely.
- **Update imports** in exactly two production sites
  (`yascheduler/application/orchestrator.py` lines ~41–42) and two test
  files (`tests/unit/test_queue.py`, `tests/unit/test_application_orchestrator.py`).
- **NOT re-export** `UniqueQueue`/`UMessage` from the
  `yascheduler/application/__init__.py` facade — they are internal to the
  orchestrator; tests reach them via the deep path
  `from yascheduler.application.queue import …`, consistent with how tests
  already import other orchestrator internals (`allocate_task`,
  `_count_nodes_by_cloud`).
- **Update** `docs/knowledge-graph.xml`:
  - remove the `M-TIME` module record entirely; migrate its `fn-asleep_until`
    annotation into `M-SHARED`'s `<annotations>`; drop the `fn-sleep_until`
    annotation (dead code);
  - **replace the dangling `M-TIME` token** in
    `M-APPLICATION-ORCHESTRATOR`'s `<depends>` (line 366) with `M-SHARED`
    (the new home of `asleep_until`). `M-TIME` is currently in that depends
    list; deleting the module record without updating this reference makes
    `scripts/grace_check.py`'s `_check_depends_refs` emit a hard ERROR
    (exit 1) on an unknown module id. `M-SHARED` is not currently in that
    depends list, so this is a token swap, not a deduplication;
  - rewrite `M-QUEUE`'s `<path>` from `yascheduler/queue.py` →
    `yascheduler/application/queue.py`; module ID, TYPE, depends, and other
    annotations unchanged.
- **Fix doc drift** in `docs/ARCHITECTURE.md` (treated as a bug fix in the
  same change, not a separate proposal): remove `queue.py`, `time.py`, and
  the stale `variables.py, time.py, compat.py` line from the root-level
  blocks — §1 layer diagram (~lines 83–92) and §4 project tree (lines 454
  `queue.py`, 458 `variables.py`, 459 `time.py`, 460 `compat.py`, all four
  stale). Reflect `queue.py` under `application/` and `asleep_until` joining
  `shared/async_utils.py`.
- **Update GRACE-lite** `# FILE:` headers, `MODULE_CONTRACT`, `MODULE_MAP`,
  and `CHANGE_SUMMARY` annotations inside the moved/merged code to reflect
  new paths.

Non-goals (explicitly out of scope):

- No public API change of any kind: `class Yascheduler`, CLI command names,
  INI format, DB schema, AiiDA entrypoint key — all preserved. The
  `yascheduler.queue` / `yascheduler.time` import paths are NOT part of the
  public surface enumerated in `AGENTS.md`.
- No backward-compatibility shim, no deprecation period, no re-export alias
  at the old paths. Internal relocations do not get shims.
- No rename of the symbols themselves — `UniqueQueue`, `UMessage`,
  `asleep_until` keep their names; only their containing module changes.
- No change to test logic, fixtures, or assertions — only import paths in
  the two affected test files.
- No relocation of `tests/unit/test_queue.py` itself — the flat
  `tests/unit/` layout has no per-layer subdirectories and no precedent for
  one.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. Verified by grep of `openspec/specs/` for `time.py`, `queue.py`,
`yascheduler.time`, `yascheduler.queue`, `yascheduler/time`,
`yascheduler/queue`, `asleep_until`, `sleep_until`: **zero path
references**. The two specs that mention these symbols
(`testing-unit/spec.md`, `testing-infrastructure/spec.md`) reference the
symbol names `UniqueQueue` / `UMessage` only — names that are unchanged by
this relocation. No spec-level requirement changes; therefore no `specs/`
delta files are produced.

## Impact

- **Code**:
  - 1 new file: `yascheduler/application/queue.py` (contents =
    current `yascheduler/queue.py` minus the FIXME header, plus updated
    `# FILE:` / `MODULE_CONTRACT` / `CHANGE_SUMMARY` annotations).
  - 1 deleted file: `yascheduler/time.py` (empty after `sleep_until`
    removal and `asleep_until` merge).
  - 1 deleted file-equivalent: `yascheduler/queue.py` (content moves to
    `application/queue.py`; the old path disappears).
  - 1 modified file: `yascheduler/shared/async_utils.py` (gains the
    `asleep_until` function; `import asyncio` is already present at line 19,
    so only `from datetime import datetime` is new; plus MODULE_MAP /
    MODULE_CONTRACT / CHANGE_SUMMARY updates).
  - 1 modified file: `yascheduler/application/orchestrator.py`
    (2 import lines: `from yascheduler.queue…` →
    `from yascheduler.application.queue…` and `from yascheduler.time import
    asleep_until` → `from yascheduler.shared.async_utils import
    asleep_until`).
- **Tests**: 2 modified files. `tests/unit/test_queue.py` — 1 import site
  (line 28). `tests/unit/test_application_orchestrator.py` — **7 import
  sites** total (1 top-level at line 63 + 6 inline imports inside test
  function bodies at lines 404, 599, 624, 643, 669, 693). All rewrite
  `from yascheduler.queue…` → `from yascheduler.application.queue…`; no test
  bodies, fixtures, or assertions change.
- **Docs**:
  - `docs/knowledge-graph.xml` — remove `M-TIME` record; migrate
    `fn-asleep_until` annotation to `M-SHARED`; rewrite `M-QUEUE` `<path>`.
  - `docs/ARCHITECTURE.md` — fix root-level doc drift (remove stale
    `variables.py`, `compat.py`, `time.py`, `queue.py` entries; reflect
    new locations).
- **GRACE-lite anchors**: `# FILE:` / `MODULE_CONTRACT` / `MODULE_MAP` /
  `CHANGE_SUMMARY` inside `application/queue.py` (new) and
  `shared/async_utils.py` (modified) rewritten for new paths.
- **Public API**: zero change.
- **Dependencies**: none added, none removed.
- **Verification**: `uv run pytest -m unit|integration|e2e`,
  `uv run lint-imports`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run zuban check`,
  `python3 scripts/grace_check.py`, and
  `openspec validate --all --json` must all pass after the relocation.

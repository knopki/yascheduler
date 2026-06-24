## 1. Code relocation (production)

- [x] 1.1 Create `yascheduler/application/queue.py` with the verbatim contents of `yascheduler/queue.py`; update the GRACE-lite header (`# FILE:` path, bump `VERSION`, `MODULE_CONTRACT`/`MODULE_MAP`/`LINKS:` if needed, add `CHANGE_SUMMARY` entry "Relocated from yascheduler/queue.py; same contents"); remove the `# FIXME: move this module to application (?)` line (the move is done).
- [x] 1.2 `git rm yascheduler/queue.py` (preserves rename detection history).
- [x] 1.3 Edit `yascheduler/shared/async_utils.py`: add `from datetime import datetime` import (`asyncio` already imported at line 19); add the `asleep_until` function (4 lines, copied verbatim from `time.py`); update `MODULE_MAP` to add `asleep_until - Async sleep until a given datetime`; widen `MODULE_CONTRACT` `SCOPE` to mention both `to_sync` and `asleep_until`; add `CHANGE_SUMMARY` entry "Gained asleep_until relocated from yascheduler/time.py".
- [x] 1.4 `git rm yascheduler/time.py` (file is empty after 1.3; `sleep_until` deleted as confirmed dead code, `asleep_until` relocated).

## 2. Import rewrites (production + tests)

- [x] 2.1 Edit `yascheduler/application/orchestrator.py` line ~41: `from yascheduler.queue import UMessage, UniqueQueue` → `from yascheduler.application.queue import UMessage, UniqueQueue`.
- [x] 2.2 Edit `yascheduler/application/orchestrator.py` line ~42: `from yascheduler.time import asleep_until` → `from yascheduler.shared.async_utils import asleep_until`.
- [x] 2.3 Edit `yascheduler/application/orchestrator.py` line 6 `MODULE_CONTRACT` `DEPENDS:`: swap `M-TIME` → `M-SHARED` (mirrors the `knowledge-graph.xml` token swap; GRACE-lite consistency — not a `grace_check.py` gate, only `LINKS:` is validated and only as warning).
- [x] 2.4 Edit `tests/unit/test_queue.py` line 28: `from yascheduler.queue import UMessage, UniqueQueue` → `from yascheduler.application.queue import UMessage, UniqueQueue`.
- [x] 2.5 Edit `tests/unit/test_application_orchestrator.py` — rewrite all 7 import sites: line 63 (top-level `UniqueQueue`) and lines 404, 599, 624, 643, 669, 693 (inline `UMessage` inside test function bodies) from `from yascheduler.queue import …` → `from yascheduler.application.queue import …`.

## 3. Knowledge graph

- [x] 3.1 Remove the entire `<M-TIME>…</M-TIME>` record from `docs/knowledge-graph.xml` (lines 94–102).
- [x] 3.2 Add `<fn-asleep_until PURPOSE="Async sleep until a given datetime" />` to `M-SHARED`'s `<annotations>` block. Do NOT add `fn-sleep_until` (deleted dead code).
- [x] 3.3 Edit `docs/knowledge-graph.xml` line 366: in `M-APPLICATION-ORCHESTRATOR`'s `<depends>`, swap the `M-TIME` token → `M-SHARED` (token swap, not dedupe — `M-SHARED` is not currently in that list).
- [x] 3.4 Edit `M-QUEUE`'s `<path>`: `yascheduler/queue.py` → `yascheduler/application/queue.py`. Leave `M-QUEUE` id, `TYPE=UTILITY`, `depends=none`, and all four annotations unchanged.

## 4. Architecture doc (bug-fix drift)

- [x] 4.1 Edit `docs/ARCHITECTURE.md` §1 layer-diagram root block (~lines 83–92): remove the `queue.py   UniqueQueue` line and the `variables.py, time.py, compat.py   Path/time/typing utilities` line.
- [x] 4.2 Edit `docs/ARCHITECTURE.md` §4 project tree: remove lines 454 (`queue.py`), 458 (`variables.py`), 459 (`time.py`), 460 (`compat.py`); fix the `├──`/`└──` box-drawing prefixes if a middle entry removal makes the last child change.
- [x] 4.3 Edit `docs/ARCHITECTURE.md`: reflect new locations — add `queue.py` under the `application/` subtree; add a note that `asleep_until` joined `shared/async_utils.py` (either in the §4 `shared/` subtree or as a §1 parenthetical).

## 5. Verification

- [x] 5.1 Run `grep -rn "yascheduler\.time\|yascheduler\.queue" --include="*.py" yascheduler/ tests/` — must return zero matches.
- [x] 5.2 Run `grep -rn "yascheduler/time\|yascheduler/queue" --include="*.py" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/` — must return zero matches. *(Satisfied by intent: 2 matches are CHANGE_SUMMARY provenance comments mandated by tasks 1.1 & 1.3, not live path references; all live references are zero — confirmed by 5.1, 5.3, 5.4.)*
- [x] 5.3 Run `grep -rn "from yascheduler\.queue\|from yascheduler\.time" --include="*.py" tests/` — must return zero matches (all 8 test import sites rewritten).
- [x] 5.4 Run `grep -n "M-TIME" docs/knowledge-graph.xml` — must return zero matches.
- [x] 5.5 Run `uv run pytest -m unit` — must pass.
- [x] 5.6 Run `uv run pytest -m integration` — must pass.
- [x] 5.7 Run `uv run pytest -m e2e` — must pass.
- [x] 5.8 Run `uv run lint-imports` — must pass.
- [x] 5.9 Run `uv run ruff check .` — must pass.
- [x] 5.10 Run `uv run ruff format --check .` — must pass.
- [x] 5.11 Run `uv run zuban check` — must pass.
- [x] 5.12 Run `python3 scripts/grace_check.py` — must exit 0.
- [x] 5.13 Run `openspec validate --all --json` — must pass. *(Skipped per user decision: zero-delta change is rejected by the validator by design — Decision 6 vs. task 5.13 contradiction. All 29 specs validate; only this change is flagged.)*

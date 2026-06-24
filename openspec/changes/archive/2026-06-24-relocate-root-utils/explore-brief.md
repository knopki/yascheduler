# Explore Brief — relocate-root-utils

## Problem

`yascheduler/time.py` and `yascheduler/queue.py` sit at the package root but
are consumed ONLY by `yascheduler/application/orchestrator.py` (plus 2 unit
test files). Both carry the FIXME `# FIXME: move this module to application (?)`.
They are the last two root-level utilities after `variables.py` and
`compat.py` were relocated to `shared/` in v1.6.0. Additionally,
`docs/ARCHITECTURE.md` still lists `variables.py`, `compat.py`, `time.py`,
`queue.py` at the root — doc drift that should be corrected alongside.

## Rejected alternatives

- **Shape A (all → `application/`)**: matches the FIXME literally, but
  misclassifies `asleep_until` — a 4-line async-runtime bridge that is
  semantically the same family as `to_sync` (already in `shared/async_utils.py`).
  Polluting `application/` with a generic sleep helper blurs the layer.
- **Shape B (all → `shared/`)**: matches the `variables/compat` precedent
  literally, but `UniqueQueue`/`UMessage` are named in their own contract as
  "for producer-consumer scheduling loops" — that is application-shaped
  machinery, not kernel utility. Putting them in `shared/` advertises a
  cross-layer generality they do not have.

## Final approach — Shape C (hybrid, relocate by semantic category)

| Symbol                            | Current                       | Destination                                  | Rationale                                                       |
| --------------------------------- | ----------------------------- | -------------------------------------------- | --------------------------------------------------------------- |
| `sleep_until` (sync)                | `yascheduler/time.py`           | **DELETED** (dead code, 0 callers)              | Confirms `# FIXME: dead code?`                                  |
| `asleep_until` (async)              | `yascheduler/time.py`           | `yascheduler/shared/async_utils.py`            | Same family as `to_sync` (async↔sync runtime bridges)            |
| `time.py` (file)                    | `yascheduler/time.py`           | **DELETED** (empty after symbol relocation)     | Module disappears; `M-TIME` collapses into `M-SHARED`             |
| `UniqueQueue`, `UMessage`, `TUMsgId`, `TUMsgPayload` | `yascheduler/queue.py` | `yascheduler/application/queue.py`             | Daemon-loop machinery; only consumer is `orchestrator.py`         |
| `tests/unit/test_queue.py` (file)   | `tests/unit/test_queue.py`      | stays (flat test layout); only import path edits | No `tests/unit/application/` precedent                          |

## Cross-module data flows (post-relocation)

```
yascheduler/shared/async_utils.py
  └─ asleep_until  ←─ imported by ── yascheduler/application/orchestrator.py (lines ~191, ~457)

yascheduler/application/queue.py
  └─ UniqueQueue, UMessage  ←─ imported by ── yascheduler/application/orchestrator.py
                            ←─ imported by ── tests/unit/test_queue.py
                            ←─ imported by ── tests/unit/test_application_orchestrator.py
```

No other production code imports either module. Verified by grep across
`yascheduler/` and `tests/` — the only other `import time` / `import queue`
hits are stdlib.

## Facade policy (DECIDED)

`UniqueQueue`/`UMessage` are **NOT** re-exported from
`yascheduler/application/__init__.py`. The facade stays narrow (use cases +
Orchestrator + AbstractUnitOfWork + MessageBus + AllocationTracker). Tests
import via deep path `from yascheduler.application.queue import ...`, matching
how tests already import other orchestrator internals
(`allocate_task`, `_count_nodes_by_cloud`, etc.).

## Spec impact (VERIFIED — none)

Grep of `openspec/specs/` for `time.py`, `queue.py`, `yascheduler.time`,
`yascheduler.queue`, `yascheduler/time`, `yascheduler/queue`, `asleep_until`,
`sleep_until`: **zero path references**. Specs reference symbol names only
(`UniqueQueue`, `UMessage`) — those names are unchanged. → No `specs/` delta
files needed. Capabilities section (New + Modified) is empty.

## Doc/Grape impact

- `docs/knowledge-graph.xml`:
  - `M-TIME` removed; its `fn-asleep_until` annotation migrates into
    `M-SHARED` annotations. `fn-sleep_until` annotation dropped (dead code).
  - `M-QUEUE` `<path>` rewritten `yascheduler/queue.py` →
    `yascheduler/application/queue.py`. ID, TYPE, depends, other annotations
    unchanged.
- `docs/ARCHITECTURE.md`:
  - §1 layer diagram root block (lines ~83–92): remove `queue.py`,
    `time.py`, and the stale `variables.py, time.py, compat.py` line.
  - §4 project tree (lines ~454, 459): remove `queue.py` and `time.py`
    entries; `variables.py`/`compat.py` already absent from filesystem
    (drift). Add `queue.py` under `application/` and note `asleep_until`
    joined `shared/async_utils.py`.
- GRACE-lite source headers inside the moved/merged code: update `# FILE:`
  paths, `MODULE_CONTRACT`/`MODULE_MAP`/`CHANGE_SUMMARY` for the new
  location; `shared/async_utils.py` gains `asleep_until` in its MODULE_MAP.

## Resolved open questions

1. Shape: **C (hybrid)** — user decision.
2. Proposal: **yes** — user decision (consistency with
   `rename-adapters-to-infra`).
3. Facade re-export: **no** — internal symbols stay deep-path.
4. `M-TIME` fate: **collapse into `M-SHARED`** — user decision.
5. Doc-drift (`variables.py`/`compat.py` in ARCHITECTURE.md): **fix as bug**
   in the same change — user decision.

## Unresolved open questions

None.

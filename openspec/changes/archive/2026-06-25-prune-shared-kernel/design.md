## Context

`yascheduler.shared` was carved out by the archived `2026-06-23-shared-kernel-extraction` change, which moved three modules into a new bottom layer: `compat.py` (typing shims), `variables.py` (path constants), and `async_utils.py` (`to_sync` + `asleep_until`). The same commit (`ee2746e`) introduced the `package-facades` spec whitelisting "typing shims, pure runtime helpers, or process-global constants" as the permitted `shared` content and left a `# FIXME: is this really shared kernel? decide` marker in `variables.py`. Two later archived changes (`add-entrypoints-layer`, `consolidate-daemon-entrypoints`) migrated every CLI consumer of `to_sync` to `asyncio.run`, collapsing `to_sync` to a single consumer (`entrypoints/client.py`) and leaving the path constants with consumers only in the `entrypoints` layer.

Current state of `yascheduler/shared/` (3 modules, 6 public symbols):

- `compat.py` — `Self`, `ParamSpec`, `Unpack`. `Self` is consumed by `config/{cloud,remote,engine_repository}.py` and `domain/model.py` (TYPE_CHECKING) — genuinely cross-layer (≥2 architectural layers). `Unpack` is consumed by `domain/model.py`. `ParamSpec` is consumed **only** by `shared/async_utils.py` (for `to_sync`'s signature).
- `async_utils.py` — `to_sync` (single production consumer: `entrypoints/client.py`, 2 call sites; the 6 CLI consumers were removed by `consolidate-daemon-entrypoints`); `asleep_until` (single production consumer: `application/orchestrator.py`, 2 call sites).
- `variables.py` — `CONFIG_FILE`, `LOG_FILE`, `PID_FILE` (all production consumers in `entrypoints`: `__init__.py` re-export, `client.py`, `cli/args.py`, `cli/init.py`, `cli/daemon_sysv.py`). Carries the unresolved FIXME at line 21.

The `package-facades` spec defines `shared` negatively ("no business logic, domain types, or I/O" / "only typing shims, pure runtime helpers, or process-global constants") and pins (frozen): path-constant re-exports to `yascheduler.shared.variables` (L531-538, L584-586), `to_sync` to `yascheduler.shared.async_utils` (L559-562, L588-590), and `Self`+`ParamSpec` importability from `yascheduler.shared` (L592-594). The negative definition cannot distinguish a true cross-layer kernel from a misplaced leaf utility — it accepted the retrofit.

`yascheduler.entrypoints` is already the top layer in the `layers` contract (`pyproject.toml`), so a module moved there is automatically subject to R3 (its imports flow `entrypoints → infra → application → domain → shared`). The `forbidden` contract `shared → config` stays in force after this change because `config` still imports `Self` from `shared` (the cycle risk remains real).

## Goals / Non-Goals

**Goals:**
- Prune `yascheduler.shared` to its honest shared-kernel content: `compat.py` with `Self` and `Unpack` (the only symbols consumed by ≥2 architectural layers).
- Relocate `variables.py` to `yascheduler/entrypoints/paths.py` (its consumers are all in the `entrypoints` layer).
- Inline `to_sync` into `yascheduler/entrypoints/client.py` and `asleep_until` into `yascheduler/application/orchestrator.py` as private helpers (single consumers each); delete `shared/async_utils.py`.
- Remove `ParamSpec` from `compat.py` (dead after the `to_sync` inline).
- Rewrite the `package-facades` shared-kernel definition from negative to positive ("typing shims consumed by ≥2 architectural layers; a module whose consumers are in a single layer belongs to that layer, not to `shared`"), keeping the "no SSH/DB/HTTP/cloud I/O" clause as a second guardrail.
- Preserve the public API surface: `from yascheduler import CONFIG_FILE, LOG_FILE, PID_FILE` continues to resolve (now via `yascheduler.entrypoints.paths` instead of `yascheduler.shared.variables`).
- Update the GRACE knowledge graph to reflect the new structure.

**Non-Goals:**
- No split of `compat.py` by symbol. `Self` and `Unpack` are both typing shims for older Python versions and co-locate naturally; splitting would add a module for no payoff.
- No compat shim at `yascheduler/shared/variables.py` or `yascheduler/shared/async_utils.py`. The deep paths `from yascheduler.shared import {to_sync, asleep_until, ParamSpec}` are internal API; no `[project.scripts]` entry references them, and no external consumer is known. Adding shims violates YAGNI and reverses the pruning.
- No change to the `layers` contract in `pyproject.toml`. `yascheduler.shared` remains the 5th (bottom) layer, now containing only `compat.py`. The `forbidden` contract `shared → config` remains (cycle risk is still real while `config` imports `Self` from `shared`).
- No change to `yascheduler/client.py` (the public-API compat shim for `Yascheduler`). It is unaffected.
- No rename of `tests/unit/test_*.py` files. Filenames are neutral; only import paths inside change.
- No change to the `yascheduler.client` query-method public contract (L596-659). Unaffected.
- No rewrite of `compat.py`'s remaining `Self`/`Unpack` version branches. They stay as-is.

## Decisions

### D1 — `variables.py` → `entrypoints/paths.py` (flat relocation)

**Choice:** `git mv yascheduler/shared/variables.py yascheduler/entrypoints/paths.py`. Update `# FILE:` header, `MODULE_CONTRACT` (`LINKS: M-ENTRYPOINTS-PATHS`), `MODULE_MAP`, `CHANGE_SUMMARY`. Drop the `# FIXME: is this really shared kernel? decide` line — the question is resolved by this change.

**Rationale:** Every production consumer of `CONFIG_FILE`/`LOG_FILE`/`PID_FILE` is in the `entrypoints` layer (`__init__.py` re-export, `client.py`, `cli/args.py`, `cli/init.py`, `cli/daemon_sysv.py`). Zero consumers in domain/application/infra/config. A module whose consumers are in a single layer belongs to that layer. `paths.py` is a flat resident of `entrypoints` (sibling to `client.py`, `di.py`, `aiida_plugin.py`), automatically subject to R3 — its imports (only `os.getenv`) flow trivially downward.

**Alternatives considered:**
- `entrypoints/cli/paths.py` — rejected. `client.py` (a flat resident, not a CLI module) consumes the constants; nesting under `cli/` would force `client.py` to import cross-subpackage, cementing "client is CLI-over-async" (the same anti-pattern `relocate-di-to-entrypoints` rejected).
- `entrypoints/defaults.py` — rejected. "defaults" is less precise than "paths"; these are file-path constants, not general defaults.
- Keep in `shared/` and rewrite the spec to permit single-layer utilities — rejected. That inverts the pruning goal and keeps the grab bag.

### D2 — `to_sync` inlined into `entrypoints/client.py` as a private helper

**Choice:** Move the `to_sync` function body (plus `ParamT`/`ReturnT_co` TypeVars and the `ParamSpec` import) into `yascheduler/entrypoints/client.py` as a module-private helper (leading-underscore name `_to_sync` is optional; the symbol is simply not re-exported). Update `client.py` `MODULE_MAP` to list `to_sync` as a private helper and `MODULE_CONTRACT` `DEPENDS` accordingly. The two call sites (`queue_submit_task` line ~118, `queue_get_tasks` line ~156) update from `to_sync(...)` to the local name.

**Rationale:** Single consumer, 2 call sites, 24 lines. The six CLI consumers were removed by `consolidate-daemon-entrypoints` (CLI now uses `asyncio.run` because "CLI entry points have no async caller"). `client.py` uses `to_sync` because the public API is sync-over-async use cases — not going to change. If a second consumer ever appears, extract then (YAGNI).

**Alternatives considered:**
- `entrypoints/async_bridge.py` as a shared entrypoints helper — rejected. No second consumer exists; a one-consumer module is a single-consumer module regardless of where it sits.
- Keep `to_sync` in `shared/async_utils.py` — rejected. That keeps the retrofit intact and leaves the negative definition unchallenged.
- Lift `to_sync` to a domain port — rejected. It is a runtime bridge, not a domain contract.

### D3 — `asleep_until` inlined into `application/orchestrator.py` as a private helper

**Choice:** Move the 6-line `asleep_until` body into `yascheduler/application/orchestrator.py` as a module-private helper `_asleep_until`. Update the 2 call sites (lines ~191, ~450).

**Rationale:** Single consumer, 2 call sites, 6 lines (a trivial `await asyncio.sleep((end-now).total_seconds())` with an early return). Inlining loses nothing. `orchestrator.py` is already 450+ lines; +6 lines is noise.

**Alternatives considered:**
- `application/async_utils.py` — rejected. No second consumer; YAGNI.
- Keep in `shared/async_utils.py` — rejected (same as D2).

### D4 — Delete `shared/async_utils.py`; remove `ParamSpec` from `compat.py`

**Choice:** After D2 and D3, `shared/async_utils.py` is empty → delete it. `ParamSpec` in `compat.py` was consumed only by `async_utils.py`'s `to_sync` signature; after the inline, no production code imports `ParamSpec` from `shared` → remove it from `compat.py` (and from `shared/__init__.py` re-exports and `__all__`). `compat.py` keeps `Self` and `Unpack`.

**Rationale:** Dead code is dead. Keeping `ParamSpec` in `shared` would preserve a symbol with zero consumers — exactly the kind of unpruned residue this change exists to remove. `Self` and `Unpack` remain because `config` and `domain` still consume them across ≥2 layers.

**Cascade:** The `package-facades` scenario "compat.py old path removed" (L592-594) currently asserts "`Self` and `ParamSpec` are importable only via `from yascheduler.shared import Self, ParamSpec`". This scenario is rewritten to drop `ParamSpec` (see spec delta).

### D5 — `shared/__init__.py` facade shrinks; `MODULE_CONTRACT` `SCOPE` rewritten positively

**Choice:** `shared/__init__.py` re-exports only `Self` and `Unpack` (from `.compat`). `__all__ = ["Self", "Unpack"]`. `MODULE_CONTRACT` `SCOPE` rewritten from "Facade re-exports only — no business logic, no I/O, no domain types" to the positive form: "Typing shims consumed by ≥2 architectural layers; a module whose consumers are in a single layer belongs to that layer, not to `shared`. No SSH/DB/HTTP/cloud I/O."

**Rationale:** The negative definition was the retrofit's defense. The positive definition makes the rule actionable: a reviewer can reject a future `shared` addition by pointing to its single-layer consumer set, not by arguing whether `getenv` counts as I/O. The "no SSH/DB/HTTP/cloud I/O" clause stays as a second guardrail (a cross-layer helper that does network I/O is still wrong even if 2 layers want it).

**Alternatives considered:**
- Drop the I/O clause entirely — rejected. Two guardrails are better than one; a future `requests`-based "shared HTTP client" consumed by 2 layers would pass the positive definition alone.
- Keep the negative definition and add the positive as an extra paragraph — rejected. Contradictory definitions invite lawyering; one positive definition is cleaner.

### D6 — `yascheduler/__init__.py` re-export source switches; `entrypoints/__init__.py` facade extends

**Choice:**
- `yascheduler/__init__.py`: `from yascheduler.shared import CONFIG_FILE, LOG_FILE, PID_FILE` → `from yascheduler.entrypoints import CONFIG_FILE, LOG_FILE, PID_FILE`. `__all__` unchanged. `MODULE_CONTRACT` `DEPENDS` drops `M-SHARED`, keeps `M-ENTRYPOINTS`.
- `yascheduler/entrypoints/__init__.py`: add `from .paths import CONFIG_FILE, LOG_FILE, PID_FILE`. Extend `__all__` to include the three constants. Update `MODULE_MAP` and `MODULE_CONTRACT` `LINKS` to reference `M-ENTRYPOINTS-PATHS`.

**Rationale:** R2 (cross-package facade imports) requires `entrypoints/cli/*` to consume `paths.py` symbols via the `entrypoints` layer facade, not via a deep sibling-cross-subpackage path. `yascheduler/__init__.py` is the package facade; it re-exports the public surface and is keyed on the resolvable symbol (`from yascheduler import CONFIG_FILE`), not on the file path — so switching the re-export source is backward-compatible.

**Consequence for `relocate-di-to-entrypoints`:** that change also extends `entrypoints/__init__.py` (adding `make_daemon`/`make_cli_deps`/`CLIDeps`). The two extensions are on disjoint symbols; the `__all__` lists merge at archive time. No conflict.

### D7 — Consumer import rewrites

**Choice:**

| File | Before | After |
|------|--------|-------|
| `entrypoints/client.py` | `from yascheduler.shared import CONFIG_FILE, to_sync` | `from .paths import CONFIG_FILE` + inlined `to_sync` (D2); `ParamSpec` imported directly from `typing`/`typing_extensions` inside `client.py` with the same `sys.version_info` branch `compat.py` uses (not from `yascheduler.shared`, since D4 removes it there). `client.py` does not import `Self` from `shared` today (verified by grep) and gains no `Self` import from this change. |
| `entrypoints/cli/args.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler.entrypoints import CONFIG_FILE` |
| `entrypoints/cli/init.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler.entrypoints import CONFIG_FILE` |
| `entrypoints/cli/daemon_sysv.py` | `from yascheduler.shared import LOG_FILE, PID_FILE` | `from yascheduler.entrypoints import LOG_FILE, PID_FILE` |
| `application/orchestrator.py` | `from yascheduler.shared import asleep_until` | inlined `_asleep_until` (D3) |
| `yascheduler/__init__.py` | `from yascheduler.shared import CONFIG_FILE, LOG_FILE, PID_FILE` | `from yascheduler.entrypoints import CONFIG_FILE, LOG_FILE, PID_FILE` (D6) |

**Rationale for `client.py` `ParamSpec` handling:** inlining `to_sync` means its `ParamSpec("ParamT")` TypeVar construction must live where `to_sync` lives. Importing `ParamSpec` from `yascheduler.shared` would re-introduce the very dependency this change removes. The clean option is to import `ParamSpec` directly in `client.py` with the same `sys.version_info` branch `compat.py` uses — but that duplicates the branch. The cleaner option: since `client.py` already imports `Self` from `yascheduler.shared` for its own typing, and `compat.py` keeps `Self`/`Unpack` but loses `ParamSpec`, `client.py` imports `ParamSpec` directly from `typing`/`typing_extensions` (2-line branch). This keeps `client.py` self-contained for its private helper.

**Test rewrites (7 files):**

| File | Before | After |
|------|--------|-------|
| `tests/unit/test_cli_args.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler import CONFIG_FILE` |
| `tests/unit/test_cli_check_status.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler import CONFIG_FILE` |
| `tests/unit/test_cli_show_nodes.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler import CONFIG_FILE` |
| `tests/unit/test_cli_submit.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler import CONFIG_FILE` |
| `tests/unit/test_cli_init.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler import CONFIG_FILE` |
| `tests/unit/test_cli_manage_node.py` | `from yascheduler.shared import CONFIG_FILE` | `from yascheduler import CONFIG_FILE` |
| `tests/unit/test_cli_daemon_sysv.py` | `from yascheduler.shared import LOG_FILE, PID_FILE` | `from yascheduler import LOG_FILE, PID_FILE` |

**Rationale:** Tests are outside the package; they should consume the public API path (`from yascheduler import …`), not the internal facade path. This is stable per the "Public API stability" requirement (L514-538) even after the re-export source switches. No test imports `to_sync` or `asleep_until` directly (verified by grep).

### D8 — GRACE knowledge graph updates

**Choice:**
- `M-SHARED`: remove annotations `fn-to_sync`, `fn-asleep_until`, `const-CONFIG_FILE`, `const-LOG_FILE`, `const-PID_FILE`, `type-ParamSpec`. Keep `type-Self`, `type-Unpack`. Update `<purpose>` to "Typing shims consumed by ≥2 architectural layers (Self, Unpack)." `<depends>` stays `none`.
- New `M-ENTRYPOINTS-PATHS` element: `TYPE="UTILITY"`, `STATUS="implemented"`, `<path>yascheduler/entrypoints/paths.py</path>`, `<depends>none</depends>`, annotations `const-CONFIG_FILE`, `const-LOG_FILE`, `const-PID_FILE`.
- `M-ENTRYPOINTS`: add annotations `const-CONFIG_FILE`, `const-LOG_FILE`, `const-PID_FILE` (re-exported from `.paths`); update `<depends>` to include `M-ENTRYPOINTS-PATHS`; update `LINKS`.
- `M-MAIN`: `<depends>` from `M-ENTRYPOINTS, M-SHARED` → `M-ENTRYPOINTS`. Remove the `CrossLink from="M-MAIN" to="M-SHARED"` (if present — verify; the graph may not have one). Update annotations comment.
- `M-ENTRYPOINTS-CLIENT`: update annotation note — `to_sync` is now a private resident, not a re-export from `M-SHARED`.
- `M-APPLICATION-ORCHESTRATOR`: optionally add `fn-_asleep_until` annotation (GRACE-lite: "Optional: private helpers" — include for traceability since it has a `START_CONTRACT` block if the inline preserves it).

**Rationale:** The graph convention is: a distinct file with its own `MODULE_CONTRACT` gets its own M-ID. `paths.py` will carry a full contract → `M-ENTRYPOINTS-PATHS`. (Precedent: `variables.py` lacked its own M-ID — a retrofit omission, not a model.) `M-MAIN` dropping `M-SHARED` reflects that the package facade no longer touches `shared`.

### D9 — Spec delta is MODIFIED-only on `package-facades`

**Choice:** One delta spec file at `specs/package-facades/spec.md` with `## MODIFIED Requirements` for:
- "Outside-layer-set exemptions" (rewrite the shared-kernel clause L310 and scenario L328-330 to the positive definition).
- "Entrypoints layer facade" (add `CONFIG_FILE`/`LOG_FILE`/`PID_FILE` from `.paths` to the re-export list L184-191; add a scenario for path-constant re-export).
- "Public API stability" (update the path-constant re-export source L531-538 from `yascheduler.shared.variables` to `yascheduler.entrypoints.paths`; rewrite the `to_sync` clause L559-562 to state it is a private helper in `entrypoints/client.py`; rewrite scenarios L584-590 and L592-594).

No ADDED, REMOVED, or RENAMED requirements.

**Rationale:** The explore established that only `package-facades` has spec-level behavior changes. The `dependency-injection` and `test-db-integration` specs touched by `relocate-di-to-entrypoints` are disjoint from this change. No new capability is introduced.

## Risks / Trade-offs

- **[Risk] External downstream code imports `from yascheduler.shared import {to_sync, ParamSpec, asleep_until}` and breaks on upgrade.** → Mitigation: all three were internal utilities; no `[project.scripts]` entry references them; the post-`consolidate-daemon-entrypoints` codebase has no production consumer of `to_sync` outside `client.py` or of `asleep_until` outside `orchestrator.py`. The breaking change is called out in the proposal Impact. No shim is added (YAGNI; adding shims reverses the pruning).

- **[Risk] `import-linter` `layers` contract flags `entrypoints/paths.py` for importing `os` only — false alarm.** → Mitigation: `os` is stdlib, not a layer; the contract checks `yascheduler.*` imports only. `paths.py` imports nothing from `yascheduler.*`. No violation possible.

- **[Risk] `entrypoints/__init__.py` facade extension creates an import cycle.** → Mitigation: `paths.py` imports only `os.getenv`; it does not import from `entrypoints/__init__.py` or any other `yascheduler` module. `__init__.py` imports `.paths` and `.client` and `.di`; `.client` imports `.paths` (sibling) and `.di` (sibling); none import `__init__.py`. No cycle.

- **[Risk] Parallel change `relocate-di-to-entrypoints` edits the same `entrypoints/__init__.py` and `package-facades/spec.md`.** → Mitigation: disjoint symbols (`make_daemon`/`make_cli_deps`/`CLIDeps` vs `CONFIG_FILE`/`LOG_FILE`/`PID_FILE`) and disjoint spec requirement blocks (the di change touches "Outside-layer-set exemptions" di bullet and "Entrypoints layer facade" di re-exports; this change touches the same requirement's shared-kernel clause and path-constant re-exports — overlap is in the same requirement, so the MODIFIED blocks must be merged carefully at archive time). The two deltas are sequenced by archive order; whichever archives first leaves the other to rebase its MODIFIED block on the updated main spec. No semantic conflict (disjoint symbols, disjoint lines).

- **[Trade-off] The positive shared-kernel definition ("≥2 architectural layers") could be gamed by a contributor adding a trivial import to a second layer just to qualify for `shared`.** → Acceptable: the "no SSH/DB/HTTP/cloud I/O" clause and reviewer scrutiny are the second guardrail; the definition is a floor, not a ceiling. The negative definition had the same gaming risk with no floor at all.

- **[Trade-off] Inlining `to_sync` into `client.py` duplicates the `ParamSpec` version branch that `compat.py` currently centralizes.** → Acceptable: 2 lines duplicated, single consumer. Centralizing a 2-line version branch for one consumer is the abstraction-without-payoff this change is pruning. If a second consumer appears, extract then.

- **[Trade-off] `M-MAIN` dropping `M-SHARED` from `<depends>` removes a graph edge that visually anchored `shared` to the package root.** → Acceptable: the edge was a side effect of the re-export, not a real dependency. `M-MAIN` depends on `M-ENTRYPOINTS` (which re-exports everything `M-MAIN` re-exports); `M-SHARED` is now only consumed by `M-CONFIG` and `M-DOMAIN-MODEL`, which is the honest dependency picture.

## Migration Plan

Single-PR mechanical migration; no runtime behavior change, no DB schema change, no config format change.

1. `git mv yascheduler/shared/variables.py yascheduler/entrypoints/paths.py`; drop the FIXME line; update `# FILE:` header, `MODULE_CONTRACT` (`LINKS: M-ENTRYPOINTS-PATHS`), `MODULE_MAP`, `CHANGE_SUMMARY`.
2. Inline `to_sync` (+ `ParamT`/`ReturnT_co` + local `ParamSpec` version branch) into `yascheduler/entrypoints/client.py`; update the 2 call sites; update `MODULE_MAP`/`MODULE_CONTRACT`/`CHANGE_SUMMARY`.
3. Inline `asleep_until` as `_asleep_until` into `yascheduler/application/orchestrator.py`; update the 2 call sites; update `MODULE_MAP`/`CHANGE_SUMMARY`.
4. `git rm yascheduler/shared/async_utils.py`.
5. Edit `yascheduler/shared/compat.py`: remove `ParamSpec` (the version branch and the `__all__` entry); update `MODULE_MAP`/`MODULE_CONTRACT`/`CHANGE_SUMMARY`.
6. Edit `yascheduler/shared/__init__.py`: drop re-exports of `to_sync`, `asleep_until`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `ParamSpec`; keep `Self`, `Unpack`; rewrite `MODULE_CONTRACT` `SCOPE` to the positive definition (D5); update `MODULE_MAP`/`CHANGE_SUMMARY`.
7. Edit `yascheduler/entrypoints/__init__.py`: add `from .paths import CONFIG_FILE, LOG_FILE, PID_FILE`; extend `__all__`; update `MODULE_MAP`/`MODULE_CONTRACT` `LINKS`/`CHANGE_SUMMARY`.
8. Edit `yascheduler/__init__.py`: `from yascheduler.shared import …` → `from yascheduler.entrypoints import CONFIG_FILE, LOG_FILE, PID_FILE`; update `MODULE_CONTRACT` `DEPENDS` (`M-SHARED` removed); `CHANGE_SUMMARY`.
9. Rewrite the 5 production consumer imports per the table in D7.
10. Rewrite the 7 test file imports per the table in D7.
11. Update `docs/knowledge-graph.xml` per D8.
12. Update `docs/ARCHITECTURE.md` if it references `shared.variables` or `shared.async_utils` (verify by grep during implementation).
13. Verify `openspec/changes/prune-shared-kernel/specs/package-facades/spec.md` is present and contains the three MODIFIED requirement blocks per D9; run `openspec validate --all --json` to confirm the delta validates.
14. Run `rg "yascheduler\.shared\.(variables|async_utils)|from yascheduler\.shared import (to_sync|asleep_until|ParamSpec|CONFIG_FILE|LOG_FILE|PID_FILE)"` repo-wide; expected zero matches.
15. Run `uv run pytest -m unit`, `uv run lint-imports` (both `layers` and `forbidden` contracts must pass), `uv run ruff check .`, `uv run ruff format --check .`, `uv run zuban check`, `uv run lint-imports`, `python3 scripts/grace_check.py`, `openspec validate --all --json`. Smoke check: `python -c "from yascheduler import CONFIG_FILE, LOG_FILE, PID_FILE, Yascheduler; from yascheduler.shared import Self, Unpack; print('ok')"` — must print `ok`. Negative smoke: `python -c "from yascheduler.shared import to_sync" 2>&1 | grep ImportError` — must error.

**Rollback:** `git revert` the single PR. No data, no config, no external state involved.

## Open Questions

None. All decisions from explore mode are captured above (D1–D9 map to the explore conclusions; OQ1 parallel sequencing, OQ2 new M-ID, OQ3 positive definition were all resolved by the user before proposal).
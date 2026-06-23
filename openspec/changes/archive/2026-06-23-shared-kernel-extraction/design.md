## Context

The proposal (frozen) establishes WHY: the top level of `yascheduler/` is a legacy accumulator with no discipline, and genuine cross-layer utilities (`compat.py`, `variables.py`, `to_sync` inside `client.py`) live alongside entry points and a legacy data layer. The `package-facades` spec already lists `yascheduler.compat` as an outside-layer-set module, but it has no dedicated home — it accretes at the root. This change creates `yascheduler/shared/` as the project's shared kernel, relocates three utilities there, and updates the `package-facades` spec to reflect the new home.

Two architectural inputs constrain this design:

- The `package-facades` spec (frozen baseline) already defines the outside-layer-set discipline (`config`, `data`, `composition root`, `compat`, `aiida_plugin`, `db` legacy). The shared kernel is added as a **4th (bottom) layer** in the `layers` contract — NOT as an outside-layer-set peer. This hard-enforces that `yascheduler.shared` imports nothing from `adapters`/`application`/`domain`.
- The `import-linter` `layers` contract today enforces only R3 (`adapters → application → domain`). Adding `yascheduler.shared` as the 4th bottom layer extends R3 to `adapters → application → domain → shared`. A separate `forbidden` contract additionally blocks `yascheduler.shared → yascheduler.config` to prevent the one import cycle that the `layers` contract cannot catch (because `config` is outside-layer-set and thus not in the `layers` list).

Current state of the three utilities being relocated:

- `yascheduler/compat.py` — 32 lines, `Self` and `ParamSpec` typing shims, version-dependent imports. Consumers: `client.py`, `config/{cloud,engine_repository,remote}.py`, `db.py`, `tests/unit/test_message_bus.py`.
- `yascheduler/variables.py` — 27 lines, `CONFIG_FILE`/`LOG_FILE`/`PID_FILE` env-derived path constants. Consumers: `__init__.py`, `client.py`, `daemon_systemd.py`, `daemon_sysv.py`, `adapters/cli/{submit,daemonize,show_nodes,init,check_status,manage_node}.py`.
- `to_sync` in `yascheduler/client.py` — async-to-sync runtime bridge (lines 43–65). Consumers: `client.py` itself (self-use in `queue_submit_task`, `queue_get_tasks`), plus `adapters/cli/{submit,daemonize,show_nodes,check_status,manage_node}.py` (5 sibling entry-point imports — the smell that motivates the extraction).

## Goals / Non-Goals

**Goals:**

- Create `yascheduler/shared/` as the single home for cross-layer utilities.
- Add `yascheduler.shared` as the 4th (bottom) layer in the `import-linter` `layers` contract, hard-enforcing that `shared` imports nothing from `adapters`/`application`/`domain`.
- Add a `forbidden` `import-linter` contract blocking `yascheduler.shared → yascheduler.config` to prevent the import cycle that the `layers` contract cannot catch (since `config` is outside-layer-set).
- Relocate `compat.py`, `variables.py`, and `to_sync` (as `async_utils.py`) into `yascheduler/shared/`.
- Establish `yascheduler/shared/__init__.py` as a lazy-publication facade (mirrors the `package-facades` policy): re-export exactly what consumers need today.
- Update the `package-facades` spec to record the new 4th layer, the `forbidden` contract, the removal of `yascheduler.compat` from outside-layer-set, and the "no business logic / no I/O" contract for the shared kernel.
- Update the GRACE-lite knowledge graph to reflect the relocation.
- Update all consumers' import paths in one atomic change (no compat shims).

**Non-Goals:**

- Move `yascheduler/time.py` and `yascheduler/queue.py`. They have a single consumer (`application/orchestrator`) and should move INTO `application/` as private modules, not into shared kernel. Separate change.
- Move `yascheduler/webhook.py` (domain value object candidate) — separate analysis.
- Delete `yascheduler/db.py` (legacy, scheduled separately).
- Hard-enforce R2 (facade-only imports) for `yascheduler.shared` via `import-linter`. R2 stays convention + spec. The `forbidden` contract added by this change is NOT R2 — it blocks only the `shared → config` cycle, not facade violations.
- Add backward-compat re-export shims at the old paths. The `package-facades` spec already states `yascheduler.compat` SHALL remain internal (not public surface), so removing the old path is not a public API break.
- Bump Python version or touch the `import-linter` version pin.
- Forbid `yascheduler.shared → {data, di, client, db, aiida_plugin}` via `import-linter`. The `forbidden_modules` list contains only `yascheduler.config` (per user instruction). Other reverse edges are not cycle risks in practice (no plausible reason for `shared` to import an entry point or legacy DB).

## Decisions

### D1. `yascheduler.shared` is the 4th (bottom) layer, NOT outside-layer-set

The `layers` contract today is `["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]`. Adding `yascheduler.shared` as the 4th bottom layer produces `["yascheduler.adapters", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`. This hard-enforces that `shared` imports nothing from `adapters`/`application`/`domain` — the `layers` contract checks "higher may import lower, lower may not import higher", so `shared` (bottom) cannot import from the three layers above it.

**What the `layers` contract does NOT catch**: `yascheduler.config` is outside-layer-set (it is not in the `layers` list). `config` imports `yascheduler.shared.Self` today (3 files: `config/{cloud,remote,engine_repository}.py`). If `shared` were to import from `config`, that would close a cycle: `config → shared → config`. The `layers` contract cannot catch this because `config` is not a layer.

**Decision**: add a second `import-linter` contract of type `forbidden` with `source_modules = ["yascheduler.shared"]` and `forbidden_modules = ["yascheduler.config"]`. This blocks the one reverse edge that creates a real cycle risk.

**Why `forbidden_modules` contains only `yascheduler.config`**: `config` is the only outside-layer-set module that (a) already imports from `shared` (creating the cycle potential) AND (b) is a plausible import target for `shared` (both are "utility" packages — a contributor might reasonably try `from yascheduler.config import X` inside `shared`). Other outside-layer-set modules (`data`, `di`, `client`, `db`, `aiida_plugin`) either do not import from `shared` or are implausible import targets for `shared` (entry points, legacy DB, AiiDA plugin). The user explicitly scoped `forbidden_modules` to `yascheduler.config` only.

**Alternative considered (Round 1, rejected)**: keep `yascheduler.shared` as outside-layer-set (peer to `config`/`data`), with no `import-linter` enforcement — relying on spec prose + code review. Rejected by the user: the whole point of creating `yascheduler.shared` is to escape the undisciplined top-level accumulator, and leaving it unenforced reproduces the same problem at a new location.

**Alternative considered (Round 2, rejected)**: add `yascheduler.shared` as a 4th layer AND add `yascheduler.config` as a 5th layer below it (`[..., "yascheduler.config", "yascheduler.shared"]`). This would let `layers` catch both `shared → {adapters,application,domain}` and `shared → config` in one contract. Rejected because `config` is outside-layer-set by deliberate prior decision (the original `clean-architecture-imports` change kept `config` out of the `layers` list to avoid flagging the existing `domain → config`-adjacent imports); pulling `config` in as a layer would be a larger decision-level change to the `package-facades` spec beyond this change's scope. The `forbidden` contract achieves the cycle-prevention goal without reclassifying `config`.

### D2. `to_sync` gets its own file (`async_utils.py`), not merged into `compat.py`

`compat.py` is typing-only today (`Self`, `ParamSpec` — both used exclusively in type annotations, never at runtime). `to_sync` is a runtime decorator that creates a `ThreadPoolExecutor` and runs an event loop. Mixing them muddies the module contract: "typing shims" vs "runtime async-to-sync bridge" are two different responsibilities.

**Decision**: `yascheduler/shared/async_utils.py` is a new file. `yascheduler/shared/compat.py` stays typing-only.

**Alternative considered**: extend `compat.py` to hold `to_sync` too. Rejected — violates single-responsibility. The brief's open question #1 is resolved: own file.

### D3. Lazy facade with exactly 6 re-exports

`yascheduler/shared/__init__.py` re-exports exactly the symbols consumers need today:

```python
from .async_utils import to_sync
from .compat import ParamSpec, Self
from .variables import CONFIG_FILE, LOG_FILE, PID_FILE

__all__ = [
    "CONFIG_FILE",
    "LOG_FILE",
    "PID_FILE",
    "ParamSpec",
    "Self",
    "to_sync",
]
```

This mirrors the `package-facades` lazy-publication policy: each re-export exists because a real consumer requires it. Adding a new symbol to the facade is a deliberate act.

**Alternative considered**: re-export everything not prefixed with `_` (Variant A from the original `clean-architecture-imports` explore). Rejected for the same reason it was rejected there — produces a grab-bag and loses encapsulation.

### D4. No backward-compat shims at old paths

Old paths (`yascheduler/compat.py`, `yascheduler/variables.py`) cease to exist. `to_sync` definition is removed from `client.py`. All consumers update in the same change.

**Justification**: The `package-facades` spec's "Public API stability" requirement states `yascheduler.compat` SHALL remain internal (not public surface). `yascheduler.variables` is re-exported from `yascheduler/__init__.py` (so downstream consumers use `from yascheduler import CONFIG_FILE`, never `from yascheduler.variables import CONFIG_FILE`). `to_sync` is an internal helper consumed by CLI adapters; no public API contract covers it.

**Alternative considered**: leave `yascheduler/compat.py` as a one-line re-export `from yascheduler.shared.compat import Self, ParamSpec` for one release. Rejected — AGENTS.md says "Do not add compatibility layers without a concrete need", and the `package-facades` spec already declares these modules internal. No concrete downstream consumer needs the old path.

### D5. `yascheduler.shared` "no business logic / no I/O" contract

The `package-facades` spec's "Outside-layer-set exemptions" requirement will add a clause: `yascheduler.shared` SHALL NOT contain business logic, domain types, or I/O. This mirrors the implicit contract that `yascheduler.config` and `yascheduler.data` already follow. The clause is enforceable by code review (same as R1/R2); no tooling.

**Why this matters**: without the clause, `yascheduler.shared` could accrete into the same accumulator the top-level is today. The clause gives reviewers a spec-grounded basis to reject "I'll just put this helper in shared" when the helper is actually business logic or I/O.

**Alternative considered**: leave the "no business logic / no I/O" rule implicit (like `config` and `data` today). Rejected — `config` and `data` are narrowly scoped by name (configuration containers, static data files); `shared` is a broader bucket that invites accretion. Making the rule explicit in the spec is the prophylactic.

### D6. Knowledge graph: one `M-SHARED` module, not three

The graph today has `M-COMPAT` and `M-VARIABLES` as separate UTILITY modules. `to_sync` is an annotation on `M-CLIENT`.

**Decision**: collapse into a single `M-SHARED` module entry (`TYPE="UTILITY"`, `STATUS="implemented"`, `depends=none`) with sub-annotations `fn-to_sync`, `type-Self`, `type-ParamSpec`, `const-CONFIG_FILE`, `const-PID_FILE`, `const-LOG_FILE`. This matches the structural reality: one package, one graph node.

**Alternative considered**: keep `M-SHARED-COMPAT`, `M-SHARED-ASYNC-UTILS`, `M-SHARED-VARIABLES` as three separate modules. Rejected — the graph is for navigation, and one `M-SHARED` node with sub-annotations is sufficient. Three nodes would be over-granular for a 3-file subpackage.

`M-CLIENT` loses its `fn-to_sync` annotation (the function is no longer defined there). `M-CLIENT.depends` changes from `M-VARIABLES, M-COMPAT, ...` to `M-SHARED, ...`. Same for `M-MAIN`, `M-DAEMON-SYSTEMD`, `M-DAEMON-SYSV`, `M-CLI-COMMANDS`, `M-DB`, `M-CONFIG-CLOUD`, `M-CONFIG-REMOTE`, `M-CONFIG-ENGINE-REPO`.

## Risks / Trade-offs

| Risk | Mitigation |
| --- | --- |
| A consumer's import path is missed during the move, leaving a broken import | The `tasks.md` checklist enumerates every consumer file (cross-checked by grepping `from yascheduler.compat`, `from yascheduler.variables`, `from .compat`, `from .variables`, `from yascheduler.client import to_sync`). `lint-imports` + `ruff check` + `pytest -m unit` all catch a missed import. |
| Someone later adds business logic to `yascheduler.shared`, turning it into the same accumulator the top-level was | The `package-facades` spec's modified "Outside-layer-set exemptions" requirement adds the explicit "no business logic / no I/O" clause (defense-in-depth), AND the `layers` contract now hard-enforces that `shared` imports nothing from `adapters`/`application`/`domain` — so even if business logic were added, it could not reach domain entities or use-case orchestration. |
| Someone adds `from yascheduler.config import X` inside `yascheduler.shared`, creating an import cycle | The new `forbidden` contract (`source_modules = ["yascheduler.shared"]`, `forbidden_modules = ["yascheduler.config"]`) hard-blocks this; `lint-imports` fails. |
| The graph update misses a `<depends>` reference, leaving a broken `M-COMPAT`/`M-VARIABLES` pointer | `python3 scripts/grace_check.py` validates graph integrity; the tasks checklist enumerates all 9 modules whose `<depends>` must change. |
| `yascheduler.shared` grows beyond 3 files over time and the single `M-SHARED` node becomes too coarse | Acceptable for now. If the subpackage exceeds ~5 files, split into `M-SHARED-COMPAT` / `M-SHARED-ASYNC` / `M-SHARED-VARIABLES` in a follow-up graph-only change. Not blocking. |
| A downstream consumer (outside this repo) imports `from yascheduler.compat import Self` directly | The `package-facades` spec already declares `yascheduler.compat` internal. Any such downstream consumer is already violating the spec. The `pyproject.toml` `[project.scripts]` and entrypoints do not reference these paths. |
| `to_sync` has a subtle runtime behavior (detects running event loop, spawns `ThreadPoolExecutor`) that breaks after extraction | The function body is moved verbatim, no logic change. `tests/unit/test_cli_smoke.py` verifies the `__wrapped__` contract on all 5 `@to_sync`-decorated CLI functions. |
| `import-linter` `forbidden` contract type not supported in `>=2.5,<2.6` | Verified: `forbidden` contract type with `source_modules`/`forbidden_modules` has been supported since `import-linter 1.0b4` (2019). No compat risk. |

**Concentration note**: Three risks (missed import, missed graph reference, downstream consumer) all reduce to "the move is mechanical and must be exhaustive". The mitigation is the same: the `tasks.md` checklist enumerates every touch point, and the standard verification ladder (`pytest`, `ruff`, `zuban`, `lint-imports`, `grace_check.py`) catches any miss.

## Migration Plan

Single-PR change. No runtime behavior change. No data migration. Steps in order:

**Code (1–5):**

1. Create `yascheduler/shared/__init__.py` (facade re-exporting `Self`, `ParamSpec`, `to_sync`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`).
2. Create `yascheduler/shared/compat.py` (move body from `yascheduler/compat.py`; update GRACE-lite `FILE`/`LINKS`).
3. Create `yascheduler/shared/async_utils.py` (move `to_sync` body from `yascheduler/client.py`; new GRACE-lite MODULE_CONTRACT).
4. Create `yascheduler/shared/variables.py` (move body from `yascheduler/variables.py`; update GRACE-lite `FILE`/`LINKS`).
5. Update consumers (~15 files) to import from `yascheduler.shared` facade. Delete `yascheduler/compat.py` and `yascheduler/variables.py`. Remove `to_sync` definition from `yascheduler/client.py`.

**`pyproject.toml` — extend `[tool.importlinter]`:**

6a. Edit the existing `layers` contract: change `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]` to `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`. This makes `yascheduler.shared` the 4th (bottom) layer; the `layers` contract now enforces that `shared` imports nothing from `adapters`/`application`/`domain`.

6b. Add a second `[[tool.importlinter.contracts]]` entry:
```toml
[[tool.importlinter.contracts]]
name = "Shared kernel has no config imports"
type = "forbidden"
source_modules = ["yascheduler.shared"]
forbidden_modules = ["yascheduler.config"]
```
This blocks the `shared → config` reverse edge that would close an import cycle (`config → shared.Self` already exists today). The `forbidden_modules` list is intentionally scoped to `yascheduler.config` only — other outside-layer-set modules are not cycle risks in practice.

**Knowledge graph (7–8):**

7. Update `docs/knowledge-graph.xml`: remove `M-COMPAT`, `M-VARIABLES`; add `M-SHARED`; update `<depends>` on 9 modules; remove `fn-to_sync` from `M-CLIENT.annotations`.
8. Run `python3 scripts/grace_check.py` — must exit 0.

**Specs (9):**

9. Update `openspec/specs/package-facades/spec.md` per the delta spec in this change (modifies "Layer direction (R3)" to add `yascheduler.shared` as 4th layer, "Outside-layer-set exemptions" to remove `yascheduler.compat`, "Layers contract configuration" to add the `forbidden` contract, "Public API stability" for path-constant re-export).

**Verification (10):**

10. Standard verification ladder: `uv run pytest -m unit`, `uv run zuban check`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run lint-imports` (must pass BOTH the `layers` contract with the new 4th layer AND the new `forbidden` contract), `python3 scripts/grace_check.py`, `openspec validate --all --json`. Smoke check: `from yascheduler.shared import Self, ParamSpec, to_sync, CONFIG_FILE, LOG_FILE, PID_FILE` resolves, and `from yascheduler import CONFIG_FILE` still resolves.

**Rollback**: revert the PR. No state to recover. The three utilities' bodies are unchanged — only their location moved.

## Open Questions

1. **Should `yascheduler.shared` be added to the `[tool.setuptools.packages.find]` include list?** No — `include = ["yascheduler*"]` already matches any subpackage. Verified in `pyproject.toml:140-141`. No change needed.
2. **Should the `package-facades` spec's "Documented private-symbol carve-outs" requirement be updated?** No — the only carve-out (`_resolve_adapter` in `di.py`) is unaffected by this change.
3. **Should `time.py` and `queue.py` move into `application/` as a follow-up?** Yes, but out of scope here. The design notes they are NOT moving into shared kernel (single consumer → private to the consumer layer). Tracked as a future change.
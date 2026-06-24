## Context

`yascheduler` has a hexagonal/clean-architecture layout enforced by `import-linter`
via a `layers` contract in `pyproject.toml`. The current contract is four layers:

```
yascheduler.infra → yascheduler.application → yascheduler.domain → yascheduler.shared
```

`yascheduler/client.py` is a driving adapter — the public Python client that calls
application use cases (`submit_task`, `query_tasks`) through a `CLIDeps` DI seam.
Despite being a driving adapter, it lives at the package root alongside `di.py`
(composition root), `aiida_plugin.py` and `daemon_*.py` (driving adapters), all
outside the `layers` contract. The file itself carries a `# FIXME: move to
adapters/api?` comment from the original author.

The `infra/` layer mixes driven adapters (persistence, ssh, cloud, notifier) with
six CLI command modules under `infra/cli/` that are themselves driving adapters
(argparse → use cases via `di`). This conflation of driving and driven in one layer
is a latent structural debt: a `di ↔ infra.cli` import cycle exists today
(`di.py` imports from `infra`, `infra/cli/*.py` import from `yascheduler.di`),
uncaught by the contract because neither `di` nor the cycle is in-scope.

This change introduces a dedicated outermost layer — `yascheduler.entrypoints` —
for driving adapters + composition root, and moves `client.py` into it as the
first resident. The remaining driving adapters (`di.py`, `aiida_plugin.py`,
`daemon_*.py`, `infra/cli/`) are explicitly deferred to follow-up changes.

Constraints:
- Public interface stability (AGENTS.md): `class Yascheduler` public API, the
  `from yascheduler import Yascheduler` import form, and the deep import
  `from yascheduler.client import Yascheduler` must continue to resolve for
  external downstream consumers.
- `config` is NOT promoted into the `layers` contract (stays outside-layer-set);
  the existing `forbidden: shared → config` contract is retained to prevent the
  `shared ↔ config` import cycle (`config → shared.Self` already exists).
- GRACE-lite: knowledge graph and module contracts must be updated in the same
  change.

## Goals / Non-Goals

**Goals:**
- Establish `yascheduler.entrypoints` as the outermost layer with import direction
  `entrypoints → infra → application → domain → shared`.
- Move `client.py` (the library client) into `entrypoints/` with its full
  implementation.
- Preserve all public import forms: `from yascheduler import Yascheduler` and
  `from yascheduler.client import Yascheduler`.
- Reclassify `yascheduler.client` in spec from "composition root" to "compat shim"
  with a real file backing it (not an `__init__.py` attribute binding).
- Update `package-facades` spec to reflect the new layer and reclassify the
  outside-layer-set members.
- Update the GRACE-lite knowledge graph: rename `M-CLIENT`, add `M-ENTRYPOINTS`
  facade and `M-CLIENT-SHIM` nodes, update dependents.

**Non-Goals:**
- Migrate `di.py`, `aiida_plugin.py`, `daemon_systemd.py`, `daemon_sysv.py`, or
  `infra/cli/*` into `entrypoints/`. These stay at their current locations and
  migrate in follow-up changes.
- Promote `config` into the `layers` contract (it remains outside-layer-set).
- Change `[project.scripts]` or `[project.entry-points."aiida.schedulers"]` in
  `pyproject.toml` — they still point at `infra.cli.*` / `aiida_plugin`.
- Change the `Yascheduler` class's public constructor or method signatures.
- Add new dependencies.

## Decisions

### D1. Layer name: `entrypoints`

**Choice:** `yascheduler.entrypoints`.

**Rationale:** "entrypoints" reads naturally as the presentation / driving-adapter
ring in a hexagonal layout and matches the layer's eventual contents (CLI, daemon
launchers, AiiDA plugin, composition root, library client).

**Alternatives considered:**
- `presentation` — classic clean-architecture term; rejected as verbose and less
  aligned with the package's existing naming style.
- `api` — rejected: too narrow for a ring that will also hold CLI and daemon
  launchers, and ambiguous with the `client.py` API surface.
- `delivery` (DDD) — rejected: less common in Python codebases.
- `driving` / `primary` (hexagonal canon) — rejected: unfamiliar to most Python
  contributors.
- `interfaces` — rejected: collides with `abc.ABC` / `typing.Protocol` intuition.

**Terminology note (for the proposal/design record):** `yascheduler.entrypoints`
is the presentation layer (driving adapters + composition root). It is unrelated
to setuptools `[project.scripts]` "entry points", which are packaging
declarations pointing *into* the layers. The two concepts coexist in the same
`pyproject.toml` but refer to different things.

### D2. Compat shim: real file, not `__init__.py` binding

**Choice:** Keep a physical `yascheduler/client.py` file as a thin re-export
shim (`from yascheduler.entrypoints.client import Yascheduler`,
`__all__ = ["Yascheduler"]`).

**Rationale:** The requirement is that `from yascheduler.client import
Yascheduler` continues to resolve for external downstream consumers. Python's
import system resolves `from pkg.client import X` by looking up the module
`pkg.client` in `sys.modules`. A `from .entrypoints import client` binding in
`yascheduler/__init__.py` creates `client` as a *package attribute* but does NOT
register `yascheduler.client` as a module — verified empirically (Python 3.13)
that `from yascheduler.client import Yascheduler` raises `ModuleNotFoundError`
in that scheme. A physical shim file is the only form that registers the module
honestly.

**Alternatives considered:**
- _5a — no shim, edit all call sites_: rejected because it breaks external
  consumers using the deep path.
- _5b — `from .entrypoints import client` in `__init__.py` only_: rejected after
  empirical verification (see explore-brief.md §Rejected alternatives).
- _5c-`import *`_ re-export: rejected because it depends on `__all__` in the
  target module and pulls in non-underscored imported names (`logging`,
  `Mapping`, etc.) — dirty surface. Explicit named re-export is cleaner.

**Shim scope:** re-export only `Yascheduler`. Do NOT re-export `Config` — the
shim is a public-API compat layer, not a test convenience. Consequence:
`patch("yascheduler.client.Config.from_config_parser")` in tests must migrate
to `patch("yascheduler.entrypoints.client.Config.from_config_parser")` (the
real module). This is acceptable: tests are internal and the migration is
mechanical (3 files).

### D3. Layer facade: `entrypoints/__init__.py` re-exports `Yascheduler`

**Choice:** `yascheduler/entrypoints/__init__.py` contains
`from .client import Yascheduler` (and `__all__ = ["Yascheduler"]`).

**Rationale:** Symmetry with `M-ADAPTERS` (`yascheduler/infra/__init__.py`) and
`M-APPLICATION` (`yascheduler/application/__init__.py`) facades. The layer
facade is the sole public surface for cross-layer consumers (R2). Today the only
resident is `client.py`; future driving adapters (CLI, daemon, AiiDA) will be
added to this facade lazily as they migrate.

**Within-package imports:** the shim `yascheduler/client.py` imports
`Yascheduler` via the facade path `from yascheduler.entrypoints import
Yascheduler` (R2-compliant cross-package import). The real implementation
module `yascheduler/entrypoints/client.py` imports its dependencies
(`application`, `config`, `di`, `domain`, `shared`) via their layer facades.

### D4. `config` stays outside-layer-set; `forbidden` contract retained

**Choice:** Do NOT add `yascheduler.config` to the `layers` contract. Keep the
existing `forbidden` contract `source_modules=["yascheduler.shared"],
forbidden_modules=["yascheduler.config"]`.

**Rationale:** `config` is a peer utility imported by `application`, `infra`,
and (after this change) `entrypoints`. Its only upward dependency is
`config → shared` (for `Self` / `ParamSpec` re-exports). Adding `config` as a
layer between `application` and `domain` would be non-standard (config is not
domain, not application) and would require deciding its exact position. The
current outside-layer-set exemption plus the directional `forbidden` contract
already prevents the `shared ↔ config` cycle. No change needed.

### D5. Knowledge graph: rename + add nodes

**Choice:**
- Rename `M-CLIENT` → `M-ENTRYPOINTS-CLIENT`; update `<path>` to
  `yascheduler/entrypoints/client.py`.
- Add `M-ENTRYPOINTS` (TYPE=ENTRY_POINT) for `yascheduler/entrypoints/__init__.py`
  — layer facade mirroring `M-ADAPTERS` / `M-APPLICATION`.
- Add `M-CLIENT-SHIM` (TYPE=UTILITY) for `yascheduler/client.py` — the compat
  re-export file. `PURPOSE: Compat shim re-exporting Yascheduler from
  yascheduler.entrypoints.client; real implementation lives in
  entrypoints/client.py.`
- Update `M-MAIN.depends`: replace `M-CLIENT` with `M-ENTRYPOINTS, M-SHARED`
  (the import reaches the client *via* the layer facade, so the dependency
  edge targets the facade node `M-ENTRYPOINTS`, not the deep module
  `M-ENTRYPOINTS-CLIENT`).
- Remove the spurious `M-AIIDA.LINKS` reference to `M-CLIENT`: `aiida_plugin.py` does not import the yascheduler client (talks to it via SSH/transport); the link was always wrong. Set `LINKS: none` in `aiida_plugin.py`'s MODULE_CONTRACT.
- Update every other `M-CLIENT` reference in the graph (verified by
  `rg -n "M-CLIENT" docs/knowledge-graph.xml` — 7 sites total):
  - `DF-SUBMIT` (line 847): `M-CLIENT -> M-DI -> ...` → `M-ENTRYPOINTS-CLIENT -> M-DI -> ...`
  - `DF-AIIDA-INTEGRATION` (line 850): DELETE — the `M-AIIDA -> M-CLIENT` data flow does not exist at the code level; `aiida_plugin.py` does not import the client.
  - `CrossLink` (line 859): `from="M-CLIENT" to="M-APPLICATION-QUERY-TASKS"` → `from="M-ENTRYPOINTS-CLIENT"`
  - `CrossLink` (line 861): DELETE — `from="M-AIIDA" to="M-CLIENT"` asserts a cross-module delegation that does not exist; the plugin uses SSH transport, not the Python client.
  - `CrossLink` (line 902): `from="M-CLIENT" to="M-DI"` → `from="M-ENTRYPOINTS-CLIENT"`
- Add `CrossLink from="M-MAIN" to="M-ENTRYPOINTS" relation="re-exports Yascheduler via layer facade"`.
- Add `CrossLink from="M-CLIENT-SHIM" to="M-ENTRYPOINTS-CLIENT" relation="compat re-export of Yascheduler"`.

The shim `yascheduler/client.py` itself does not get a `MODULE_CONTRACT`-driven
KG edge into `M-MAIN.depends` — it is an outside-layer-set exempt utility
re-exporting a symbol, not a structural dependency of the package facade
(`M-MAIN` reaches `Yascheduler` via `M-ENTRYPOINTS`). `M-CLIENT-SHIM` is
documented as a standalone node for completeness and for
`grace_check.py`-friendly attribution.

### D6. Spec rewrite scope: full rewrite of affected requirements

**Choice:** Rewrite the affected requirements of
`openspec/specs/package-facades/spec.md` in place (not delta-overlay). Affected
requirements:
- _Layer direction (R3)_ — add `yascheduler.entrypoints` as top layer.
- _Layers contract configuration_ — new `layers = [...]` with 5 entries.
- _Outside-layer-set exemptions_ — reclassify `yascheduler.client` as compat
  shim (not "composition root"); drop stale `yascheduler.db`,
  `yascheduler.compat`, `yascheduler.variables` references (these no longer
  exist in the codebase).
- _Public API stability_ — decouple the `Yascheduler` contract from the file
  path; key it on `from yascheduler import Yascheduler`.
- Add a new requirement documenting the `entrypoints` layer facade contents
  (`yascheduler/entrypoints/__init__.py` re-exports `Yascheduler`).

Unchanged requirements: _Shared kernel config-import prohibition_,
_Within-package relative imports (R1)_, _Cross-package facade imports (R2)_,
_Package facade as public surface (lazy publication)_, _Documented residual
edges_, _Domain package facade contents_, _Extended facade contents_,
_Documented private-symbol carve-outs_, _Broad ignore_imports tradeoff_.

The _Yascheduler client query method public contract_ requirement is also
rewritten in the delta: its body references the file path
`yascheduler/client.py`, which becomes a compat shim after this change. The
rewrite decouples it from the file path (keying on `from yascheduler import
Yascheduler`) and clarifies that the `Yascheduler` class now lives in
`yascheduler.entrypoints.client` while preserving all public-method signatures
and the 6-key Mapping output shape. This is consistent with the public-API
decoupling decision (D6, Public API stability) and does not change the
requirement's normative intent — only its file-path reference.

## Risks / Trade-offs

- **[Risk] Shim maintenance drift** — a future contributor edits the shim
  `yascheduler/client.py` instead of `yascheduler/entrypoints/client.py`; the
  change silently has no effect.
  → **Mitigation:** the shim's GRACE-lite `MODULE_CONTRACT` PURPOSE explicitly
  states the implementation lives in `entrypoints/client.py`. No additional
  warning comment beyond the contract (the contract is the single source of
  truth per GRACE-lite).
- **[Risk] `patch("yascheduler.client.Config…")` breaks at test runtime** — if
  a test is missed in the migration, the patch raises
  `AttributeError: module 'yascheduler.client' has no attribute 'Config'`.
  → **Mitigation:** the tasks checklist enumerates the 3 affected test files;
  `rg "yascheduler\.client"` after the edit confirms zero remaining references.
  Unit tests (`uv run pytest -m unit`) catch the regression immediately.
- **[Trade-off] Two classes of driving adapters during the transition** —
  `client.py` lives in `entrypoints/`, but `di.py`, `aiida_plugin.py`,
  `daemon_*.py`, and `infra/cli/` remain at their current locations. The layer
  is partially populated.
  → **Mitigation:** the Out-of-scope section of the proposal and a comment in
  the `entrypoints/__init__.py` facade document the interim state and the
  follow-up intent. Reviewers accept this as scoped.
- **[Trade-off] `entrypoints` name collides conceptually with setuptools
  `[project.scripts]` "entry points"** in the same `pyproject.toml`.
  → **Mitigation:** D1 records the distinction; no runtime ambiguity (one is a
  package path, the other is a packaging declaration).

## Migration Plan

This is a single-change, code-and-spec migration. Steps (detailed in tasks.md):

1. Create `yascheduler/entrypoints/` package with `__init__.py` facade and the
   moved `client.py` (full implementation + GRACE-lite contracts, FIXME removed).
2. Replace `yascheduler/client.py` with the compat shim (full MODULE_CONTRACT).
3. Update `yascheduler/__init__.py`: import `from .entrypoints import Yascheduler`
   AND update the source-file `MODULE_CONTRACT` `DEPENDS` field from
   `M-CLIENT, M-SHARED` to `M-ENTRYPOINTS, M-SHARED`.
4. Update `pyproject.toml` `[tool.importlinter]` `layers` (add `entrypoints` on
   top).
5. Update the 3 test files (patch paths + import paths).
6. Update `docs/knowledge-graph.xml`: rename `M-CLIENT` → `M-ENTRYPOINTS-CLIENT`
   across all 7 reference sites (M-MAIN.depends, the node itself, 2 DF-* data
   flows, 3 CrossLinks), add `M-ENTRYPOINTS` and `M-CLIENT-SHIM` nodes, add the
   2 new CrossLinks (M-MAIN→M-ENTRYPOINTS, M-CLIENT-SHIM→M-ENTRYPOINTS-CLIENT).
7. Rewrite affected requirements in `openspec/specs/package-facades/spec.md`.
8. Verify: `uv run pytest -m unit`, `uv run lint-imports`, `uv run ruff check .`,
   `uv run ruff format --check .`, `uv run zuban check`,
   `python3 scripts/grace_check.py`, `openspec validate --all --json`.
   Integration/e2e (`uv run pytest -m integration`, `uv run pytest -m e2e`)
   are not required for this change (no DB/SSH behaviour touched) but may be
   run as a smoke check.

**Rollback:** `git revert` the change commit. No data migration, no external
state. The shim makes the change externally invisible, so downstream
consumers need no coordination.

## Open Questions

_None outstanding._ All decisions captured during the explore phase are
resolved in this design. Follow-up changes will address the migration of the
remaining driving adapters into `entrypoints/`.
## Why

`yascheduler/client.py` is a driving adapter (presentation-layer client that calls
application use cases via a DI seam), yet it lives at the package root outside the
`import-linter` layers contract, alongside `di.py`, `aiida_plugin.py`, and the daemon
launchers. The `client.py` file itself carries a `# FIXME: move to adapters/api?`
comment signalling the author already saw the misplacement. Introducing a dedicated
outermost layer — `yascheduler.entrypoints` — gives driving adapters + composition root
a sanctioned home, enforces a clean `entrypoints → infra → application → domain →
shared` direction, and disambiguates driving from driven (the `infra/` layer is
driven-only). This change moves only `client.py` as the first resident; `di.py`,
`aiida_plugin.py`, `daemon_*.py`, and `infra/cli/` are explicitly out of scope and
migrate in follow-up changes.

## What Changes

- Add a new package `yascheduler/entrypoints/` as the outermost hexagonal layer
  (presentation / driving adapters + composition root).
- Move `yascheduler/client.py` → `yascheduler/entrypoints/client.py` (real
  implementation, including `Yascheduler` class, `_task_to_dict`, and all contracts).
- Add `yascheduler/entrypoints/__init__.py` as the layer facade re-exporting
  `Yascheduler` (mirrors `M-ADAPTERS` / `M-APPLICATION` facade pattern).
- Replace `yascheduler/client.py` with a thin compat shim that re-exports `Yascheduler`
  from `yascheduler.entrypoints.client` (`__all__ = ["Yascheduler"]`), preserving the
  deep import path `from yascheduler.client import Yascheduler` for external
  downstream consumers. A plain `from .entrypoints import client` binding in
  `__init__.py` was rejected because it creates a package attribute but does not
  register `yascheduler.client` in `sys.modules`, so the deep import would raise
  `ModuleNotFoundError`; a real shim file is required (see explore-brief.md §Rejected
  alternatives for the empirical justification). `yascheduler.client` is reclassified
  in spec from "composition root" to "compat shim".
- Update `yascheduler/__init__.py` to source `Yascheduler` via
  `from .entrypoints import Yascheduler`.
- Remove the stale `# FIXME: move to adapters/api?` comment.
- Update `[tool.importlinter]` in `pyproject.toml`: add `yascheduler.entrypoints` as
  the top layer; the `forbidden: shared → config` contract is retained unchanged
  (`config` stays outside-layer-set).
- Update test patch sites: `patch("yascheduler.client.Config.from_config_parser")`
  → `patch("yascheduler.entrypoints.client.Config.from_config_parser")` (the shim
  does not re-export `Config`, so patches must target the real module).
- Update test imports: `from yascheduler.client import Yascheduler` →
  `from yascheduler.entrypoints.client import Yascheduler` (tests may import any way;
  these are migrated to the canonical deep path for clarity).
- Update `docs/knowledge-graph.xml`: rename `M-CLIENT` → `M-ENTRYPOINTS-CLIENT`,
  update `<path>`, introduce `M-ENTRYPOINTS` layer-facade node, add `M-CLIENT-SHIM`
  node for the compat shim, and update `M-MAIN` depends/links.
- Rewrite affected requirements in `openspec/specs/package-facades/spec.md`:
  - Layer direction (R3): add `entrypoints` as top layer.
  - Layers contract configuration: new 5-entry `layers = [...]`.
  - Outside-layer-set exemptions: reclassify `yascheduler.client` as compat shim;
    drop stale `yascheduler.db` / `yascheduler.compat` / `yascheduler.variables`
    references (these no longer exist in the codebase).
  - Public API stability: decouple from file path; key on `from yascheduler import
    Yascheduler`.
  - The `forbidden: shared → config` contract is retained unchanged.

### Out of scope (explicit, deferred to follow-up changes)

- `yascheduler/di.py`, `yascheduler/aiida_plugin.py`,
  `yascheduler/daemon_systemd.py`, `yascheduler/daemon_sysv.py`,
  `yascheduler/infra/cli/` — remain at their current locations; migration into
  `entrypoints/` is tracked separately.
- `[project.scripts]` and `[project.entry-points."aiida.schedulers"]` in
  `pyproject.toml` — unchanged (they still point at `infra.cli.*` /
  `aiida_plugin:YaScheduler`).

## Capabilities

### New Capabilities

_None._ The `entrypoints` layer is a structural/architectural concern whose
requirements (layer direction, facade convention, import discipline) are all
expressed as modifications to the existing `package-facades` capability. A
separate `entrypoints-layer` spec would duplicate `package-facades` R2/R3
content; folding the layer into `package-facades` keeps a single source of
truth for the layer contract.

### Modified Capabilities

- `package-facades`: Layer direction (R3) gains `yascheduler.entrypoints` as the
  top layer; `layers` contract configuration is updated to 5 entries;
  `outside-layer-set exemptions` reclassify `yascheduler.client` as a compat shim
  (no longer "composition root") and drop stale module references; `public API
  stability` decouples the `Yascheduler` contract from the file path and keys it
  on `from yascheduler import Yascheduler`; a new requirement documents the
  `entrypoints` layer facade (`yascheduler/entrypoints/__init__.py` re-exports
  `Yascheduler`, mirroring the `M-ADAPTERS` / `M-APPLICATION` facade pattern).
  The `forbidden: shared → config` contract is retained unchanged.

## Impact

- **Code**: new `yascheduler/entrypoints/` package (2 files); `yascheduler/client.py`
  reduced to a compat shim; `yascheduler/__init__.py` import path swap.
- **Tests**: 3 files updated for patch-path and import-path migration
  (`tests/unit/test_client_query.py`, `tests/unit/test_characterization.py`,
  `tests/integration/test_client_query_integration.py`). No behavioural change.
- **External API**: `from yascheduler import Yascheduler` and
  `from yascheduler.client import Yascheduler` both continue to resolve
  (verified empirically). No **BREAKING** change to the public surface.
- **Config**: `pyproject.toml` `[tool.importlinter]` updated.
- **Specs**: `openspec/specs/package-facades/spec.md` rewritten in the affected
  requirements.
- **Knowledge graph**: `docs/knowledge-graph.xml` node rename + additions.
- **Dependencies**: none added or removed.
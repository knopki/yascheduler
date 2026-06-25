## Why

`yascheduler/di.py` (the composition root) is the last outside-layer-set module still living at the package root. Every peer — `client`, `daemon_systemd`, `daemon_sysv`, `aiida_plugin` — already migrated into `yascheduler/entrypoints/` via `add-entrypoints-layer` and `relocate-daemon-launchers`. Both archived changes explicitly deferred `di.py` to a follow-up; `openspec/specs/package-facades/spec.md` L264 carries the standing note "Scheduled for migration into `yascheduler.entrypoints` in a follow-up change; remains at the package root in the interim." This change closes that deferred item.

## What Changes

- **Relocate** `yascheduler/di.py` → `yascheduler/entrypoints/di.py` (composition root joins the entrypoints layer).
- **Rewrite internal imports** in `di.py`: relative `.application` / `.domain` / `.infra` → absolute via layer facades `yascheduler.application` / `yascheduler.domain` / `yascheduler.infra` (required because the module is no longer at the package root; R2-correct).
- **Extend the `yascheduler.entrypoints` facade** (`entrypoints/__init__.py`) to re-export `make_daemon`, `make_cli_deps`, `CLIDeps` alongside the existing `Yascheduler`. **BREAKING** for any external importer of `from yascheduler.di import …` — there is no compat shim, because `di` is not public API (no `[project.scripts]` entry exposes it; only `entrypoints/client.py` is public API and already has its own `yascheduler/client.py` shim).
- **Rewrite consumer imports** (6 production files): `entrypoints/cli/{daemon_common,submit,check_status,show_nodes,manage_node}.py` switch to `from yascheduler.entrypoints import …` (via the layer facade); `entrypoints/client.py` switches to `from .di import CLIDeps, make_cli_deps` (sibling-relative, R1).
- **Rewrite test imports** (7 files): `from yascheduler.di import …` → `from yascheduler.entrypoints.di import …`, and ~12 `patch("yascheduler.di.X")` targets in `tests/unit/test_di.py` → `patch("yascheduler.entrypoints.di.X")`.
- **Update OpenSpec specs** (decision-level, in this change):
  - `package-facades`: remove `yascheduler.di` from the outside-layer-set enumeration; replace the "Scheduled for migration" paragraph with the completed fact; update facade consumer descriptions; clean the stale R2 carve-out for `_resolve_adapter` (the symbol was renamed to public `resolve_adapter` in a prior `review-hardening` change and is now imported via the `infra` facade).
  - `dependency-injection`: rename the "DI factories in yascheduler.di" requirement to `yascheduler.entrypoints.di`; update path references in scenarios.
  - `test-db-integration`: update the `yascheduler.di.make_cli_deps` patch-path reference.
- **Update GRACE artifacts**: `docs/knowledge-graph.xml` `<path>` for `M-DI` (ID retained, `CrossLink`s unchanged); `docs/ARCHITECTURE.md` §2.8 heading path.
- **No `pyproject.toml` changes**: the `layers` contract already lists `yascheduler.entrypoints` as the top layer, so `entrypoints/di.py` is automatically subject to R3 and its imports (`entrypoints → infra → application → domain`) flow legally.

## Capabilities

### New Capabilities
<!-- none — this is a relocation, no new capability is introduced -->

### Modified Capabilities
- `package-facades`: composition root is no longer in the outside-layer-set; it now lives inside the `yascheduler.entrypoints` layer and is subject to the `layers` contract (R3). The stale R2 carve-out for `_resolve_adapter` is removed (symbol is already public and imported via the `infra` facade).
- `dependency-injection`: the requirement "DI factories in yascheduler.di" is renamed to `yascheduler.entrypoints.di`; path references in requirement bodies and scenarios are updated. Factory signatures and behavior are unchanged.
- `test-db-integration`: the patch-path reference `yascheduler.di.make_cli_deps` is updated to `yascheduler.entrypoints.di.make_cli_deps`.

## Impact

- **Code**: 1 file moved (`di.py`); 6 production consumers rewritten; 7 test files rewritten (import paths + `patch()` targets). No symbol signatures change; no runtime behavior changes.
- **APIs**: The composition-root import path `yascheduler.di` is removed without a shim. This is internal API; the public API surface (`Yascheduler` class, CLI entry points in `[project.scripts]`) is unchanged.
- **Dependencies**: none added or removed.
- **Config**: `pyproject.toml` unchanged (the `layers` contract already covers `entrypoints`).
- **GRACE**: `M-DI` knowledge-graph entry gets an updated `<path>`; `M-DI` `<depends>` is unchanged (di.py gains no new dependencies, it only moves); all `CrossLink` references to `M-DI` are unchanged; `MODULE_CONTRACT` / `MODULE_MAP` / `CHANGE_SUMMARY` inside the moved `di.py` are updated; `entrypoints/__init__.py` MODULE_CONTRACT and CHANGE_SUMMARY are updated.
- **Active changes**: `schema-migrations` (in-progress) does not touch `di.py` or `yascheduler.di` (verified); `queue-dataclass-migration` is archived (2026-06-25) and also did not touch `di.py`; no conflict.
- **Compatibility**: **BREAKING** for any external importer of `from yascheduler.di import …`. Composition root is by definition internal to the package; no such external importer is known. The two active in-progress changes do not reference this path.
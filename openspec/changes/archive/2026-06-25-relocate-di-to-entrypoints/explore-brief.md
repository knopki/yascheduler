# Explore Brief — relocate-di-to-entrypoints

## Goal

Move the composition root `yascheduler/di.py` to `yascheduler/entrypoints/di.py`.
This closes the last deferred follow-up from `add-entrypoints-layer` and
`relocate-daemon-launchers` (both archived): every other outside-layer-set
module (`client`, `daemon_systemd`, `daemon_sysv`, `aiida_plugin`) already
migrated into `entrypoints/`. `di.py` is the only one left at the package root.

## Alternatives Rejected

- **Split into `entrypoints/cli/deps.py` + `entrypoints/daemon/deps.py`** —
  rejected. `client.py` (public API, not a CLI) consumes `CLIDeps` and
  `make_cli_deps`; splitting would force the public client to import from
  `entrypoints/cli/`, cementing "client is CLI-over-async". Also the two
  factories share logic (`_setup_domain_events`, `PostgresUnitOfWork`
  construction), so a split duplicates or requires a `_common.py`.
- **Keep a compat shim at `yascheduler/di.py` re-exporting from
  `entrypoints/di.py`** — rejected. `di.py` is NOT public API (no
  `[project.scripts]` entry exposes it; `entrypoints/client.py` is the public
  API and already has its own compat shim `yascheduler/client.py`). Composition
  root is internal to the package. Adding a shim violates YAGNI and runs against
  the recent trend of removing root-level compat modules.
- **Lift `CLIDeps` to a domain port in `application/`** — rejected. The
  `Yascheduler.deps_factory` seam (per `dependency-injection/spec.md`) already
  provides the test substitution point. A second abstraction earns nothing.
- **Variant with `entrypoints/daemon/` subpackage** — not applicable; that
  subpackage was liquidated in `relocate-daemon-launchers`. The daemon entry
  lives at `entrypoints/cli/daemon_common.py` + `entrypoints/cli/daemonize.py`.

## Final Approach — Flat Relocation

### Physical move

- `git mv yascheduler/di.py → yascheduler/entrypoints/di.py`
- Update `# FILE:` header and `START_CHANGE_SUMMARY` inside the module.
- Internal imports in `di.py` change from relative (`.application`,
  `.domain`, `.infra`) to absolute-via-facades (`yascheduler.application`,
  `yascheduler.domain`, `yascheduler.infra`). This is R2-correct (all three
  are layer facades) and required because `di.py` no longer lives at the
  package root.

### Consumer import rewrites (6 production files)

| File | Before | After |
|------|--------|-------|
| `entrypoints/cli/daemon_common.py` | `from yascheduler.di import make_daemon` | `from yascheduler.entrypoints import make_daemon` |
| `entrypoints/cli/submit.py` | `from yascheduler.di import make_cli_deps` | `from yascheduler.entrypoints import make_cli_deps` |
| `entrypoints/cli/check_status.py` | `from yascheduler.di import make_cli_deps` + `CLIDeps` | `from yascheduler.entrypoints import make_cli_deps, CLIDeps` |
| `entrypoints/cli/show_nodes.py` | `from yascheduler.di import make_cli_deps` | `from yascheduler.entrypoints import make_cli_deps` |
| `entrypoints/cli/manage_node.py` | `from yascheduler.di import make_cli_deps` + `CLIDeps` | `from yascheduler.entrypoints import make_cli_deps, CLIDeps` |
| `entrypoints/client.py` | `from yascheduler.di import CLIDeps, make_cli_deps` | `from .di import CLIDeps, make_cli_deps` (sibling-relative, R1) |

### `entrypoints/__init__.py` facade extension

Currently re-exports only `Yascheduler` (`__all__ = ["Yascheduler"]`).
Add: `make_daemon`, `make_cli_deps`, `CLIDeps` (imported from `.di`).
Update `MODULE_MAP`, `LINKS`, `CHANGE_SUMMARY` (remove "only di.py remains
deferred" line), bump VERSION.

### Test rewrites (8 files)

| File | Change |
|------|--------|
| `tests/unit/test_di.py` | import path `yascheduler.di` → `yascheduler.entrypoints.di`; ~12 `patch("yascheduler.di.X")` targets → `yascheduler.entrypoints.di.X`; `import yascheduler.di as di_module` → `import yascheduler.entrypoints.di as di_module` |
| `tests/unit/test_cli_behavioral.py` | `from yascheduler.di import CLIDeps` → `from yascheduler.entrypoints.di import CLIDeps` (test is outside the package → absolute) |
| `tests/unit/test_cli_check_status.py` | same |
| `tests/unit/test_cli_manage_node.py` | same |
| `tests/unit/test_cli_show_nodes.py` | same |
| `tests/unit/test_cli_submit.py` | same |
| `tests/e2e/test_full_cycle.py` | `from yascheduler.di import make_cli_deps, make_daemon` → `from yascheduler.entrypoints.di import …` |

`test_di.py` filename: **kept** (neutral; does not encode a path; rename is
pure aesthetics and out of scope).

### OpenSpec spec edits (decision-level — must be in this change)

1. `openspec/specs/package-facades/spec.md`:
   - L14, L73, L264, L271, L274: remove `yascheduler.di` from the
     outside-layer-set enumeration. After the move, `entrypoints/di.py` is
     inside the `yascheduler.entrypoints` layer (top of `layers` contract in
     `pyproject.toml` L126) and is subject to R3 — its imports flow
     `entrypoints → infra → application → domain`, fully legal.
   - Replace the "Scheduled for migration … in the interim" paragraph (L264)
     with a statement that composition root now lives at
     `yascheduler.entrypoints.di` and is layer-checked.
   - L380-389, L397, L404: update "consumed by the composition root
     `yascheduler.di`" → `yascheduler.entrypoints.di` in the facade consumer
     descriptions.
   - L436: stale R2 carve-out for `_resolve_adapter` — symbol was renamed to
     public `resolve_adapter` in a prior change (`review-hardening`) and is
     now imported by `di.py` via `from yascheduler.infra import
     resolve_adapter` (facade). The carve-out paragraph is outdated; remove
     or rewrite it to reflect the current public import.

2. `openspec/specs/dependency-injection/spec.md`:
   - L38, L67, L69, L73: `yascheduler.di` → `yascheduler.entrypoints.di` in
     requirement title and scenarios.

3. `openspec/specs/test-db-integration/spec.md`:
   - L93: patch path `yascheduler.di.make_cli_deps` →
     `yascheduler.entrypoints.di.make_cli_deps`.

### GRACE knowledge graph

`docs/knowledge-graph.xml`: keep `M-DI` ID (preserves all `CrossLink`
references unchanged); update `<path>yascheduler/di.py</path>` →
`<path>yascheduler/entrypoints/di.py</path>`. `<depends>` on M-DI is
unchanged — di.py does not gain new dependencies, it only moves.

### `docs/ARCHITECTURE.md`

§2.8 heading: `### 2.8 Composition Root (yascheduler/di.py)` →
`### 2.8 Composition Root (yascheduler/entrypoints/di.py)`.

### `pyproject.toml`

No changes. The `layers` contract already lists `yascheduler.entrypoints`
(L126) as the top layer; `entrypoints/di.py` is automatically covered. The
outside-layer-set enumeration lives in the spec, not in the config.

## Cross-Module Data Flows (unchanged semantics)

- `daemon_common.make_daemon_entry` → `yascheduler.entrypoints.make_daemon`
  (via facade) → `Orchestrator(…)` wired with `PostgresUnitOfWork`,
  `SSHMachineGateway`, `CloudProvisionerImpl`, `AllocationTracker`,
  `MessageBus` + webhook handlers.
- `cli/{submit,check_status,show_nodes,manage_node}` →
  `yascheduler.entrypoints.make_cli_deps` (via facade) → `CLIDeps` with
  `uow_factory`, `engines`, `remote_tasks_dir`.
- `entrypoints/client.Yascheduler` → `from .di import CLIDeps, make_cli_deps`
  (sibling-relative) → same `CLIDeps` used as default `deps_factory`.

The only thing that changes is import paths. No runtime behavior, no symbol
signatures, no dependencies.

## Open Questions

None. All decisions captured during explore mode:
- E1 facade exports = `{Yascheduler, make_daemon, make_cli_deps, CLIDeps}`
- E2 stale `_resolve_adapter` carve-out to be cleaned
- E3 internal imports → absolute via facades
- E4 no conflict: `schema-migrations` (in-progress) and `queue-dataclass-migration` (archived 2026-06-25) both do not mention `di.py` or `yascheduler.di` (verified)
- E5 `test_di.py` filename kept
- E6 ARCHITECTURE.md §2.8 path updated
- E7 `M-DI` id retained, path updated
- E8 `M-DI` `<depends>` unchanged (distinct from CrossLinks)
- E9 `entrypoints/__init__.py` CHANGE_SUMMARY updated
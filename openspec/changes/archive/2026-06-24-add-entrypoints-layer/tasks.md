## 1. Create the entrypoints package

- [x] 1.1 Create `yascheduler/entrypoints/__init__.py` as the layer facade: `from .client import Yascheduler` with `__all__ = ["Yascheduler"]`. Add a brief comment noting the layer's interim state (only `client.py` resident; `di.py`, `aiida_plugin.py`, `daemon_*.py`, `infra/cli/` migrate in follow-up changes).
- [x] 1.2 Move `yascheduler/client.py` → `yascheduler/entrypoints/client.py` (preserve the full file: implementation, `Yascheduler` class, `_task_to_dict`, all GRACE-lite contracts). Update `# FILE:` header path to `yascheduler/entrypoints/client.py`. Remove the `# FIXME: move to adapters/api?` comment. Bump `VERSION` in the header and add a `START_CHANGE_SUMMARY` entry describing the relocation.
- [x] 1.3 Update the 5 relative imports in `yascheduler/entrypoints/client.py` to absolute facade paths (they currently resolve against `yascheduler.client.*` and would break as `yascheduler.entrypoints.client.*` after the move):
  - `from .application import query_tasks` → `from yascheduler.application import query_tasks`
  - `from .config import Config` → `from yascheduler.config import Config`
  - `from .di import CLIDeps, make_cli_deps` → `from yascheduler.di import CLIDeps, make_cli_deps`
  - `from .domain import Task, TaskStatus` → `from yascheduler.domain import Task, TaskStatus`
  - `from .shared import CONFIG_FILE, to_sync` → `from yascheduler.shared import CONFIG_FILE, to_sync`
  These are all R2-compliant cross-package facade imports (`yascheduler.application`, `yascheduler.config`, etc.).

## 2. Replace yascheduler/client.py with compat shim

- [x] 2.1 Replace `yascheduler/client.py` with a thin compat shim: `from yascheduler.entrypoints.client import Yascheduler` and `__all__ = ["Yascheduler"]`. Add a full GRACE-lite `MODULE_CONTRACT` block whose `PURPOSE` states: "Compat shim re-exporting Yascheduler from yascheduler.entrypoints.client; real implementation lives in entrypoints/client.py." Include `START_MODULE_MAP` (only `Yascheduler`) and `START_CHANGE_SUMMARY` entries.
- [x] 2.2 Verify the shim does NOT re-export `Config` or any other symbol (only `Yascheduler`).

## 3. Update package facade

- [x] 3.1 Update `yascheduler/__init__.py`: change `from .client import Yascheduler` → `from .entrypoints import Yascheduler`. Update the `# FILE:` / `MODULE_CONTRACT DEPENDS` field from `M-CLIENT, M-SHARED` → `M-ENTRYPOINTS, M-SHARED`. Bump `VERSION` and add a `START_CHANGE_SUMMARY` entry.

## 4. Update import-linter config

- [x] 4.1 In `pyproject.toml`, update the `[[tool.importlinter.contracts]]` `layers` entry: add `"yascheduler.entrypoints"` as the first element, yielding `layers = ["yascheduler.entrypoints", "yascheduler.infra", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`. Leave the `forbidden` contract unchanged.

## 5. Update test call sites

- [x] 5.1 `tests/unit/test_client_query.py`: change `from yascheduler.client import Yascheduler` → `from yascheduler.entrypoints.client import Yascheduler`; change `patch("yascheduler.client.Config.from_config_parser")` → `patch("yascheduler.entrypoints.client.Config.from_config_parser")` (2 sites: lines ~109, ~191).
- [x] 5.2 `tests/unit/test_characterization.py`: change `from yascheduler.client import Yascheduler` → `from yascheduler.entrypoints.client import Yascheduler`; change `patch("yascheduler.client.Config.from_config_parser")` → `patch("yascheduler.entrypoints.client.Config.from_config_parser")` (line ~31).
- [x] 5.3 `tests/integration/test_client_query_integration.py`: change `from yascheduler.client import Yascheduler` → `from yascheduler.entrypoints.client import Yascheduler` (line ~32). No patch sites in this file.
- [x] 5.4 Run `rg "yascheduler\.client"` across `tests/` and `examples/` to confirm zero remaining references to the old deep path (except in the shim file itself). Confirm `examples/*.py` use `from yascheduler import Yascheduler` (the package facade) and need no changes.
- [x] 5.5 Update the `MODULE_CONTRACT DEPENDS` field in the 3 affected test files if it references `M-CLIENT` (cosmetic — tests are out-of-graph, but the reference would be stale after the rename to `M-ENTRYPOINTS-CLIENT` / `M-CLIENT-SHIM`).

## 6. Update knowledge graph

- [x] 6.1 In `docs/knowledge-graph.xml`, rename the `<M-CLIENT ...>` element (lines ~41-56) → `<M-ENTRYPOINTS-CLIENT NAME="Client API" TYPE="ENTRY_POINT" STATUS="implemented">`; update `<path>` to `yascheduler/entrypoints/client.py`; update `<depends>` to reflect the new layer (e.g. `M-SHARED, M-CONFIG, M-DI, M-DOMAIN-MODEL, M-APPLICATION-QUERY-TASKS` — unchanged content, just under the new ID).
- [x] 6.2 Add `<M-ENTRYPOINTS NAME="Entrypoints layer facade" TYPE="ENTRY_POINT" STATUS="implemented">` with `<path>yascheduler/entrypoints/__init__.py</path>`, `<depends>M-ENTRYPOINTS-CLIENT</depends>`, and an `<annotations>` block re-exporting `Yascheduler`.
- [x] 6.3 Add `<M-CLIENT-SHIM NAME="Client compat shim" TYPE="UTILITY" STATUS="implemented">` with `<path>yascheduler/client.py</path>`, `<depends>M-ENTRYPOINTS-CLIENT</depends>`, `<annotations><export-Yascheduler PURPOSE="Compat re-export of Yascheduler from entrypoints.client" /></annotations>`.
- [x] 6.4 Update `M-MAIN` (lines ~17-28): change `<depends>M-CLIENT, M-SHARED</depends>` → `<depends>M-ENTRYPOINTS, M-SHARED</depends>`. Verify `LINKS` and annotations still resolve.
- [x] 6.5 Remove the spurious `LINKS: M-CLIENT` reference in `yascheduler/aiida_plugin.py`'s MODULE_CONTRACT (line ~8): set `LINKS: none`. The plugin does not import the yascheduler client (talks to it via SSH/transport); the link was always factually wrong. (The `<CrossLink from="M-AIIDA" to="M-CLIENT">` at line ~861 is handled separately in task 6.7(b).)
- [x] 6.6 Update the data-flow entry `DF-SUBMIT` (line ~847) `M-CLIENT -> ...` → `M-ENTRYPOINTS-CLIENT -> ...`; DELETE `DF-AIIDA-INTEGRATION` (line ~850) — the `M-AIIDA -> M-CLIENT` data flow does not exist at the code level.
- [x] 6.7 Update the `CrossLink` entries referencing `M-CLIENT`: (a) line ~859 `from="M-CLIENT" to="M-APPLICATION-QUERY-TASKS"` → `from="M-ENTRYPOINTS-CLIENT"`; (b) DELETE line ~861 `from="M-AIIDA" to="M-CLIENT"` — spurious edge, plugin does not import client; (c) line ~902 `from="M-CLIENT" to="M-DI"` → `from="M-ENTRYPOINTS-CLIENT"`.
- [x] 6.8 Add 2 new `CrossLink` entries: `<CrossLink from="M-MAIN" to="M-ENTRYPOINTS" relation="re-exports Yascheduler via layer facade" />` and `<CrossLink from="M-CLIENT-SHIM" to="M-ENTRYPOINTS-CLIENT" relation="compat re-export of Yascheduler" />`.
- [x] 6.9 Run `rg -n "M-CLIENT" docs/knowledge-graph.xml` and confirm zero remaining bare `M-CLIENT` references (only `M-ENTRYPOINTS-CLIENT` and `M-CLIENT-SHIM` should appear).

## 7. Rewrite affected requirements in package-facades spec

- [x] 7.1 Apply the delta spec `openspec/changes/add-entrypoints-layer/specs/package-facades/spec.md` to the main spec `openspec/specs/package-facades/spec.md`: the 2 ADDED requirements ("Entrypoints layer facade", "Compat shim for yascheduler.client") and the 5 MODIFIED requirements ("Layer direction (R3)", "Outside-layer-set exemptions", "Layers contract configuration", "Public API stability", "Yascheduler client query method public contract") replace the corresponding existing requirements in place. (This task is executed at archive time per OpenSpec workflow; confirm the delta is complete and validates.)
- [x] 7.2 Run `openspec validate --all --json` and confirm `valid: true` for all items.

## 8. Verification

- [x] 8.1 `uv run pytest -m unit` — confirm all unit tests pass (especially `tests/unit/test_client_query.py` and `tests/unit/test_characterization.py` after the patch-path migration).
- [x] 8.2 `uv run lint-imports` — confirm the `layers` contract passes with the new 5-entry `layers` list and the `forbidden: shared → config` contract still passes.
- [x] 8.3 `uv run ruff check .` — confirm no lint errors.
- [x] 8.4 `uv run ruff format --check .` — confirm no formatting violations.
- [x] 8.5 `uv run zuban check` — confirm static analysis passes.
- [x] 8.6 `python3 scripts/grace_check.py` — confirm knowledge-graph XML + source MODULE_CONTRACT checks pass (including the new `M-ENTRYPOINTS`, `M-ENTRYPOINTS-CLIENT`, `M-CLIENT-SHIM` nodes and the updated CrossLinks/DF entries).
- [x] 8.7 `openspec validate --all --json` — confirm all specs validate.
- [x] 8.8 Smoke check: `python3 -c "from yascheduler import Yascheduler; from yascheduler.client import Yascheduler as Y2; from yascheduler.entrypoints import Yascheduler as Y3; assert Yascheduler is Y2 is Y3; print('all import paths resolve to same class')"` — confirm all three import forms resolve to the same class object.
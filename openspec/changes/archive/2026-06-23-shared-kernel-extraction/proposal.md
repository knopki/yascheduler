## Why

The top level of the `yascheduler/` package is a legacy accumulator that mixes entry points (`client.py`, `daemon_*.py`, `aiida_plugin.py`), legacy data layer (`db.py`), a domain value object (`webhook.py`), and genuine cross-cutting utilities (`compat.py`, `variables.py`, `time.py`, `queue.py`) with no discipline. The `package-facades` spec already lists `yascheduler.compat` as an outside-layer-set module — but it lives at the root alongside `client.py` (an ENTRY_POINT that also exports `to_sync`, which five `adapters/cli/*` modules then import from a sibling entry point). This couples adapters to a sibling entry point for a utility, and lets shared utilities accrete at the root with no contract. The fix is a dedicated `yascheduler.shared/` subpackage added as the 4th (bottom) layer in the `layers` contract — hard-enforcing that shared utilities never import from adapters/application/domain — with a separate `forbidden` contract preventing an import cycle with `yascheduler.config`.

## What Changes

- Create `yascheduler/shared/` subpackage as the project's **shared kernel** — the only home for cross-layer utilities (typing shims, runtime helpers, process-global path constants).
- **Move** `yascheduler/compat.py` → `yascheduler/shared/compat.py` (content unchanged: `Self`, `ParamSpec`).
- **Extract** `to_sync` from `yascheduler/client.py` → `yascheduler/shared/async_utils.py` (new file, same body). `client.py` keeps `Yascheduler` and `_task_to_dict` only; `to_sync` is no longer defined there.
- **Move** `yascheduler/variables.py` → `yascheduler/shared/variables.py` (content unchanged: `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`).
- Create `yascheduler/shared/__init__.py` as the lazy-publication facade re-exporting exactly what consumers need: `Self`, `ParamSpec`, `to_sync`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`.
- Update every consumer's import path to use the shared facade (`from yascheduler.shared import ...`). ~15 files: `__init__.py`, `client.py`, `config/{cloud,engine_repository,remote}.py`, `db.py`, `daemon_systemd.py`, `daemon_sysv.py`, `adapters/cli/{submit,daemonize,show_nodes,init,check_status,manage_node}.py`, plus tests.
- **No backward-compat shims** at old paths (`yascheduler/compat.py`, `yascheduler/variables.py`). Both are explicitly internal per the existing `package-facades` spec ("`yascheduler.compat` SHALL remain internal (not public surface)"), so removing the old paths is not a public API break.
- Update `pyproject.toml` `[tool.importlinter]`: add `yascheduler.shared` as the 4th (bottom) layer in the `layers` contract (`["yascheduler.adapters", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`), and add a second contract of type `forbidden` with `source_modules = ["yascheduler.shared"]` and `forbidden_modules = ["yascheduler.config"]`. The `layers` contract enforces that `yascheduler.shared` imports nothing from `adapters`/`application`/`domain`. The `forbidden` contract enforces that `yascheduler.shared` does not import from `yascheduler.config` (the one outside-layer-set module that creates a real import-cycle risk: `config` already imports `shared.Self` today, so the reverse edge would close a cycle). Other outside-layer-set modules (`data`, `di`, `client`, `db`, `aiida_plugin`) are not in `forbidden_modules` — the practical risk of `shared` importing an entry point or the legacy DB layer is negligible, and the user explicitly scoped `forbidden_modules` to `yascheduler.config` only.
- Update GRACE-lite knowledge graph: remove `M-COMPAT` and `M-VARIABLES` module entries, remove `fn-to_sync` from `M-CLIENT`, add a single `M-SHARED` module with the relocated annotations; update `<depends>` on `M-MAIN`, `M-CLIENT`, `M-DAEMON-SYSTEMD`, `M-DAEMON-SYSV`, `M-CLI-COMMANDS`, `M-DB`, `M-CONFIG-CLOUD`, `M-CONFIG-REMOTE`, `M-CONFIG-ENGINE-REPO` (replace `M-COMPAT`/`M-VARIABLES` with `M-SHARED`).

## Capabilities

### New Capabilities

_None._ The shared kernel does not introduce a new spec-worthy capability; it is an internal structural relocation governed by the existing `package-facades` discipline. A new "shared-kernel" spec would duplicate the outside-layer-set rules already in `package-facades`.

### Modified Capabilities

- `package-facades`: The "Outside-layer-set exemptions" requirement changes: `yascheduler.compat` (the only shared-utility module listed individually today) is removed from the outside-layer-set list. `yascheduler.shared` is added as a **4th (bottom) layer** in the `layers` contract, NOT as an outside-layer-set module — meaning `yascheduler.shared` SHALL NOT import from `adapters`/`application`/`domain`, enforced by `import-linter`. A new `forbidden` contract additionally forbids `yascheduler.shared → yascheduler.config` to prevent import cycles (`config` depends on `shared` via `Self`; the reverse edge must be blocked). `yascheduler.shared.compat` and `yascheduler.shared.variables` are submodules of this new layer; the outside-layer-set exemption no longer applies to them. A new clause SHALL state that `yascheduler.shared` MUST NOT contain business logic, domain types, or I/O (defense-in-depth beyond the layer-direction enforcement). The "Public API stability" requirement is updated to note that `yascheduler/__init__.py` path constants (`CONFIG_FILE`, `LOG_FILE`, `PID_FILE`) remain resolvable via re-export through `yascheduler.shared.variables` (no downstream-visible change).

## Impact

- **Code**:
  - `yascheduler/shared/__init__.py` — new facade (lazy publication: `Self`, `ParamSpec`, `to_sync`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`).
  - `yascheduler/shared/compat.py` — moved from `yascheduler/compat.py` (GRACE-lite contract: update `FILE`/`LINKS`).
  - `yascheduler/shared/async_utils.py` — new file (body extracted from `client.py`).
  - `yascheduler/shared/variables.py` — moved from `yascheduler/variables.py` (GRACE-lite contract: update `FILE`/`LINKS`).
  - `yascheduler/client.py` — remove `to_sync` definition and `from .compat import ParamSpec`; add `from yascheduler.shared import ParamSpec, to_sync`. Update MODULE_MAP / MODULE_CONTRACT / CHANGE_SUMMARY.
  - `yascheduler/__init__.py` — change `from .variables import ...` → `from yascheduler.shared import CONFIG_FILE, LOG_FILE, PID_FILE`. Update MODULE_CONTRACT `DEPENDS` (`M-VARIABLES` → `M-SHARED`).
  - `yascheduler/config/{cloud,engine_repository,remote}.py`, `yascheduler/db.py` — `from yascheduler.compat import Self` → `from yascheduler.shared import Self`.
  - `yascheduler/daemon_systemd.py`, `yascheduler/daemon_sysv.py` — `from .variables import ...` → `from yascheduler.shared import LOG_FILE, PID_FILE`.
  - `yascheduler/adapters/cli/{submit,daemonize,show_nodes,init,check_status,manage_node}.py` — `from yascheduler.client import to_sync` → `from yascheduler.shared import to_sync`; `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
  - `tests/unit/test_message_bus.py` — `from yascheduler.compat import Self` → `from yascheduler.shared import Self`.
  - Delete `yascheduler/compat.py` and `yascheduler/variables.py`.
  - `pyproject.toml` — extend `[tool.importlinter]` `layers` contract `layers` list from `["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]` to `["yascheduler.adapters", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`; add a second `[[tool.importlinter.contracts]]` entry of type `forbidden` with `name = "Shared kernel has no config imports"`, `source_modules = ["yascheduler.shared"]`, `forbidden_modules = ["yascheduler.config"]`.
- **Knowledge graph**: `docs/knowledge-graph.xml` — remove `M-COMPAT`, `M-VARIABLES`; add `M-SHARED` (`TYPE="UTILITY"`, `STATUS="implemented"`, `depends=none`) with annotations `fn-to_sync`, `type-Self`, `type-ParamSpec`, `const-CONFIG_FILE`, `const-PID_FILE`, `const-LOG_FILE`; update `<depends>` on `M-MAIN`, `M-CLIENT`, `M-DAEMON-SYSTEMD`, `M-DAEMON-SYSV`, `M-CLI-COMMANDS`, `M-DB`, `M-CONFIG-CLOUD`, `M-CONFIG-REMOTE`, `M-CONFIG-ENGINE-REPO` (replace `M-VARIABLES`/`M-COMPAT` with `M-SHARED`); remove `fn-to_sync` from `M-CLIENT.annotations`.
- **Specs**: `openspec/specs/package-facades/spec.md` — delta modifying the "Layer direction (R3)" requirement (add `yascheduler.shared` as 4th bottom layer), "Outside-layer-set exemptions" requirement (remove `yascheduler.compat`), "Layers contract configuration" requirement (add the `forbidden` contract alongside the `layers` contract), and "Public API stability" requirement.
- **Dependencies**: none new. No new dev dependency, no new runtime dependency. (`import-linter` is already a dev dependency at `>=2.5,<2.6`; both `layers` and `forbidden` contract types are supported in this version.)
- **Public API**: no breaking changes. `yascheduler/__init__.py` exports remain resolvable (`Yascheduler`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE`, `__version__`). `yascheduler.compat` and `yascheduler.variables` are explicitly internal per the existing spec — path changes are not public API breaks.
- **CI**: no new check. `lint-imports` continues to run; now enforces both R3 layer direction (with `yascheduler.shared` as the bottom 4th layer) and the `forbidden` contract blocking `yascheduler.shared → yascheduler.config`. Existing `ruff check`, `zuban check`, `grace_check.py`, `pytest` unchanged.
- **Out of scope**:
  - Moving `yascheduler/time.py` and `yascheduler/queue.py` — these have a single consumer (`application/orchestrator`) and should move INTO `application/` as private modules, not into shared kernel. Separate change.
  - Moving `yascheduler/webhook.py` (domain value object candidate) — separate analysis.
  - Deleting `yascheduler/db.py` (legacy, scheduled separately).
  - Trimming `yascheduler/adapters/ssh/platform/__init__.py` (180-line over-export — pre-existing smell, separate change).
  - Backward-compat re-export shims at old paths — explicitly rejected; internal modules, no compat layer per AGENTS.md.
  - Hard-enforcing R2 (facade-only imports) for `yascheduler.shared` via an additional `import-linter` contract — R2 stays convention + spec, only R3 (layer direction) and the `shared → config` cycle-prevention are hard-enforced.
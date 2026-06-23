## 1. Create yascheduler/shared/ subpackage

- [x] 1.1 Create `yascheduler/shared/__init__.py` with facade re-exporting `Self`, `ParamSpec`, `to_sync`, `CONFIG_FILE`, `LOG_FILE`, `PID_FILE` from submodules; include `__all__` listing all six. Add GRACE-lite MODULE_CONTRACT (PURPOSE: shared kernel for cross-layer utilities; SCOPE: facade re-exports; DEPENDS: none; LINKS: M-SHARED), MODULE_MAP, CHANGE_SUMMARY (v1.6.0 — Initial extraction from top-level compat/variables/client.to_sync). Create `yascheduler/shared/compat.py` by moving the body of `yascheduler/compat.py` verbatim (version-dependent `Self`/`ParamSpec` imports, `__all__`). Update GRACE-lite `FILE` header to `yascheduler/shared/compat.py`, `LINKS: M-SHARED`. Keep VERSION 1.6.0, add CHANGE_SUMMARY entry "v1.6.0 — Moved from yascheduler/compat.py to yascheduler/shared/compat.py".
- [x] 1.3 Create `yascheduler/shared/async_utils.py` with the `to_sync` function body moved verbatim from `yascheduler/client.py` (lines 43–65: `to_sync` decorator with `ThreadPoolExecutor` and event-loop detection). Add GRACE-lite MODULE_CONTRACT (PURPOSE: async-to-sync runtime bridge; SCOPE: to_sync decorator; DEPENDS: none; LINKS: M-SHARED), MODULE_MAP (`to_sync - Decorator wrapping async functions for sync execution`), CHANGE_SUMMARY (v1.6.0 — Initial extraction from yascheduler/client.py). Import `ParamSpec` from `.compat` and `ReturnT_co` TypeVar defined in-file.
- [x] 1.4 Create `yascheduler/shared/variables.py` by moving the body of `yascheduler/variables.py` verbatim (`CONFIG_FILE`, `LOG_FILE`, `PID_FILE` env-derived constants). Update GRACE-lite `FILE` header to `yascheduler/shared/variables.py`, `LINKS: M-SHARED`. Keep VERSION 1.6.0, add CHANGE_SUMMARY entry "v1.6.0 — Moved from yascheduler/variables.py to yascheduler/shared/variables.py".

## 2. Update consumers to import from yascheduler.shared facade

- [x] 2.1 `yascheduler/__init__.py`: change `from .variables import CONFIG_FILE, LOG_FILE, PID_FILE` → `from yascheduler.shared import CONFIG_FILE, LOG_FILE, PID_FILE`. Update MODULE_CONTRACT `DEPENDS` (`M-VARIABLES` → `M-SHARED`) and `LINKS`. Bump CHANGE_SUMMARY.
- [x] 2.2 `yascheduler/client.py`: remove `to_sync` definition (lines 43–65) and the `ReturnT_co`/`ParamT`/`ParamSpec`-related TypeVars and imports (they are used only by `to_sync` and move with it to `async_utils.py`); remove `from .compat import ParamSpec`; remove `from .variables import CONFIG_FILE`; add `from yascheduler.shared import to_sync, CONFIG_FILE`. Update MODULE_MAP (remove `to_sync` entry), MODULE_CONTRACT `DEPENDS` (`M-VARIABLES, M-COMPAT` → `M-SHARED`), CHANGE_SUMMARY (v2.4.0 — Extract to_sync to yascheduler.shared.async_utils; import to_sync/CONFIG_FILE from yascheduler.shared; ParamSpec/ParamT/ReturnT_co move with to_sync).
- [x] 2.3 `yascheduler/config/cloud.py`: change `from yascheduler.compat import Self` → `from yascheduler.shared import Self`. Bump CHANGE_SUMMARY if present.
- [x] 2.4 `yascheduler/config/engine_repository.py`: change `from yascheduler.compat import Self` → `from yascheduler.shared import Self`. Bump CHANGE_SUMMARY if present.
- [x] 2.5 `yascheduler/config/remote.py`: change `from yascheduler.compat import Self` → `from yascheduler.shared import Self`. Bump CHANGE_SUMMARY if present.
- [x] 2.6 `yascheduler/db.py`: change `from .compat import Self` → `from yascheduler.shared import Self`. (db.py is legacy but still imports compat; update the import path, do NOT refactor anything else in db.py.) [SKIPPED — db.py already deleted]
- [x] 2.7 `yascheduler/daemon_systemd.py`: change `from .variables import LOG_FILE` → `from yascheduler.shared import LOG_FILE`. Bump CHANGE_SUMMARY if present.
- [x] 2.8 `yascheduler/daemon_sysv.py`: change `from .variables import LOG_FILE, PID_FILE` → `from yascheduler.shared import LOG_FILE, PID_FILE`. Bump CHANGE_SUMMARY if present.
- [x] 2.9 `yascheduler/adapters/cli/submit.py`: change `from yascheduler.client import to_sync` → `from yascheduler.shared import to_sync`; change `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
- [x] 2.10 `yascheduler/adapters/cli/daemonize.py`: change `from yascheduler.client import to_sync` → `from yascheduler.shared import to_sync`; change `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
- [x] 2.11 `yascheduler/adapters/cli/show_nodes.py`: change `from yascheduler.client import to_sync` → `from yascheduler.shared import to_sync`; change `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
- [x] 2.12 `yascheduler/adapters/cli/init.py`: change `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
- [x] 2.13 `yascheduler/adapters/cli/check_status.py`: change `from yascheduler.client import to_sync` → `from yascheduler.shared import to_sync`; change `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
- [x] 2.14 `yascheduler/adapters/cli/manage_node.py`: change `from yascheduler.client import to_sync` → `from yascheduler.shared import to_sync`; change `from yascheduler.variables import CONFIG_FILE` → `from yascheduler.shared import CONFIG_FILE`.
- [x] 2.15 `tests/unit/test_message_bus.py`: change `from yascheduler.compat import Self` → `from yascheduler.shared import Self`.

## 3. Delete old paths

- [x] 3.1 Delete `yascheduler/compat.py`.
- [x] 3.2 Delete `yascheduler/variables.py`.

## 4. Update pyproject.toml import-linter config

- [x] 4.1 In `pyproject.toml`, edit the existing `[[tool.importlinter.contracts]]` entry of type `layers`: change `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain"]` to `layers = ["yascheduler.adapters", "yascheduler.application", "yascheduler.domain", "yascheduler.shared"]`. This adds `yascheduler.shared` as the 4th (bottom) layer, hard-enforcing that `shared` imports nothing from `adapters`/`application`/`domain`.
- [x] 4.2 In `pyproject.toml`, add a second `[[tool.importlinter.contracts]]` entry immediately after the `layers` contract:
  ```toml
  [[tool.importlinter.contracts]]
  name = "Shared kernel has no config imports"
  type = "forbidden"
  source_modules = ["yascheduler.shared"]
  forbidden_modules = ["yascheduler.config"]
  ```
  This blocks the `yascheduler.shared → yascheduler.config` reverse edge that would close an import cycle (since `config` already imports `shared.Self`). The `forbidden_modules` list is intentionally scoped to `yascheduler.config` only per user instruction.

## 5. Update GRACE-lite knowledge graph

- [x] 5.1 In `docs/knowledge-graph.xml`: remove `<M-COMPAT NAME="Compatibility" ...>` module block entirely.
- [x] 5.2 In `docs/knowledge-graph.xml`: remove `<M-VARIABLES NAME="Project variables" ...>` module block entirely.
- [x] 5.3 In `docs/knowledge-graph.xml`: add new `<M-SHARED NAME="Shared kernel" TYPE="UTILITY" STATUS="implemented">` module with `<purpose>Shared kernel for cross-layer utilities: typing shims, async-to-sync runtime bridge, process-global path constants.</purpose>`, `<path>yascheduler/shared/__init__.py</path>`, `<depends>none</depends>`, and `<annotations>` containing `fn-to_sync`, `type-Self`, `type-ParamSpec`, `const-CONFIG_FILE`, `const-PID_FILE`, `const-LOG_FILE` (each with PURPOSE attribute).
- [x] 5.4 In `docs/knowledge-graph.xml`: update `<M-MAIN>` `<depends>` from `M-CLIENT, M-VARIABLES` → `M-CLIENT, M-SHARED`; update `<M-MAIN>` `<annotations>` if any `const-CONFIG_FILE`/`const-PID_FILE`/`const-LOG_FILE` annotations reference M-VARIABLES (re-point to M-SHARED or leave as M-MAIN re-exports — keep consistent with existing style).
- [x] 5.5 In `docs/knowledge-graph.xml`: update `<M-CLIENT>` `<depends>` from `M-VARIABLES, M-COMPAT, M-CONFIG, M-DI, M-DOMAIN-MODEL, M-APPLICATION-QUERY-TASKS` → `M-SHARED, M-CONFIG, M-DI, M-DOMAIN-MODEL, M-APPLICATION-QUERY-TASKS`; remove `<fn-to_sync PURPOSE="Decorator converting async function to sync" />` from `<M-CLIENT>` `<annotations>`.
- [x] 5.6 In `docs/knowledge-graph.xml`: update `<M-DAEMON-SYSTEMD>` `<depends>` (replace `M-VARIABLES` → `M-SHARED`); update `<M-DAEMON-SYSV>` `<depends>` (replace `M-VARIABLES` → `M-SHARED`).
- [x] 5.7 In `docs/knowledge-graph.xml`: update `<M-CLI-COMMANDS>` `<depends>` (replace `M-VARIABLES` → `M-SHARED`).
- [x] 5.8 In `docs/knowledge-graph.xml`: update `<M-DB>` `<depends>` (replace `M-COMPAT` → `M-SHARED`). [SKIPPED — M-DB already absent from KG; db.py deleted]
- [x] 5.9 In `docs/knowledge-graph.xml`: update `<M-CONFIG-CLOUD>` `<depends>` (replace `M-COMPAT` → `M-SHARED`); update `<M-CONFIG-REMOTE>` `<depends>` (replace `M-COMPAT` → `M-SHARED`); update `<M-CONFIG-ENGINE-REPO>` `<depends>` (replace `M-COMPAT` → `M-SHARED`).
- [x] 5.10 Run `python3 scripts/grace_check.py` — must exit 0.

## 6. Update spec delta into main spec (after archive)

- [x] 6.1 Confirm `openspec/changes/shared-kernel-extraction/specs/package-facades/spec.md` delta matches the modified requirements in this change (no further edits expected; delta is the source of truth for archive-time sync).

## 7. Verification

- [x] 7.1 Run `uv run pytest -m unit` — must pass (no import errors; `tests/unit/test_cli_smoke.py` `__wrapped__` contract on 5 `@to_sync`-decorated CLI functions still holds; `tests/unit/test_message_bus.py` imports `Self` from new path).
- [x] 7.2 Run `uv run zuban check` — must pass.
- [x] 7.3 Run `uv run ruff check .` — must pass (no unused imports from the move; no F401).
- [x] 7.4 Run `uv run ruff format --check .` — must pass.
- [x] 7.5 Run `uv run lint-imports` — must pass BOTH contracts: (a) the `layers` contract with `yascheduler.shared` as the 4th bottom layer (enforces `shared` imports nothing from `adapters`/`application`/`domain`), AND (b) the new `forbidden` contract blocking `yascheduler.shared → yascheduler.config`. If `lint-imports` reports a violation, it is a real architectural leak — do NOT add `ignore_imports` or expand `forbidden_modules` without explicit decision.
- [x] 7.6 Run `openspec validate --all --json` — must pass.
- [x] 7.7 Run `python3 scripts/grace_check.py` — must exit 0 (re-confirms KG integrity after all code + graph changes).
- [x] 7.8 Smoke check: `python -c "from yascheduler.shared import Self, ParamSpec, to_sync, CONFIG_FILE, LOG_FILE, PID_FILE; print('ok')"` — must print `ok`.
- [x] 7.9 Smoke check: `python -c "from yascheduler import CONFIG_FILE, LOG_FILE, PID_FILE, Yascheduler; print('ok')"` — must print `ok` (public API preserved).
- [x] 7.10 Smoke check: `python -c "import yascheduler.compat"` — must raise `ModuleNotFoundError` (old path removed).
- [x] 7.11 Smoke check: `python -c "import yascheduler.variables"` — must raise `ModuleNotFoundError` (old path removed).
- [x] 7.12 Smoke check: `python -c "from yascheduler.client import to_sync"` — must raise `ImportError` (to_sync no longer defined in client.py). [Achieved by aliasing the internal import as `_to_sync` so `to_sync` is not in client's public namespace.]
- [x] 7.13 Smoke check (negative): temporarily add `from yascheduler.config import ConfigDb` to `yascheduler/shared/__init__.py`, run `uv run lint-imports` — must FAIL with a `forbidden` contract violation. Revert the temporary edit. (Verifies the `forbidden` contract actually enforces the `shared → config` block.) [Verified: contract reported BROKEN — `yascheduler.shared -> yascheduler.config (l.29)`; reverted.]
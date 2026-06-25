## 1. Relocate `variables.py` → `entrypoints/paths.py`

- [x] 1.1 `git mv yascheduler/shared/variables.py yascheduler/entrypoints/paths.py`
- [x] 1.2 In `yascheduler/entrypoints/paths.py`: drop the `# FIXME: is this really shared kernel? decide` line; update `# FILE:` header path; update `START_MODULE_CONTRACT` `LINKS` from `M-SHARED` to `M-ENTRYPOINTS-PATHS` and `PURPOSE` to reflect entrypoints-layer residence; update `START_MODULE_MAP` (unchanged content, keep the three constants); add `START_CHANGE_SUMMARY` entry "<VERSION> - Relocated from yascheduler/shared/variables.py to yascheduler/entrypoints/paths.py (prune-shared-kernel)." (use the project version at merge time; do not hand-edit `pyproject.toml`).

## 2. Inline `to_sync` into `entrypoints/client.py`

- [x] 2.1 In `yascheduler/entrypoints/client.py`: add a local `ParamSpec` import with the `sys.version_info` branch mirroring `yascheduler/shared/compat.py` (import from `typing_extensions` on <3.10, else `typing`); add the `ParamT = ParamSpec("ParamT")` and `ReturnT_co = TypeVar("ReturnT_co", covariant=True)` lines.
- [x] 2.2 Paste the `to_sync` function body (from the former `yascheduler/shared/async_utils.py`) into `yascheduler/entrypoints/client.py` as a module-private helper (keep the name `to_sync` or rename to `_to_sync` — not re-exported either way); preserve its `START_CONTRACT`/`END_CONTRACT` block, updating `LINKS` to `M-ENTRYPOINTS-CLIENT`.
- [x] 2.3 Update the two call sites in `client.py` (`queue_submit_task` ~line 118, `queue_get_tasks` ~line 156) to reference the local helper.
- [x] 2.4 Remove the `from yascheduler.shared import CONFIG_FILE, to_sync` line; add `from .paths import CONFIG_FILE`.
- [x] 2.5 Update `client.py` `MODULE_MAP` (add `to_sync` private-helper entry, remove `to_sync` re-export note), `MODULE_CONTRACT` `DEPENDS` (drop `M-SHARED`, add `M-ENTRYPOINTS-PATHS`), `CHANGE_SUMMARY` ("<VERSION> — Inline to_sync from yascheduler.shared.async_utils; import CONFIG_FILE from .paths; drop yascheduler.shared dependency (prune-shared-kernel).").

## 3. Inline `asleep_until` into `application/orchestrator.py`

- [x] 3.1 In `yascheduler/application/orchestrator.py`: paste the `asleep_until` body as a module-private helper `_asleep_until` (6 lines + early return); preserve its `START_CONTRACT`/`END_CONTRACT` block with `LINKS` updated to `M-APPLICATION-ORCHESTRATOR`.
- [x] 3.2 Update the two call sites (lines ~191, ~450) from `await asleep_until(end_time)` to `await _asleep_until(end_time)`.
- [x] 3.3 Remove `from yascheduler.shared import asleep_until`.
- [x] 3.4 Update `orchestrator.py` `MODULE_MAP` (add `_asleep_until` private-helper entry) and `CHANGE_SUMMARY` ("<VERSION> — Inline asleep_until from yascheduler.shared.async_utils as _asleep_until; drop yascheduler.shared dependency (prune-shared-kernel).").

## 4. Delete `shared/async_utils.py` and prune `shared/compat.py`

- [x] 4.1 `git rm yascheduler/shared/async_utils.py`
- [x] 4.2 In `yascheduler/shared/compat.py`: remove the `ParamSpec` version branch (`if sys.version_info < (3, 10): from typing_extensions import ParamSpec` … `else: from typing import ParamSpec`); keep the `Self`/`Unpack` branch; update `__all__` to `["Self", "Unpack"]`; update `MODULE_CONTRACT` `PURPOSE`/`SCOPE` (drop `ParamSpec`), `MODULE_MAP` (drop `ParamSpec`), `CHANGE_SUMMARY` ("<VERSION> — Remove ParamSpec (consumed only by the former to_sync; moved with it into entrypoints.client). Keep Self and Unpack. (prune-shared-kernel)").

## 5. Extend `entrypoints/__init__.py` facade

- [x] 5.1 In `yascheduler/entrypoints/__init__.py`: add `from .paths import CONFIG_FILE, LOG_FILE, PID_FILE`.
- [x] 5.2 Extend `__all__` to include `"CONFIG_FILE"`, `"LOG_FILE"`, `"PID_FILE"`.
- [x] 5.3 Update `MODULE_MAP` (add `CONFIG_FILE`/`LOG_FILE`/`PID_FILE` re-export entries from `.paths`); update `MODULE_CONTRACT` `SCOPE` (add path constants), `LINKS` (add `M-ENTRYPOINTS-PATHS`); update `CHANGE_SUMMARY` ("<VERSION> — Re-export CONFIG_FILE/LOG_FILE/PID_FILE from .paths (prune-shared-kernel).").

## 6. Update `yascheduler/__init__.py` re-export source

- [x] 6.1 In `yascheduler/__init__.py`: change `from yascheduler.shared import CONFIG_FILE, LOG_FILE, PID_FILE` → `from yascheduler.entrypoints import CONFIG_FILE, LOG_FILE, PID_FILE`.
- [x] 6.2 Update `MODULE_CONTRACT` `DEPENDS` from `M-ENTRYPOINTS, M-SHARED` → `M-ENTRYPOINTS`; update `MODULE_MAP` constant entries to note re-export via `yascheduler.entrypoints`; update `CHANGE_SUMMARY` ("<VERSION> — Re-export path constants from yascheduler.entrypoints instead of yascheduler.shared (prune-shared-kernel).").

## 7. Rewrite `shared/__init__.py` facade

- [x] 7.1 In `yascheduler/shared/__init__.py`: change `from .async_utils import asleep_until, to_sync` and `from .compat import ParamSpec, Self, Unpack` and `from .variables import CONFIG_FILE, LOG_FILE, PID_FILE` → `from .compat import Self, Unpack` only.
- [x] 7.2 Update `__all__` to `["Self", "Unpack"]`.
- [x] 7.3 Rewrite `START_MODULE_CONTRACT` `PURPOSE` to "Shared kernel: typing shims consumed by ≥2 architectural layers." and `SCOPE` to "Typing shims consumed by ≥2 architectural layers; a module whose consumers are in a single layer belongs to that layer, not to shared. No SSH/DB/HTTP/cloud I/O."
- [x] 7.4 Update `START_MODULE_MAP` to list only `Self` and `Unpack`; update `START_CHANGE_SUMMARY` ("<VERSION> — Prune to honest shared kernel: drop re-exports of to_sync/asleep_until/CONFIG_FILE/LOG_FILE/PID_FILE/ParamSpec (relocated or inlined per prune-shared-kernel); keep Self/Unpack.").
- [x] 7.5 Verify the new re-export path via `entrypoints` is established (groups 5 and 6 done) BEFORE removing the old re-exports from `shared` — no intermediate state should break `from yascheduler import CONFIG_FILE`.

## 8. Rewrite production consumer imports

- [x] 8.1 `yascheduler/entrypoints/cli/args.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler.entrypoints import CONFIG_FILE`; update `MODULE_MAP`/`CHANGE_SUMMARY` if they mention the import source.
- [x] 8.2 `yascheduler/entrypoints/cli/init.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler.entrypoints import CONFIG_FILE`; update contract `CHANGE_SUMMARY`.
- [x] 8.3 `yascheduler/entrypoints/cli/daemon_sysv.py`: `from yascheduler.shared import LOG_FILE, PID_FILE` → `from yascheduler.entrypoints import LOG_FILE, PID_FILE`; update contract `CHANGE_SUMMARY`.

## 9. Rewrite test imports

- [x] 9.1 `tests/unit/test_cli_args.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler import CONFIG_FILE`.
- [x] 9.2 `tests/unit/test_cli_check_status.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler import CONFIG_FILE`.
- [x] 9.3 `tests/unit/test_cli_show_nodes.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler import CONFIG_FILE`.
- [x] 9.4 `tests/unit/test_cli_submit.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler import CONFIG_FILE`.
- [x] 9.5 `tests/unit/test_cli_init.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler import CONFIG_FILE`.
- [x] 9.6 `tests/unit/test_cli_manage_node.py`: `from yascheduler.shared import CONFIG_FILE` → `from yascheduler import CONFIG_FILE`.
- [x] 9.7 `tests/unit/test_cli_daemon_sysv.py`: `from yascheduler.shared import LOG_FILE, PID_FILE` → `from yascheduler import LOG_FILE, PID_FILE`.

## 10. Update GRACE knowledge graph

- [x] 10.1 In `docs/knowledge-graph.xml`: edit `M-SHARED` — remove `<fn-to_sync>`, `<fn-asleep_until>`, `<const-CONFIG_FILE>`, `<const-LOG_FILE>`, `<const-PID_FILE>`, `<type-ParamSpec>` annotations; keep `<type-Self>`, `<type-Unpack>`; update `<purpose>` to "Shared kernel: typing shims (Self, Unpack) consumed by ≥2 architectural layers."
- [x] 10.2 Add new `M-ENTRYPOINTS-PATHS` element (TYPE="UTILITY", STATUS="implemented", `<path>yascheduler/entrypoints/paths.py</path>`, `<depends>none</depends>`, annotations for `const-CONFIG_FILE`/`const-LOG_FILE`/`const-PID_FILE`).
- [x] 10.3 Edit `M-ENTRYPOINTS`: add `<const-CONFIG_FILE>`/`<const-LOG_FILE>`/`<const-PID_FILE>` annotations (re-exported from `.paths`); add `M-ENTRYPOINTS-PATHS` to `<depends>`; update `LINKS`.
- [x] 10.4 Edit `M-MAIN`: change `<depends>M-ENTRYPOINTS, M-SHARED</depends>` → `<depends>M-ENTRYPOINTS</depends>`; remove the `CrossLink from="M-MAIN" to="M-SHARED"` if present (verify by grep); update `<annotation>` comment for the path-constant exports if it mentions `M-SHARED`.
- [x] 10.5 Edit `M-ENTRYPOINTS-CLIENT`: update annotation note for `to_sync` (now a private resident, not a re-export from `M-SHARED`); add `M-ENTRYPOINTS-PATHS` to `<depends>` if not already present.
- [x] 10.6 Edit `M-APPLICATION-ORCHESTRATOR`: add `<fn-_asleep_until PURPOSE="Private async sleep-until helper inlined from former shared.async_utils">` annotation (optional per GRACE-lite private-helper guidance — include for traceability); update `CHANGE_SUMMARY` reference if the module has one.

## 11. Update `docs/ARCHITECTURE.md`

- [x] 11.1 Grep `docs/ARCHITECTURE.md` for `shared.variables`, `shared.async_utils`, `yascheduler.shared.variables`, `yascheduler.shared.async_utils`; rewrite any hits to reflect the new locations (`entrypoints.paths`, inlined `to_sync`/`asleep_until`).
- [x] 11.2 If `docs/ARCHITECTURE.md` has a "Shared kernel" section describing the permitted content by the negative definition, rewrite it to the positive definition (design D5).

## 12. Verify delta spec and run full verification

- [x] 12.1 Confirm `openspec/changes/prune-shared-kernel/specs/package-facades/spec.md` is present and contains `## MODIFIED Requirements` for "Outside-layer-set exemptions", "Entrypoints layer facade", and "Public API stability" (the delta spec was frozen during planning; this step confirms it is still in place and unchanged).
- [x] 12.2 Run `rg "yascheduler\.shared\.(variables|async_utils)|from yascheduler\.shared import (to_sync|asleep_until|ParamSpec|CONFIG_FILE|LOG_FILE|PID_FILE)"` repo-wide; expected zero matches.
- [x] 12.3 Run `openspec validate --all --json`; expected exit 0 and no errors.
- [x] 12.4 Run `python3 scripts/grace_check.py`; expected exit 0.
- [x] 12.5 Run `uv run lint-imports`; expected both `layers` and `forbidden` contracts pass.
- [x] 12.6 Run `uv run ruff check .` and `uv run ruff format --check .`; expected clean.
- [x] 12.7 Run `uv run zuban check`; expected clean.
- [x] 12.8 Run `uv run pytest -m unit`; expected all passing.
- [x] 12.9 Smoke: `python -c "from yascheduler import CONFIG_FILE, LOG_FILE, PID_FILE, Yascheduler; from yascheduler.shared import Self, Unpack; print('ok')"` — must print `ok`.
- [x] 12.10 Negative smoke: `python -c "from yascheduler.shared import to_sync" 2>&1 | grep ImportError` — must error; same for `asleep_until` and `ParamSpec`.
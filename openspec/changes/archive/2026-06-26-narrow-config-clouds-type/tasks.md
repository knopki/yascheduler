## 1. Narrow `Config.clouds` type

- [x] 1.1 In `yascheduler/entrypoints/config.py`, swap the `TYPE_CHECKING` import: drop `CloudConfig` from the `yascheduler.domain` import block, add `from yascheduler.infra.cloud.cloud_configs import ConfigCloud`. Keep `EngineRepository`, `LocalSettings`, `RemoteDefaults` in the `yascheduler.domain` import block. Run `uv run ruff check --fix yascheduler/entrypoints/config.py` to fix import ordering (the infra import lands after the domain import alphabetically — confirm ruff's sort matches the layers contract; if not, adjust to match the existing `config_parser.py:57-63` ordering pattern).
- [x] 1.2 Change the `clouds` field annotation on the `Config` dataclass from `Sequence[CloudConfig]` to `Sequence[ConfigCloud]`.
- [x] 1.3 Update the `START_MODULE_CONTRACT` `SCOPE` line in `config.py` to read `Sequence[ConfigCloud]` (was `Sequence[CloudConfig]`).
- [x] 1.4 Add a `LAST_CHANGE` entry to the `START_CHANGE_SUMMARY` block in `config.py`, referencing this change (`narrow-config-clouds-type`) and explaining the field-type narrowing (move the current `LAST_CHANGE` to `PREVIOUS_CHANGE`). Bump `VERSION`.

## 2. Remove the 2 downcasts from `di.py`

- [x] 2.1 In `yascheduler/entrypoints/di.py`, delete the 6-line comment block at lines 160-165 (the "config.clouds is typed Sequence[CloudConfig]…" explanation) and the `cfg = cast("ConfigCloud", cfg)` line. The loop variable `cfg` from `for cfg in config.clouds` is now `ConfigCloud` directly (D1 of this change narrowed the field type); `resolve_adapter(cfg, log)`, `_configs[adapter.name] = cfg`, and `active_clouds.append(cfg)` all accept `ConfigCloud` without a cast.
- [x] 2.2 In the same file, delete the 2-line comment at lines 192-193 (the "Protocol→Union downcast…" note) and unwrap the `cast("list[ConfigCloud]", [...])` wrapper around the `active_clouds` list comprehension at lines 194-201. The comprehension `[cfg for cfg in config.clouds if cfg.max_nodes > 0 and cfg.prefix in resolved_prefixes]` infers `list[ConfigCloud]` directly.
- [x] 2.3 Drop `cast` from the `from typing import TYPE_CHECKING, cast` line in `di.py` (now `from typing import TYPE_CHECKING`). Run `uv run ruff check --fix yascheduler/entrypoints/di.py` to confirm no unused-import warning remains.
- [x] 2.4 Confirm the upcast comment at di.py:204-206 ("The concrete ConfigCloud* DTOs explicitly inherit the domain CloudConfig Protocol (D1), so list[ConfigCloud] is assignable to Sequence[CloudConfig] (covariance + inheritance) without a cast.") stays unchanged — it is now the only cast-related comment and is accurate.
- [x] 2.5 Add a `LAST_CHANGE` entry to the `START_CHANGE_SUMMARY` block in `di.py`, referencing this change and noting the removal of both downcasts + the `cast` import (move the current `LAST_CHANGE` to `PREVIOUS_CHANGE`). The `PREVIOUS_CHANGE` line will retain the verbatim `cast("ConfigCloud", cfg)` and `cast("list[ConfigCloud]", [...])` tokens — these are comment text and do not affect the AST-based regression test (task 4.1). Bump `VERSION`.

## 3. Add the regression test

- [x] 3.1 Create `tests/unit/test_di_no_casts.py` with the AST-based test from design.md D3: parse `yascheduler/entrypoints/di.py` with `ast`, walk for `ImportFrom` from `typing` binding `cast`, `Call` with bare-name `cast`, and `Call` with `typing.cast` attribute. Use `raise AssertionError(...)` in all three branches (not `assert` — survives `python -O`). Include the GRACE-lite `FILE`/`VERSION`/`START_MODULE_CONTRACT` headers if the test is substantial; a minimal contract (PURPOSE + LINKS) suffices. Reference `openspec/changes/narrow-config-clouds-type` in the docstring for rationale.
- [x] 3.2 Run `uv run pytest -m unit tests/unit/test_di_no_casts.py` — confirm the test passes against the post-task-2 `di.py` (no `cast` usage in code). If it fails, the AST walk found a `cast` token in code (not comments) — re-inspect `di.py` and remove the missed usage.

## 4. Static verification

- [x] 4.1 `uv run zuban check` — confirm Success (148 files expected). If zuban flags a type error at `Orchestrator(config_clouds=config.clouds, active_clouds=active_clouds, ...)` in `di.py`, the covariance+inheritance path from `Sequence[ConfigCloud]` to `Sequence[CloudConfig]` is not resolving as expected — re-verify against the isolated repro at `/tmp/opencode/repro_a1/repro_a1_clean.py` and the real-tree spike from the explore phase.
- [x] 4.2 `uv run ruff check .` — confirm All checks passed (no unused imports, no ordering issues).
- [x] 4.3 `uv run ruff format --check .` — confirm all files formatted.
- [x] 4.4 `uv run lint-imports` — confirm "Clean architecture layers KEPT" (the new `TYPE_CHECKING`-only `entrypoints → infra.cloud.cloud_configs` edge in `config.py` is invisible to lint-imports under `exclude_type_checking_imports = true` at `pyproject.toml:119`).
- [x] 4.5 `rg -n 'cast\(' yascheduler/entrypoints/di.py` — confirm zero matches in code (matches in the `PREVIOUS_CHANGE` comment line are expected and acceptable; the AST test is the authoritative check).

## 5. Full unit suite

- [x] 5.1 `uv run pytest -m unit` — confirm 648 passed (647 existing + 1 new `test_di_no_casts`). No failures, no errors.
- [x] 5.2 `uv run pytest -m unit tests/unit/test_di.py tests/unit/test_config.py tests/unit/test_cloud_config_protocol_inheritance.py tests/unit/test_cloud_provisioner_impl.py` — confirm the cloud/config/DI-adjacent tests in particular still pass (these are the most likely to surface a runtime regression from the field-type change).

## 6. Spec + GRACE validation

- [x] 6.1 `openspec validate --all --json` — confirm `narrow-config-clouds-type` has zero invalid items. The pre-existing unrelated `cloud-init-rename-and-prune` invalid item is out of scope and should be ignored.
- [x] 6.2 `python3 scripts/grace_check.py` — confirm exit 0 (the `CHANGE_SUMMARY` updates in `config.py` and `di.py` are the only GRACE-relevant changes; no `M-*` node added/removed, no `<depends>` change, no `CrossLink` change).
- [x] 6.3 Spot-check `docs/knowledge-graph.xml` `M-ENTRYPOINTS-CONFIG` entry — confirm `M-CLOUD-CONFIGS` is already in its `<depends>` (no new entry needed; the field type narrows but the structural dependency is unchanged).
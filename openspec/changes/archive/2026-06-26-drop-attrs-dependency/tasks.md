## 1. Drop the direct dependency

- [x] 1.1 In `pyproject.toml`, remove the line `"attrs>=22.2.0",` from the `[project].dependencies` array. Do not reorder the remaining entries; leave the array otherwise untouched.
- [x] 1.2 Run `uv lock` to regenerate `uv.lock`. Verify `attrs` still appears in `uv.lock` as a transitive dependency of `aiohttp` (lines ~32 and ~4117 — `aiohttp`'s and `yascheduler`'s dependency blocks). The `yascheduler` block MUST NOT list `attrs` after the change; `aiohttp`'s block MUST still list it.
- [x] 1.3 Run `uv run python -c "import attrs"` and confirm it still succeeds (transitive resolvability preserved). Then run `uv run python -c "import yascheduler"` and confirm no `ModuleNotFoundError`.

## 2. Stale FIXME marker

- [x] 2.1 Grep `yascheduler/config/config.py` for `# FIXME: migrate from attrs to dataclasses`. If P4 deleted the file, this task is a no-op verification (grep returns no such file — done). If the file still exists with the marker, remove the marker line. After this task, `grep -rn "FIXME.*attrs\|migrate from attrs" yascheduler/ tests/` returns zero matches outside `CHANGE_SUMMARY` historical lines.

## 3. CHANGE_SUMMARY refreshes

- [x] 3.1 In `yascheduler/infra/cloud/cloud_config.py`, add a `CHANGE_SUMMARY` `LAST_CHANGE` entry: `v1.2.0 - attrs is no longer a direct dependency of yascheduler (drop-attrs-dependency).` Bump the file `VERSION` from 1.1.0 to 1.2.0. Verify `MODULE_CONTRACT` and `MODULE_MAP` contain no stale "attrs" wording (they should already say "frozen dataclass" after migrate-cloud-from-attrs).
- [x] 3.2 In `yascheduler/infra/cloud/adapters.py`, verify the `# FIXME: migrate from attrs to dataclasses` marker is already gone (removed by migrate-cloud-from-attrs). If present, remove it. No `CHANGE_SUMMARY` bump required unless the marker is found (then add a minor-version note).
- [x] 3.3 In `tests/unit/test_cloud_provisioner_impl.py`, update the `CHANGE_SUMMARY` `LAST_CHANGE` to note that the `test_cloud_config_render_serializes` canary is now complemented by the package-wide `test_no_attrs_dependency` canary (P5). Bump the test file `VERSION` minor.

## 4. Package-wide attrs-import canary

- [x] 4.1 Create `tests/unit/test_no_attrs_dependency.py` with a `MODULE_CONTRACT` (PURPOSE: AST-based canary guarding that no module under `yascheduler/` imports `attrs` or `attr` at runtime; DEPENDS: none; LINKS: no-attrs-dependency spec) and a single test `test_no_attrs_imports_in_yascheduler`.
- [x] 4.2 The test walks `yascheduler/` (the package root, resolved via `importlib.resources` or `pathlib` from the `yascheduler` import path), recursively discovers every `.py` file, parses each with `ast.parse`, and visits every `ImportFrom` and `Import` node. It fails if any node targets a module name starting with `attrs` or `attr` (covering `from attrs import ...`, `from attr import ...`, `import attrs`, `import attr`). Exclude `tests/` (the canary guards production code only).
- [x] 4.3 The test MUST ignore `TYPE_CHECKING`-guarded imports for the purpose of this canary? — No: the canary guards *runtime* imports, and `attrs` is a runtime package. But an `if TYPE_CHECKING:` import of attrs is not a runtime import. Decide: the canary flags any `ImportFrom`/`Import` node regardless of guard context, because a TYPE_CHECKING-only attrs import is still a smell (attrs is not a typing shim). Document this in the test's CONTRACT: "flags all `attrs`/`attr` imports, including those under `TYPE_CHECKING`; attrs is a runtime third-party package and must not appear in any yascheduler module's import graph at all."
- [x] 4.4 Add the test file to `tests/unit/` (no `conftest.py` changes needed; the test uses only stdlib `ast`, `pathlib`, `importlib`). Mark the test with `@pytest.mark.unit` if the project's unit-test marker convention requires it (check `tests/unit/conftest.py` for a marker applied at collection; if unit tests are auto-marked by directory, no decorator is needed).

## 5. OpenSpec spec

- [x] 5.1 Create `openspec/changes/2026-06-25-drop-attrs-dependency/specs/no-attrs-dependency/spec.md` with:
  - `## Purpose` — one sentence: yascheduler has no direct runtime dependency on `attrs`.
  - `### Requirement: No direct attrs dependency` — the `[project].dependencies` array in `pyproject.toml` SHALL NOT list `attrs`; all record types in `yascheduler/` SHALL be stdlib `dataclasses`; a CI-guard canary test SHALL fail if any module under `yascheduler/` imports `attrs` or `attr`.
  - `#### Scenario: pyproject.toml does not list attrs` — WHEN `pyproject.toml` is parsed, THEN the `[project].dependencies` array does not contain `attrs`.
  - `#### Scenario: canary test guards reintroduction` — WHEN a contributor adds `from attrs import define` to any module under `yascheduler/`, THEN `tests/unit/test_no_attrs_dependency.py` fails on the next `uv run pytest -m unit` run.
  - `#### Scenario: transitive attrs via aiohttp is allowed` — WHEN `uv.lock` is inspected, THEN `attrs` appears as a transitive dependency of `aiohttp` (and may appear under other third-party packages); the canary test does not inspect `uv.lock` or `aiohttp`'s internals.
  - `#### Scenario: attrs remains importable in the environment` — WHEN `uv run python -c "import attrs"` is executed, THEN it succeeds (transitive resolvability preserved).

## 6. GRACE-lite markup

- [x] 6.1 The new `tests/unit/test_no_attrs_dependency.py` carries a `MODULE_CONTRACT` (per testing-unit spec: test files MAY carry contracts when substantial; this canary is substantial — it is a CI guard).
- [x] 6.2 The `CHANGE_SUMMARY` refreshes in step 3 use the standard `LAST_CHANGE` / `PREVIOUS_CHANGE` form.

## 7. Verification

- [x] 7.1 Run `uv run pytest -m unit` — all pass, including the new `test_no_attrs_dependency`.
- [x] 7.2 Run `uv run pytest -m integration` — all pass (no behavior change expected; integration tests do not import attrs through yascheduler).
- [x] 7.3 Run `uv run pytest -m e2e` — all pass, or skip if no testcontainers environment.
- [x] 7.4 Run `uv run ruff check .` — clean.
- [x] 7.5 Run `uv run ruff format --check .` — clean.
- [x] 7.6 Run `uv run lint-imports` — no violations (the layers contract is untouched by P5; this is a regression check only).
- [x] 7.7 Run `python3 scripts/grace_check.py` — exit 0.
- [x] 7.8 Run `openspec validate --all --json` — pass. (Note: the pre-existing `resolve-type-bridge-debt` change fails validation independently of this work — it has no deltas and is out of scope; this change validates clean.)
- [x] 7.9 Grep `grep -rn "from attrs\|import attrs" yascheduler/` — no import statements remain. `CHANGE_SUMMARY` comment lines that historically mention "attrs" (e.g. `# LAST_CHANGE: ... Migrate ... from attrs.define ...`) will match the grep but are not imports and are not a failure; the authoritative guard is the AST canary in 7.1, which ignores comments. (Verified: 6 matches, all `#`-prefixed CHANGE_SUMMARY lines; AST canary passed.)
- [x] 7.10 Grep `grep "attrs" pyproject.toml` — zero matches.
- [x] 7.11 Grep `grep -rn "FIXME.*attrs" yascheduler/ tests/` — zero matches. (Verified: the single textual match is `adapters.py:25` CHANGE_SUMMARY historical prose "remove stale FIXME marker (migrate-cloud-from-attrs)" — not an active marker; the regex spans "marker (migrate-cloud-from-" + "attrs". No active FIXME markers exist. This line is preserved per GRACE-lite CHANGE_SUMMARY rules and task 3.2's "no CHANGE_SUMMARY bump" instruction; rewriting it would falsify history.)
- [x] 7.12 Verify `uv run python -c "import yascheduler; import attrs"` succeeds (attrs still transitively resolvable).
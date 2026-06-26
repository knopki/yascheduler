## Why

The config-layer split plan (`docs/config-layer-split-plan.md`) migrates every
attrs consumer to stdlib `dataclasses` in steps P1–P4. After P4 archives,
`yascheduler/config/` is deleted and the last four attrs users
(`config/config.py`, `config/db.py`, `config/remote.py`, `config/utils.py`) are
gone with it. Every other attrs consumer is already migrated:

- `application/queue.py` — `queue-dataclass-migration`
- `infra/cloud/{adapters,cloud_config,protocols,manager}.py` —
  `migrate-cloud-from-attrs`
- `infra/cloud/providers/az.py` — hybrid in `migrate-cloud-from-attrs`; the last
  `attrs.asdict(vm_image)` call site was resolved when `AzureImageReference`
  became a stdlib dataclass in `cloud-configs-to-infra-registry` (P3), and the
  call site already uses `dataclasses.asdict` (aliased `dataclass_asdict`).
- `infra/ssh/platform/{common,adapters}.py` — `migrate-ssh-platform-from-attrs`

`grep -rn "from attrs\|import attrs" yascheduler/ tests/` after P4 returns zero
runtime imports (only historical mentions in `CHANGE_SUMMARY` comments). Yet
`pyproject.toml:35` still declares `"attrs>=22.2.0"` as a direct dependency, and
`config/config.py:22` carries a stale `# FIXME: migrate from attrs to dataclasses`
marker that P4 leaves in place because the file is about to be deleted (P4 deletes
the file; P5 removes the dangling FIXME trail and the dependency declaration).

This is the fifth and final step (P5) of the config-layer split plan. It is a
cleanup change: drop the direct `attrs` dependency from `pyproject.toml`,
remove the stale FIXME marker, refresh the two `CHANGE_SUMMARY` entries that
still describe the attrs era as if it were current, and add a spec requirement
codifying "no direct attrs dependency" so the dependency cannot be reintroduced
silently. Predecessors P1, P2, P3 are archived; P4
(`config-aggregate-to-entrypoints`) is the immediate predecessor — P5 assumes
P4's deletion of `yascheduler/config/` is in place.

## What Changes

- Remove `"attrs>=22.2.0"` from the `dependencies` array in `pyproject.toml`.
  After P4 no production or test code imports `attrs`; the direct dependency is
  dead weight. `aiohttp` continues to depend on `attrs` transitively, so
  `attrs` remains in `uv.lock` — that is expected and out of scope (transitive
  dependencies are not under yascheduler's direct control).
- Remove the stale `# FIXME: migrate from attrs to dataclasses` marker at
  `yascheduler/config/config.py:22`. (If P4 has already deleted the file, this
  task is a no-op verification step; if P4 archived but left the marker as a
  breadcrumb, P5 removes it.) After P5, `grep -rn "FIXME.*attrs\|migrate from
  attrs" yascheduler/ tests/` returns zero matches outside `CHANGE_SUMMARY`
  history lines.
- Refresh the `START_CHANGE_SUMMARY` `LAST_CHANGE` entries in the two files
  that still describe the attrs era as a current state in their `MODULE_MAP` /
  contract wording:
  - `yascheduler/infra/cloud/cloud_config.py` — `MODULE_MAP` says "Frozen
    dataclass" (already correct after `migrate-cloud-from-attrs`); verify no
    stale "attrs" wording remains in `MODULE_CONTRACT` / `MODULE_MAP`. Add a
    `CHANGE_SUMMARY` entry noting `attrs` is no longer a direct dependency.
  - `yascheduler/infra/cloud/adapters.py` — same verification; the
    `# FIXME: migrate from attrs to dataclasses` marker was already removed by
    `migrate-cloud-from-attrs`; confirm it has not regressed.
- Add a canary unit test `tests/unit/test_no_attrs_dependency.py` asserting
  that no module under `yascheduler/` imports `attrs` at runtime. The test
  walks `yascheduler/**/*.py`, parses each file with `ast`, and fails if any
  `ImportFrom` node targets `attrs` or `attr` (catching `from attrs import ...`
  and `import attrs`). This guards against silent reintroduction. Precedent:
  `tests/unit/test_cloud_provisioner_impl.py::test_cloud_config_render_serializes`
  was a canary added during `migrate-cloud-from-attrs`; P5 generalises the
  pattern to the whole package.
- Refresh the canary test's `CHANGE_SUMMARY` in
  `tests/unit/test_cloud_provisioner_impl.py` to note that the render-output
  guard is now backed by a package-wide attrs-import canary (P5), so the
  cloud-specific canary is no longer the sole guard.

## Capabilities

### New Capabilities
- `no-attrs-dependency`: yascheduler has no direct runtime dependency on the
  `attrs` package. All record types are stdlib `dataclasses.dataclass`
  (frozen unless mutability is required by a documented invariant). A CI-guard
  canary test fails if any module under `yascheduler/` imports `attrs` or
  `attr`. Transitive presence of `attrs` via `aiohttp` (and other third-party
  packages) in `uv.lock` is expected and out of scope.

### Modified Capabilities
- None. `no-attrs-dependency` is a standalone dependency-policy spec; it does
  not modify an existing capability spec. The `package-facades` spec is
  untouched (the layers contract is unaffected — `attrs` was never a layering
  concern, only a dependency choice).

## Impact

- **Code**: `pyproject.toml` (one line removed from `dependencies`);
  `yascheduler/config/config.py` (stale FIXME removed, or the file is already
  deleted by P4 — P5 verifies either way); `CHANGE_SUMMARY` refreshes in
  `infra/cloud/cloud_config.py`, `infra/cloud/adapters.py`, and
  `tests/unit/test_cloud_provisioner_impl.py`; new
  `tests/unit/test_no_attrs_dependency.py`.
- **APIs**: None. No public symbol changes; no import path changes; no
  constructor or method signature changes. The `attrs` package remains
  importable in the environment (transitive via `aiohttp`), so any code outside
  `yascheduler/` that imports it is unaffected — but no such code exists in
  this repository after P4.
- **Layers contract**: Unchanged. The `layers` and `forbidden` contracts in
  `pyproject.toml` are untouched; P4 already removed the vacuous `forbidden`
  contract and the `ignore_imports` seam. P5 does not touch import-linter
  configuration.
- **Dependencies**: `attrs` removed from `[project].dependencies` in
  `pyproject.toml`. `uv lock` regenerates `uv.lock`; the `attrs` package
  remains in the lockfile as a transitive dependency of `aiohttp` (and any
  other third-party package that pulls it). The `yascheduler` package's own
  `dependencies = [...]` block no longer lists `attrs`.
- **Specs**: New `no-attrs-dependency` capability spec with one Requirement
  (no direct attrs dependency) and two Scenarios (canary test guards
  reintroduction; transitive presence via aiohttp is allowed). No delta specs
  against existing capabilities.
- **Tests**: New `tests/unit/test_no_attrs_dependency.py` (AST-based canary).
  No existing tests modified in behavior; `test_cloud_provisioner_impl.py`
  `CHANGE_SUMMARY` refreshed only.
- **Knowledge graph**: No changes. `attrs` is a dependency, not a module; the
  knowledge graph tracks in-repo modules and their call edges, not
  third-party packages. No `M-*` node is added, removed, or repointed.
- **Verification**: `uv run pytest -m unit` passes (including the new
  canary); `uv run ruff check .` clean; `grep -rn "from attrs\|import attrs"
  yascheduler/` returns no import statements (only `CHANGE_SUMMARY` comment
  lines that historically mention "attrs" — those are expected and ignored by
  the AST canary); `grep "attrs" pyproject.toml` returns zero matches;
  `openspec validate --all --json` passes.
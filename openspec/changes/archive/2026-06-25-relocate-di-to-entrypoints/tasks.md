## 1. Relocate the composition root module

- [x] 1.1 `git mv yascheduler/di.py yascheduler/entrypoints/di.py`
- [x] 1.2 In `yascheduler/entrypoints/di.py`, update the `# FILE:` header from `yascheduler/di.py` to `yascheduler/entrypoints/di.py`
- [x] 1.3 In `yascheduler/entrypoints/di.py`, rewrite the three internal relative import blocks to absolute-via-facade form: `from .application import …` → `from yascheduler.application import …`; `from .domain import …` → `from yascheduler.domain import …`; `from .infra import …` → `from yascheduler.infra import …` (preserve the exact symbol list including `resolve_adapter`, `webhook_handler`)
- [x] 1.4 In `yascheduler/entrypoints/di.py`, append a new `START_CHANGE_SUMMARY` entry at the top of the block: `LAST_CHANGE: v5.4.0 - relocate-di-to-entrypoints: move composition root into yascheduler.entrypoints; internal imports switch from relative (.application/.domain/.infra) to absolute via layer facades (yascheduler.application/.domain/.infra). PREVIOUS_CHANGE: v5.3.0 - …` (preserve the existing v5.3.0 entry as PREVIOUS_CHANGE)

## 2. Extend the entrypoints layer facade

- [x] 2.1 In `yascheduler/entrypoints/__init__.py`, add imports `from .di import CLIDeps, make_cli_deps, make_daemon` (sibling-relative, R1)
- [x] 2.2 Extend `__all__` to `["Yascheduler", "make_daemon", "make_cli_deps", "CLIDeps"]`
- [x] 2.3 Update `MODULE_CONTRACT`: `SCOPE` mentions re-exporting `make_daemon`, `make_cli_deps`, `CLIDeps` in addition to `Yascheduler`; `LINKS` adds `M-DI`; bump `VERSION` to 2.3.0
- [x] 2.4 Update `MODULE_MAP` to add one-line entries for `make_daemon`, `make_cli_deps`, `CLIDeps`
- [x] 2.5 Update `START_CHANGE_SUMMARY`: new `LAST_CHANGE: v2.3.0 - relocate-di-to-entrypoints: di.py moved into entrypoints; facade now re-exports make_daemon, make_cli_deps, CLIDeps alongside Yascheduler. The "only di.py remains deferred" caveat in the previous entry is superseded.` (preserve existing entries as PREVIOUS_CHANGE)

## 3. Rewrite production consumer imports (6 files)

- [x] 3.1 `yascheduler/entrypoints/cli/daemon_common.py`: `from yascheduler.di import make_daemon` → `from yascheduler.entrypoints import make_daemon`
- [x] 3.2 `yascheduler/entrypoints/cli/submit.py`: `from yascheduler.di import make_cli_deps` → `from yascheduler.entrypoints import make_cli_deps`
- [x] 3.3 `yascheduler/entrypoints/cli/check_status.py`: `from yascheduler.di import make_cli_deps` → `from yascheduler.entrypoints import make_cli_deps`; the inner `from yascheduler.di import CLIDeps` → `from yascheduler.entrypoints import CLIDeps`
- [x] 3.4 `yascheduler/entrypoints/cli/show_nodes.py`: `from yascheduler.di import make_cli_deps` → `from yascheduler.entrypoints import make_cli_deps`
- [x] 3.5 `yascheduler/entrypoints/cli/manage_node.py`: `from yascheduler.di import make_cli_deps` → `from yascheduler.entrypoints import make_cli_deps`; the inner `from yascheduler.di import CLIDeps` → `from yascheduler.entrypoints import CLIDeps`
- [x] 3.6 `yascheduler/entrypoints/client.py`: `from yascheduler.di import CLIDeps, make_cli_deps` → `from .di import CLIDeps, make_cli_deps` (sibling-relative, R1)

## 4. Rewrite test imports and patch targets (7 files)

- [x] 4.1 `tests/unit/test_di.py`: update the import line `from yascheduler.di import CLIDeps, make_cli_deps, make_daemon` → `from yascheduler.entrypoints.di import CLIDeps, make_cli_deps, make_daemon`
- [x] 4.2 `tests/unit/test_di.py`: replace every `yascheduler.di.X` patch target with `yascheduler.entrypoints.di.X` — 15 references total: `submit_task` (1, L108), `aiohttp.ClientSession` (4, L131/143/155/184), `resolve_adapter` (5, L194/239/264/284/299), `SSHMachineGateway` (1, L195), `Orchestrator` (4, L197/240/265/285/300). Also `import yascheduler.di as di_module` → `import yascheduler.entrypoints.di as di_module`.
- [x] 4.3 `tests/unit/test_cli_behavioral.py`: `from yascheduler.di import CLIDeps` → `from yascheduler.entrypoints.di import CLIDeps`
- [x] 4.4 `tests/unit/test_cli_check_status.py`: same rewrite
- [x] 4.5 `tests/unit/test_cli_manage_node.py`: same rewrite
- [x] 4.6 `tests/unit/test_cli_show_nodes.py`: same rewrite
- [x] 4.7 `tests/unit/test_cli_submit.py`: same rewrite
- [x] 4.8 `tests/e2e/test_full_cycle.py`: `from yascheduler.di import make_cli_deps, make_daemon` → `from yascheduler.entrypoints.di import make_cli_deps, make_daemon`

## 5. Update GRACE knowledge graph and architecture doc

- [x] 5.1 In `docs/knowledge-graph.xml`, update the `M-DI` element's `<path>` from `yascheduler/di.py` to `yascheduler/entrypoints/di.py`. Do NOT change the `M-DI` tag name, `<depends>`, or any `CrossLink` referencing `M-DI`.
- [x] 5.2 In `docs/ARCHITECTURE.md` §2.8, update the heading `### 2.8 Composition Root (yascheduler/di.py)` → `### 2.8 Composition Root (yascheduler/entrypoints/di.py)`; update any in-body path references in §2.8 and §2.9 that mention `yascheduler/di.py` or `yascheduler.di` to point to `yascheduler/entrypoints/di.py` / `yascheduler.entrypoints.di`

## 6. Update OpenSpec specs (decision-level)

- [x] 6.1 Apply the `package-facades` delta: merge the MODIFIED requirements ("Layer direction (R3)", "Outside-layer-set exemptions", "Documented private-symbol carve-outs") and the ADDED requirement ("Entrypoints layer facade contents") into `openspec/specs/package-facades/spec.md`. Per the project's OpenSpec rule, this is a same-change spec update.
- [x] 6.2 Apply the `dependency-injection` delta: merge the MODIFIED requirements ("make_daemon factory", "make_cli_deps factory", "DI factories in yascheduler.entrypoints.di", "Each factory creates only needed dependencies") into `openspec/specs/dependency-injection/spec.md`.
- [x] 6.3 Apply the `test-db-integration` delta: merge the MODIFIED requirement ("Yascheduler query path integration against PostgreSQL") into `openspec/specs/test-db-integration/spec.md` (single change: `yascheduler.di.make_cli_deps` → `yascheduler.entrypoints.di.make_cli_deps`).

## 7. Verify

- [x] 7.1 Run `rg "yascheduler\.di\b"` repo-wide; expected zero matches (all references migrated to `yascheduler.entrypoints.di`)
- [x] 7.2 Run `uv run pytest -m unit` — all unit tests pass (especially `tests/unit/test_di.py` and the 5 `test_cli_*.py`)
- [x] 7.3 Run `uv run lint-imports` — the `layers` contract passes with `entrypoints/di.py` now subject to R3; the `forbidden` contract passes
- [x] 7.4 Run `uv run ruff check .` and `uv run ruff format --check .` — clean
- [x] 7.5 Run `uv run zuban check` — clean
- [x] 7.6 Run `python3 scripts/grace_check.py` — XML + source checks pass (updated `M-DI` path, updated `# FILE:` header, MODULE_CONTRACT/CHANGE_SUMMARY in `entrypoints/di.py` and `entrypoints/__init__.py`)
- [x] 7.7 Run `openspec validate --all --json` — passes after the spec updates in step 6
- [x] 7.8 Run `uv run pytest -m integration` and `uv run pytest -m e2e` if testcontainers infrastructure is available — confirm no regressions in `tests/e2e/test_full_cycle.py`
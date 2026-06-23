## 1. Move directory

- [x] 1.1 Remove `__pycache__/` directories under `yascheduler/adapters/` (untracked bytecode)
- [x] 1.2 `git mv yascheduler/adapters yascheduler/infra`
- [x] 1.3 Verify `yascheduler/infra/` exists with 64 tracked files; `yascheduler/adapters/` gone

## 2. Rewrite dotted-form references (pattern 1: `yascheduler.adapters` → `yascheduler.infra`)

- [x] 2.1 Rewrite `yascheduler/**/*.py` outside `yascheduler/infra/` that import `from yascheduler.adapters...` or reference `yascheduler.adapters...` in strings/comments: `di.py`, `client.py`, `daemon_systemd.py`, `daemon_sysv.py`, `config/__init__.py`, `domain/exceptions.py`, `domain/model.py`
- [x] 2.2 Rewrite `yascheduler/infra/**/*.py` internal `# FILE:` headers, `MODULE_CONTRACT`/`LINKS:`/`CHANGE_SUMMARY` path references, and any absolute `yascheduler.adapters...` references inside the moved tree (internal cross-references)
- [x] 2.3 Rewrite `tests/**/*.py` absolute imports and `patch("yascheduler.adapters...")` string targets (~18 test files)
- [x] 2.4 Rewrite `pyproject.toml` six `[project.scripts]` entry points from `yascheduler.adapters.cli.*` to `yascheduler.infra.cli.*`
- [x] 2.5 Rewrite `pyproject.toml` `[tool.importlinter]` `layers` first entry from `yascheduler.adapters` to `yascheduler.infra`
- [x] 2.6 Rewrite `pyproject.toml` `[tool.setuptools.package-data]` key from `yascheduler.adapters.persistence.sql` to `yascheduler.infra.persistence.sql`
- [x] 2.7 Rewrite `docs/ARCHITECTURE.md` dotted-form references (prose mentions of `yascheduler.adapters...`) — N/A: docs use slash-form only, handled in §3

## 3. Rewrite prefix-slash-form references (pattern 2: `yascheduler/adapters/` → `yascheduler/infra/`)

- [x] 3.1 Rewrite `yascheduler/infra/**/*.py` `# FILE:` header comments from `yascheduler/adapters/...` to `yascheduler/infra/...`
- [x] 3.2 Rewrite `docs/ARCHITECTURE.md` slash-form references with the `yascheduler/` prefix (prose + ASCII diagrams: lines 97, 146, 202, 212, 220, 227, 356, 401, 520 as flagged in design)
- [x] 3.3 Rewrite `docs/knowledge-graph.xml` every `<path>yascheduler/adapters/...` to `<path>yascheduler/infra/...`
- [x] 3.4 Rewrite `openspec/specs/**/*.md` slash-form references with the `yascheduler/` prefix (the 18 specs)

## 4. Rewrite bare-slash-form references (pattern 3: `adapters/<subpkg>` → `infra/<subpkg>` for cloud/ssh/persistence/cli/notifier)

- [x] 4.1 Rewrite `docs/ARCHITECTURE.md` bare `adapters/<subpkg>/` references in the component table (lines 111-115), section headers (2.2/2.4/2.5/2.6/2.7), and the standalone `adapters/` directory label in the project-structure tree (line 401) and the import-rules block (line 356)
- [x] 4.2 Rewrite `docs/knowledge-graph.xml` `<annotation>` PURPOSE text embedding bare `adapters/<subpkg>/...` paths (e.g. lines 85-90 `adapters/cli/submit.py`)
- [x] 4.3 Rewrite `openspec/specs/**/*.md` bare `adapters/<subpkg>/` references in spec prose (cloud-providers, cloud-provisioner, cloud-wrapper, ssh-gateway, platform-adapters, remote-machine-wrapper, sql-queries, cli-commands, test-db-integration, e2e-testing, package-facades)

## 5. Rewrite relative imports (pattern 4: `from .adapters` → `from .infra`, four-file allow-list)

- [x] 5.1 Rewrite `yascheduler/di.py` line 33: `from .adapters import (` → `from .infra import (`
- [x] 5.2 Rewrite `yascheduler/di.py` line 40: `from .adapters.cloud import resolve_adapter` → `from .infra.cloud import resolve_adapter`
- [x] 5.3 Rewrite `yascheduler/daemon_sysv.py` line 31: `from .adapters.cli import daemonize` → `from .infra.cli import daemonize`
- [x] 5.4 Rewrite `yascheduler/daemon_systemd.py` line 26: `from .adapters.cli import daemonize` → `from .infra.cli import daemonize`
- [x] 5.5 Verify the four sibling `from .adapters` imports inside `yascheduler/infra/` are NOT touched: `infra/cloud/__init__.py:36`, `infra/cloud/provider_selection.py:29`, `infra/cloud/manager.py:58`, `infra/ssh/platform/__init__.py:18` (they resolve to the preserved `adapters.py` basename)

## 6. Verify

- [x] 6.1 Grep #1: `grep -rn "yascheduler.adapters" --include="*.py" --include="*.toml" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/ openspec/specs/ pyproject.toml` returns zero matches
- [x] 6.2 Grep #2: `grep -rn "yascheduler/adapters/" --include="*.py" --include="*.toml" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/ openspec/specs/ pyproject.toml` returns zero matches
- [x] 6.3 Grep #3: `grep -rn "adapters/cloud\|adapters/ssh\|adapters/persistence\|adapters/cli\|adapters/notifier" --include="*.py" --include="*.toml" --include="*.xml" --include="*.md" yascheduler/ tests/ docs/ openspec/specs/ pyproject.toml` returns zero matches
- [x] 6.4 Grep #4: `grep -rn "from \.adapters" --include="*.py" yascheduler/` returns EXACTLY the four expected sibling imports (`infra/cloud/__init__.py`, `infra/cloud/provider_selection.py`, `infra/cloud/manager.py`, `infra/ssh/platform/__init__.py`)
- [x] 6.5 `uv run pytest -m unit` passes (378 passed)
- [x] 6.6 `uv run pytest -m integration` passes (if testcontainers available) (68 passed)
- [x] 6.7 `uv run pytest -m e2e` passes (if testcontainers available) (1 passed)
- [x] 6.8 `uv run lint-imports` passes (the `layers` contract with `yascheduler.infra` as top layer recognizes the renamed package; if the residual R3 edges `yascheduler.application.{consume_task,orchestrator} -> yascheduler.infra` are flagged, add the two `ignore_imports` entries with the new target — but only if actually flagged) (2 contracts KEPT, 0 broken; no ignore_imports needed)
- [x] 6.9 `uv run ruff check .` passes (after `--fix` re-sorted 24 import blocks whose alphabetical order shifted due to the rename)
- [x] 6.10 `uv run ruff format --check .` passes (130 files formatted)
- [x] 6.11 `uv run zuban check` passes (no issues in 131 source files)
- [x] 6.12 `python3 scripts/grace_check.py` passes (exit 0; 0 errors, 28 pre-existing size warnings, no path-mismatch warnings)
- [x] 6.13 `openspec validate --all --json` passes (`valid: true`, zero errors)
- [x] 6.14 Final smoke check: `yasubmit --help`, `yastatus --help`, `yanodes --help`, `yasetnode --help`, `yainit --help`, `yascheduler --help` all still resolve their entry points (confirm the `[project.scripts]` rewrite didn't break console-script loading) (all 6 entry points loaded successfully; yanodes/yainit fail on environmental issues — DB connection / systemd write perms — not import breaks)
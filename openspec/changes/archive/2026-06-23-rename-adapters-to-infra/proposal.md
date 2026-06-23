## Why

The package `yascheduler.adapters` is the hexagonal-architecture outer
ring (PostgreSQL, SSH, cloud, CLI, notifier). The word "adapters" is
both the literal directory name and a conceptual label that collides
with the cloud-provider `CloudAdapter` wrapper, the platform
`RemoteMachineAdapter` family, and the `yascheduler.adapters.cloud.adapters`
module — three unrelated things all called "adapter". Renaming the
layer directory to `yascheduler.infra` (infrastructure) disambiguates
the layer from the in-layer adapter classes, aligns the vocabulary
with the rest of the prose ("infrastructure adapter",
"infrastructure failure"), and is a pure cosmetic rename — no behavior,
no public API, no schema, no semantics change. The user explicitly
framed this as a mechanical, sense-preserving cosmetic change.

## What Changes

- **BREAKING (internal import paths only)**: rename the directory
  `yascheduler/adapters/` → `yascheduler/infra/`. Every absolute
  import path `yascheduler.adapters…` becomes `yascheduler.infra…`.
- Update all in-tree absolute imports of `yascheduler.adapters…` in
  `yascheduler/` and `tests/` to `yascheduler.infra…`.
- Update `pyproject.toml`:
  - six `[project.scripts]` entry points (`yainit`, `yanodes`,
    `yascheduler`, `yasetnode`, `yastatus`, `yasubmit`) point at
    `yascheduler.infra.cli.*`.
  - the `layers` contract in `[tool.importlinter]` uses
    `yascheduler.infra` as the top layer instead of
    `yascheduler.adapters`.
  - the `[tool.setuptools.package-data]` key
    `"yascheduler.adapters.persistence.sql"` becomes
    `"yascheduler.infra.persistence.sql"`.
- Note: the `ignore_imports` array in `pyproject.toml` is currently
  empty (`ignore_imports = []`); the two residual R3 edges
  (`yascheduler.application.{consume_task,orchestrator} -> yascheduler.adapters`)
  are documented only in `package-facades/spec.md` text. That spec text
  is updated in this change; no `pyproject.toml` `ignore_imports`
  entries are added or removed by the rename itself.
- Update `docs/knowledge-graph.xml`: every `<path>` containing
  `yascheduler/adapters/` becomes `yascheduler/infra/`; the module IDs
  `M-ADAPTERS`, `M-CLOUD-ADAPTERS-NEW`, `M-PLATFORM-ADAPTERS` are
  preserved (they name concepts, not the directory), but their
  `<path>` children are rewritten.
- Update `docs/ARCHITECTURE.md` prose and ASCII diagrams
  (`ADAPTERS:` boxes → `INFRA:`, every `adapters/` path reference).
- Update GRACE-lite `FILE:`/`MODULE_CONTRACT`/`MODULE_MAP`/contract
  `LINKS:` comments and `PREVIOUS_CHANGE`/`LAST_CHANGE` annotations
  inside the renamed files to reflect the new path (mechanical, no
  semantic change to contracts).
- Update in-tree string references to the old path that exist as
  `patch("yascheduler.adapters.…")` targets in tests, and the
  `# FILE:` header comments that hard-code the path.

Non-goals (explicitly out of scope):

- No renaming of the classes `CloudAdapter`, `RemoteMachineAdapter`,
  or the module `yascheduler.adapters.cloud.adapters.py` → those
  identifiers keep their names; only the containing directory changes.
  The cloud-adapter module becomes
  `yascheduler/infra/cloud/adapters.py` (path changes, file basename
  stays `adapters.py`, class names stay).
- No public API change: `class Yascheduler`, CLI command names, INI
  format, AiiDA entrypoint key, DB schema — all preserved.
- No change to the layer-direction contract semantics; the top layer
  keeps the same position, only its label changes.

## Capabilities

### New Capabilities
<!-- None: this is a rename of an existing layer, not a new capability. -->

### Modified Capabilities
- `package-facades`: the layer facade path
  `yascheduler.adapters/__init__.py` becomes
  `yascheduler.infra/__init__.py`; the R2/R3 contract text, the
  `layers` contract configuration in `pyproject.toml`, the residual
  R3 edges documented in this spec, and the
  `[tool.setuptools.package-data]` key are updated to the new path.
  Requirements R1, R2, R3, the lazy-publication policy, the
  outside-layer-set exemptions, and the private-symbol carve-outs
  (including the `from .infra.cloud.adapters import _resolve_adapter`
  deep-path carve-out) are preserved verbatim in semantics; only the
  literal layer name changes.
- `platform-adapters`: the platform adapter module path
  `yascheduler/adapters/ssh/platform/adapters.py` becomes
  `yascheduler/infra/ssh/platform/adapters.py`; the class names
  (`debian_10_adapter` … `windows12_adapter`) and the
  `RemoteMachineAdapter` protocol are unchanged.
- `cloud-providers`, `cloud-provisioner`, `cloud-wrapper`: the cloud
  subpackage path `yascheduler/adapters/cloud/` becomes
  `yascheduler/infra/cloud/`; all file basenames, class names
  (`CloudAdapter`, `CloudProvisionerImpl`), and protocol names are
  preserved.
- `remote-machine-wrapper`, `ssh-gateway`: the SSH subpackage path
  `yascheduler/adapters/ssh/` becomes `yascheduler/infra/ssh/`;
  `SSHMachineGateway` and the retry exception tuples keep their names.
- `postgres-uow`, `sql-queries`: the persistence subpackage path
  `yascheduler/adapters/persistence/` becomes
  `yascheduler/infra/persistence/`; `PostgresUnitOfWork`,
  `apply_schema`, `load_query`, and the `sql/` tree are unchanged in
  content (only location).
- `cli-commands`: the CLI subpackage path
  `yascheduler/adapters/cli/` becomes `yascheduler/infra/cli/`; the
  six per-command modules keep their file basenames and function names.
- `webhook-handler`: the notifier subpackage path
  `yascheduler/adapters/notifier/` becomes
  `yascheduler/infra/notifier/`; `webhook_handler` keeps its name.
- `testing-unit`, `test-db-integration`, `e2e-testing`: test imports
  and `patch("…")` string targets under `tests/` are rewritten from
  `yascheduler.adapters…` to `yascheduler.infra…`; no test logic,
  fixtures, or assertions change.
- `use-cases`: the spec text normatively says use cases "SHALL NOT
  import from `yascheduler.adapters` at runtime" (and per-use-case
  variants) — the path references are rewritten to
  `yascheduler.infra`; the SHALL NOT semantics are preserved.
- `orchestrator`: the spec text says the `Orchestrator` "SHALL NOT
  import `AllSSHRetryExc`, `SFTPRetryExc`, or `backoff` from
  `yascheduler.adapters` at runtime" — the path reference is rewritten
  to `yascheduler.infra`; the SHALL NOT semantics are preserved.
- `domain-exceptions`: the requirement "CloudError is not re-exported
  from `yascheduler.adapters.cloud`" and its scenarios reference
  `from yascheduler.adapters.cloud import …` — these paths are
  rewritten to `yascheduler.infra.cloud`; the SHALL NOT re-export
  semantics are preserved.
- `uow-not-initialized-error`: the spec text requires the error to be
  provided "in `yascheduler.adapters.persistence.exceptions`" — the
  path is rewritten to `yascheduler.infra.persistence.exceptions`; the
  requirement semantics are preserved.

## Impact

- **Code**: ~61 files under `yascheduler/adapters/` move (directory
  rename); a handful of files outside that directory update one or a
  few import lines or comment references (`di.py`, `client.py`,
  `daemon_systemd.py`, `daemon_sysv.py`, `config/__init__.py`,
  `domain/{exceptions,model}.py` for comment references only).
- **Tests**: ~18 test files update imports and `patch("…")` string
  targets; no test bodies, fixtures, or assertions change.
- **Build config**: `pyproject.toml` — 6 script entry points, 1
  `layers` layer label, 1 `[tool.setuptools.package-data]` key. The
  `ignore_imports` array is empty and unchanged; the residual R3 edges
  live only in `package-facades/spec.md` text.
- **Docs**: `docs/ARCHITECTURE.md` (prose + 2 ASCII diagrams),
  `docs/knowledge-graph.xml` (every `<path>` under the renamed
  subpackages + 3 `M-*` module records whose `<path>` child points
  into the renamed tree).
- **GRACE-lite anchors**: `# FILE:` header comments and
  `START_MODULE_CONTRACT`/`MODULE_MAP`/`LINKS:`/`CHANGE_SUMMARY`
  annotations inside the moved files are rewritten to the new path.
  Module IDs in `knowledge-graph.xml` (`M-ADAPTERS`, `M-CLOUD`,
  `M-SSH`, etc.) are preserved.
- **Public API**: zero change. `yascheduler.__init__` exports, CLI
  command names, AiiDA entrypoint key, INI format, DB schema — all
  preserved.
- **Dependencies**: none added, none removed.
- **Verification**: `uv run pytest -m unit|integration|e2e`,
  `uv run lint-imports`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run zuban check`,
  `python3 scripts/grace_check.py`, and
  `openspec validate --all --json` must all pass after the rename.
## Context

`yascheduler/di.py` is the project's composition root — the single module that
wires `Orchestrator`, `CLIDeps`, and their dependencies. It sits at the package
root as an "outside-layer-set" module: exempt from the `layers` contract (R3)
but bound by R2 (facades for cross-package imports). Two archived changes
(`add-entrypoints-layer`, `relocate-daemon-launchers`) migrated every other
outside-layer-set module (`client`, `daemon_systemd`, `daemon_sysv`,
`aiida_plugin`) into `yascheduler/entrypoints/` and explicitly deferred `di.py`
to a follow-up. `openspec/specs/package-facades/spec.md` L264 carries the
standing "Scheduled for migration … in the interim" note.

Current state of `di.py` (v5.3.0, 227 lines, 7 symbols):

- Exports `make_daemon`, `make_cli_deps`, `CLIDeps`.
- Uses relative imports `.application`, `.domain`, `.infra` (valid at package
  root).
- Has 15 consumers: 6 production files in `entrypoints/cli/` and
  `entrypoints/client.py`, plus 7 test files (1 direct `test_di.py`, 5
  `test_cli_*.py`, 1 `test_full_cycle.py` e2e).
- `tests/unit/test_di.py` contains ~12 `patch("yascheduler.di.X")` targets.

`yascheduler.entrypoints` is already the top layer in the `layers` contract
(`pyproject.toml` L126), so a module moved there is automatically subject to
R3 — its imports must flow `entrypoints → infra → application → domain`. The
current imports of `di.py` already flow that way; the move is layer-legal.

`entrypoints/__init__.py` is a layer facade re-exporting only `Yascheduler`
today. `entrypoints/client.py` is the public API; `yascheduler/client.py` is a
compat shim preserving the deep import path for external consumers. There is
no `yascheduler/di.py` shim and none will be added — `di` is not public API
(none of `[project.scripts]` entries reference it).

## Goals / Non-Goals

**Goals:**
- Move `di.py` into `yascheduler/entrypoints/` so the composition root lives
  in the outermost hexagonal layer alongside its consumers.
- Close the deferred follow-up recorded in `package-facades/spec.md` L264.
- Keep factory signatures, runtime behavior, and the `Yascheduler.deps_factory`
  test seam unchanged — this is a pure relocation.
- Make the `entrypoints` layer facade the single import surface for CLI
  subpackages needing the composition root (R2 via facade, not deep
  sibling-cross-subpackage imports).
- Update the affected OpenSpec specs (`package-facades`,
  `dependency-injection`, `test-db-integration`) in the same change.

**Non-Goals:**
- No split into per-entrypoint factories (`cli/deps.py` + `daemon/deps.py`).
  Rejected in explore: `client.py` (non-CLI) consumes `CLIDeps`, and the two
  factories share `_setup_domain_events` + `PostgresUnitOfWork` construction.
- No compat shim at `yascheduler/di.py`. `di` is internal; no public surface
  exposes it.
- No lifting `CLIDeps` to a domain port. `Yascheduler.deps_factory` already
  provides the test seam.
- No rename of `tests/unit/test_di.py`. Neutral filename, pure aesthetics.
- No `pyproject.toml` edits. The `layers` contract already covers
  `entrypoints`.
- No change to `M-DI` ID or its `<depends>` list in the knowledge graph.

## Decisions

### D1 — Flat relocation to `entrypoints/di.py` (no subpackage)

**Choice:** Single file at `yascheduler/entrypoints/di.py`.

**Alternatives considered:**
- `entrypoints/cli/deps.py` + `entrypoints/daemon/deps.py` — rejected. The
  `entrypoints/daemon/` subpackage was liquidated in `relocate-daemon-launchers`;
  recreating it reverses that decision. More importantly, `client.py` (the
  public API, not a CLI) consumes `CLIDeps` and `make_cli_deps`, so a CLI-only
  location would force `client.py` to import from `entrypoints/cli/`, cementing
  "client is CLI-over-async." The two factories also share logic
  (`_setup_domain_events`, `PostgresUnitOfWork(config.db, bus)`), so a split
  duplicates or requires a `_common.py` — extra abstraction, no payoff.

**Rationale:** One file, one move, minimal diff. `client.py` imports a sibling
(`from .di import …`); `cli/` imports via the layer facade.

### D2 — Internal imports become absolute via layer facades

**Choice:** Inside the moved `di.py`:
```python
# before (at package root)
from .application import (Orchestrator, submit_task, AbstractUnitOfWork, …)
from .domain import (TaskCreated, TaskAllocated, …)
from .infra import (CloudProvisionerImpl, SSHMachineGateway, …)

# after (at entrypoints/di.py)
from yascheduler.application import (Orchestrator, submit_task, AbstractUnitOfWork, …)
from yascheduler.domain import (TaskCreated, TaskAllocated, …)
from yascheduler.infra import (CloudProvisionerImpl, SSHMachineGateway, resolve_adapter, webhook_handler, …)
```

**Rationale:** Relative `.application` / `.domain` / `.infra` no longer resolve
once `di.py` is inside `entrypoints/`. Absolute-via-facade is the project's R2
pattern for cross-package imports (every other entrypoints resident uses it).
`yascheduler.application`, `yascheduler.domain`, `yascheduler.infra` are all
layer facades, so this is R2-correct.

**Alternatives considered:**
- Keep relative by adding `entrypoints` to a hypothetical "root-relative
  exemption" — does not exist; R2 mandates facades for cross-package.

### D3 — `cli/` imports via the `entrypoints` facade; `client.py` uses sibling-relative

**Choice:**
- `entrypoints/cli/*.py`: `from yascheduler.entrypoints import make_daemon,
  make_cli_deps, CLIDeps` (via the layer facade).
- `entrypoints/client.py`: `from .di import CLIDeps, make_cli_deps`
  (sibling-relative, R1 within `entrypoints`).

**Rationale:** `cli/` is a subpackage of `entrypoints`; reaching a sibling
resident of its parent via a deep path (`from ..di import …`) is permitted by
R1 but bypasses the layer facade. The project convention (and the user's
explicit instruction during explore) is that subpackages consume composition
root symbols through the `entrypoints` facade, not via deep
sibling-cross-subpackage imports. `client.py` is a flat resident of
`entrypoints` (same level as `di.py`), so sibling-relative `from .di` is the
natural R1 form and does not cross a subpackage boundary.

**Consequence:** The `entrypoints/__init__.py` facade must be extended to
re-export `make_daemon`, `make_cli_deps`, `CLIDeps` (in addition to
`Yascheduler`). This is a public-surface change to the facade — captured as a
Modified Capability in `package-facades` spec.

### D4 — No compat shim

**Choice:** `yascheduler/di.py` is deleted; no re-export shim.

**Rationale:** `di` is the composition root, internal to the package by
definition. The public API surface declared in `pyproject.toml`
`[project.scripts]` is the CLI entry points (`yasubmit`, `yastatus`, `yanodes`,
`yasetnode`, `yainit`, `yascheduler`) and the AiiDA plugin entry
(`yascheduler = "yascheduler.entrypoints.aiida_plugin:YaScheduler"`); none
reference `yascheduler.di`. The public Python API is `Yascheduler` (in
`entrypoints/client.py`, already shimmed by `yascheduler/client.py`). Adding a
second shim for an internal module violates YAGNI and runs against the recent
trend of removing root-level compat modules.

**Breaking for:** any external importer of `from yascheduler.di import …`.
Unknown and architecturally anti-pattern; acceptable.

### D5 — `M-DI` knowledge-graph ID retained

**Choice:** In `docs/knowledge-graph.xml`, the `M-DI` element keeps its ID;
only `<path>` changes (`yascheduler/di.py` →
`yascheduler/entrypoints/di.py`). `<depends>` is unchanged. All `CrossLink`
references to `M-DI` remain valid.

**Rationale:** The module's identity, purpose, and dependencies do not change —
only its filesystem location. Renaming the ID would force a cascade of
`CrossLink` updates for zero semantic gain.

### D6 — Stale `_resolve_adapter` R2 carve-out removed

**Choice:** `package-facades/spec.md` L436 documents a carve-out for
`yascheduler/di.py: from .adapters.cloud.adapters import _resolve_adapter`,
calling it the "only R2 carve-out in the codebase." This is stale: the symbol
was renamed `_resolve_adapter` → `resolve_adapter` (public) in the
`review-hardening` change and is now imported by `di.py` L51 via
`from .infra import resolve_adapter` (the `infra` layer facade). The carve-out
paragraph is removed in this change.

**Rationale:** The spec should match reality. Leaving a carve-out for a symbol
that no longer exists under that name is a latent inconsistency; this change
already touches the same spec section, so cleaning it is cheaper than a
separate change.

### D7 — `test_di.py` filename kept

**Choice:** `tests/unit/test_di.py` is not renamed.

**Rationale:** The filename does not encode a path; it names the module under
test (`di`). Renaming to `test_entrypoints_di.py` is pure aesthetics and would
diffuse the change. The import paths and `patch()` targets inside the file are
updated; the filename stays.

## Risks / Trade-offs

- **[Risk] External downstream code imports `from yascheduler.di import …` and
  breaks on upgrade.** → Mitigation: `di` is internal composition root, not
  public API; no `[project.scripts]` entry references it. The breaking change
  is called out in the proposal Impact and the change is a major-version
  candidate per the project's stability policy. No shim is added (YAGNI).

- **[Risk] Missed `patch("yascheduler.di.X")` target in a test, causing a
  silent no-op patch.** → Mitigation: `tests/unit/test_di.py` has ~12 such
  targets (enumerated in explore-brief); tasks.md includes an explicit
  grep-and-replace step with a verification command
  (`rg "yascheduler\.di\b"` returning zero matches across the repo after the
  rewrite). The same grep catches any forgotten import.

- **[Risk] `entrypoints/__init__.py` facade extension creates an import cycle.**
  → Mitigation: `di.py` does not import from `entrypoints/__init__.py` (it
  imports only from `yascheduler.application`, `yascheduler.domain`,
  `yascheduler.infra`). `__init__.py` imports from `.di` and `.client`; `.client`
  imports from `.di` (sibling). No cycle: `__init__ → di → {application,
  domain, infra}` and `__init__ → client → di`; `di` never imports `__init__`
  or `client`.

- **[Risk] `import-linter` layers contract flags `entrypoints/di.py` for
  importing `infra`/`application`/`domain`.** → Mitigation: the `layers`
  contract direction is `entrypoints → infra → application → domain → shared`;
  `di.py`'s imports flow exactly that way. The contract was already correct;
  no `pyproject.toml` change is needed. Verify with `lint-imports` in the
  implementation phase.

- **[Trade-off] The composition root is now subject to R3 (layer direction)
  whereas before it was exempt.** → Acceptable: its imports already comply.
  The exemption was only needed because the module sat at the package root
  outside any layer; once inside `entrypoints`, the layer contract naturally
  covers it.

- **[Trade-off] `cli/` must go through the facade even though `from ..di` would
  compile.** → Acceptable: the project convention (and explicit user direction)
  is that subpackages consume composition-root symbols via the layer facade.
  This keeps `cli/` decoupled from the internal layout of `entrypoints`.

## Migration Plan

Single-PR mechanical migration; no runtime behavior change, no DB schema
change, no config format change.

1. `git mv yascheduler/di.py yascheduler/entrypoints/di.py`.
2. Rewrite imports inside `entrypoints/di.py` (relative → absolute via
   facades) per D2; update `# FILE:` header and `START_CHANGE_SUMMARY`.
3. Extend `entrypoints/__init__.py` facade per D3; update its
   `MODULE_CONTRACT`, `MODULE_MAP`, `CHANGE_SUMMARY`, VERSION.
4. Rewrite the 6 production consumer imports per the table in the
   explore-brief.
5. Rewrite the 7 test file imports and ~12 `patch()` targets in
   `test_di.py`.
6. Update `docs/knowledge-graph.xml` `M-DI` `<path>`.
7. Update `docs/ARCHITECTURE.md` §2.8 heading path.
8. Update OpenSpec specs: `package-facades` (D6 + outside-layer-set removal +
   consumer descriptions), `dependency-injection` (requirement rename +
   paths), `test-db-integration` (patch path).
9. Run `rg "yascheduler\.di\b"` repo-wide; expected zero matches.
10. Run `uv run pytest -m unit`, `uv run lint-imports`,
    `uv run ruff check .`, `uv run zuban check`, `python3 scripts/grace_check.py`,
    `openspec validate --all --json`.

**Rollback:** `git revert` the single PR. No data, no config, no external
state involved.

## Open Questions

None. All E1–E9 decisions from explore are captured above (D1–D7 map to
E1/E2/E3/E5/E7/E8; E4/E6/E9 are mechanical steps in the Migration Plan).
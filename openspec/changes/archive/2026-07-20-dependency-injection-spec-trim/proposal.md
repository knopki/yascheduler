## Why

`openspec/specs/dependency-injection/spec.md` (176 lines, 6 requirements, 20 scenarios)
interleaves actual SHALL requirements with content kinds that GRACE assigns to
code-local contracts, not to spec text:

1. **Invented `SHALL NOT` negative-space regression guards** — 5 instances
   enumerating absent code or non-behavior as normative requirements:
   - "The composition root SHALL NOT introduce a DB-facade class."
   - "The composition root SHALL NOT use `typing.cast` to bridge between the
     domain `CloudConfig` Protocol and the infra `ConfigCloud` Union."
   - "The `make_daemon` function SHALL NOT accept a `log` parameter."
   - "The composition root SHALL NOT create or thread a logger into
     collaborators."
   - "The module SHALL NOT import from `remote_machine/` or `clouds/`."
   Every one is already asserted by a Gherkin scenario (No DB-facade import;
   make_daemon does not accept a log parameter; Three collaborators constructed
   without log argument) or is a non-existent code path dressed up as a
   normative requirement (`remote_machine/` was dissolved; `clouds/` is governed
   by the `layers` contract R3). The prose is drift bait.
2. **Design rationale living in the spec** — the "This ensures a single
   connection registry spans cloud setup and orchestrator runtime, so that
   connections opened during cloud allocation are visible to the orchestrator
   and are reaped by `Orchestrator.stop()` via `repository.disconnect_all()`"
   narrative, the "each binds its own module-local `YaLogger` via
   `get_logger("M-...")` at module top" implementation detail, the
   "`CloudProvisionerImpl` is constructed with `machine_repository` only — it
   no longer takes any operations-side parameter or a `log` parameter"
   regression aside, the "CloudProvisionerImpl SHALL be constructed WITHOUT
   any operations-side parameter AND WITHOUT a `log=` keyword argument"
   restatement, and the "the caller-supplied `clouds` retain whatever
   repository it was built with" duplication of its own scenario. These
   answer *why the code is shaped this way* — they belong in `RATIONALE` /
   `INVARIANTS` / `SCOPE` on the owning entity, not in spec.
3. **Layering narrative dressed as a per-module negative requirement** — the
   `DI factories in yascheduler.entrypoints.di` requirement restates the
   `layers` contract (R3) inline as a per-module `SHALL NOT import`. The
   layers contract already governs every `entrypoints` module; restating it
   here creates a maintenance hazard and a false positive on layers-contract
   refactors.

In parallel, the code under `yascheduler/entrypoints/` violates the GRACE
Python rule ("if an entity is annotated by markup, it must always be wrapped
in a region"):

- `yascheduler/entrypoints/client.py` declares `class Yascheduler` with
  seven nested `METHOD_*` regions but no enclosing `CLASS_Yascheduler`
  region — the class itself is unwrapped.
- `yascheduler/entrypoints/client.py` declares `_task_to_dict` (a ~40-line
  non-trivial projection) with no `FUNC_*` region.
- Where regions exist (`MODULE_CONTRACT`, `CLASS_CLIDeps`, `METHOD_submit`,
  `FUNC__setup_domain_events`, `FUNC_make_daemon`, `FUNC_make_cli_deps` in
  `di.py`; `MODULE_CONTRACT`, `FUNC_to_sync`, the seven `METHOD_*` regions in
  `client.py`), they carry `PURPOSE` only and the `PURPOSE` text has slipped
  to WHAT (descriptions) rather than WHY (the goal/reason the entity exists).
  The rationale/invariants/scope that should accompany the code is missing
  because it currently sits in the spec.

## What Changes

- **MODIFIED `dependency-injection`**: rewrite all 6 requirements to carry
  only behavioral contracts (SHALL statements + Gherkin scenarios). Remove
  the 5 invented `SHALL NOT` enumerations of absent code, the shared-repository
  rationale paragraph, the "constructed WITHOUT ..." regression asides, the
  implementation-detail sentences about `YaLogger` binding, the duplicated
  pre-built-clouds prose, and the inline layers-contract restatement. Every
  observable behavioral scenario (20) survives unchanged. No requirement is
  added, removed, merged, or split; the 6 requirement headers stay identical
  so OpenSpec recognizes the MODIFIED operation.
- Add the missing `CLASS_*` and `FUNC_*` regions required by the GRACE Python
  rule: `CLASS_Yascheduler` enclosing the full `class Yascheduler:` block in
  `client.py` (the nested `METHOD_*` regions stay INSIDE the new `CLASS_*`);
  `FUNC__task_to_dict` enclosing the full projection function in `client.py`.
- Enrich existing `MODULE_CONTRACT`, `CLASS_*`, `METHOD_*`, and `FUNC_*`
  regions with the rationale/invariants/scope that leaves the spec, each in
  its correct GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g.
    `make_daemon` constructs exactly one `SSHMachineRepository` on the
    `clouds is None` path; `make_daemon` accepts no `log` parameter;
    `make_daemon` imports no DB-facade class and uses no `typing.cast` to
    bridge the domain `CloudConfig` Protocol and the infra `ConfigCloud`
    Union; collaborators bind their own loggers, none are threaded from the
    composition root; `Yascheduler.deps_factory` is keyword-only, defaults
    to `make_cli_deps` when `None`, is invoked once per query call to produce
    a fresh `CLIDeps`, and is NOT awaited).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why one shared `SSHMachineRepository` spans cloud allocation and
    orchestrator runtime; why each collaborator module binds its own logger;
    why the composition root refuses to introduce a DB-facade or a
    `typing.cast` bridge; why `CLIDeps` is a lightweight dataclass with no
    SSH/cloud/http dependencies; why the int↔`TaskId` marshalling boundary
    lives on the `Yascheduler` facade).
  - `SCOPE` declares the entity's functional boundaries with explicit `NOT:`
    exclusions where useful (e.g. `di.py` `MODULE_CONTRACT` `NOT:` clause
    captures the layers-contract commitment that the module imports nothing
    from `yascheduler.infra.clouds.*` subpaths).
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `RAISES:`, no
  free-form labels. The spec's removed `SHALL NOT` sentences do NOT become a
  `SHALL NOT:` contract field — they become an `INVARIANTS` entry stating
  the positive contract, or a `RATIONALE` Q/A if the rationale is the
  valuable part.
- Every `CLASS_*` region encloses the FULL class body — the `class` line
  (and any decorator), the docstring, every field, every `__init__` line,
  every `self.<attr>` assignment — through the trailing blank line before
  the next region marker; nested `METHOD_*` / `BLOCK_*` regions live INSIDE
  the enclosing `CLASS_*` region, with the `CLASS_*` `# endregion` placed
  AFTER the last nested `# endregion`. Every `FUNC_*` region encloses the
  decorator (if any), the `def`/`async def` line, the body, and the trailing
  blank line. No region closes before its entity ends.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `dependency-injection`: requirements slimmed to SHALL statements and
  behavior scenarios; invented `SHALL NOT` negative-space language, shared-
  repository rationale, collaborator-logger implementation detail, regression
  asides, and one inline layers-contract restatement relocated out of the
  spec text and into GRACE code contracts across
  `yascheduler/entrypoints/di.py` and `yascheduler/entrypoints/client.py`.
  No DI behavior, factory signature, factory parameter, scenario, exit code,
  public API, or import path is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/dependency-injection/spec.md` rewritten — every
  requirement trimmed to behavioral SHALL + scenarios; pre/post scenario
  count compared and MUST remain 20 → 20. `openspec validate --all --json`
  must still pass after the change.
- **Code (markup only, no logic)**: `yascheduler/entrypoints/di.py`,
  `yascheduler/entrypoints/client.py` — existing `MODULE_CONTRACT` /
  `CLASS_CLIDeps` / `METHOD_submit` / `FUNC__setup_domain_events` /
  `FUNC_make_daemon` / `FUNC_make_cli_deps` / `FUNC_to_sync` / seven
  `METHOD_*` regions enriched with `INVARIANTS` / `RATIONALE` / `SCOPE`;
  new `CLASS_Yascheduler` region added (enclosing the full class block with
  all nested `METHOD_*` regions inside); new `FUNC__task_to_dict` region
  added. No code logic, signature, decorator, docstring semantics, or import
  changes. Code contracts absorb what leaves the spec, comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing DI unit tests (`tests/unit/test_di.py`),
  client tests (`tests/unit/test_client_query.py`,
  `tests/unit/test_characterization.py`), CLI smoke tests
  (`tests/unit/test_cli_smoke.py`), and daemon-common tests
  (`tests/unit/test_daemon_common.py`,
  `tests/unit/test_daemon_common_cleanup.py`) already assert them. A passing
  `uv run pytest -m unit` run after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config, DB
  schema, public API, or log-format change in the diff. The diff is
  `# region` / `# endregion` markup + comment-field enrichment + spec text
  trim only.
- **Pilot scope**: this change ONLY dehydrates the `dependency-injection`
  spec. Other specs (`cli`, `cloud`, `orchestrator`, `use-cases`, etc.) are
  explicitly out of scope. Follows the pattern set by `cli-spec-trim`,
  `cloud-spec-trim`, `config-value-objects-spec-trim`,
  `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`, and
  `2026-07-18-slim-domain-ports-spec`.
- **Non-goals**:
  - No change to any DI behavior, factory signature, factory parameter,
    return type, scenario, exit code, public API, or import path.
  - No spec split; all trimmed requirements remain in the
    `dependency-injection` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No rewrite of `yascheduler/entrypoints/__init__.py` (the package facade
    — already minimal and WHY-shaped), `yascheduler/entrypoints/config.py`,
    `yascheduler/entrypoints/config_parser.py`,
    `yascheduler/entrypoints/_config_utils.py`,
    `yascheduler/entrypoints/paths.py`,
    `yascheduler/entrypoints/aiida_plugin.py` (out of capability scope).

## Why

`openspec/specs/engine-config-parsing/spec.md` (39 lines, 1 requirement, 5
scenarios) is already small but interleaves three content kinds that GRACE
assigns to code-local contracts, not to spec text:

1. **Invented negative-space normative language.** The requirement body says
   "The validators SHALL run parser-side (raising `ValueError` on invalid INI),
   not in `Engine.__post_init__`." The tail "not in `Engine.__post_init__`"
   describes absent code as a normative requirement — `Engine` has no
   `__post_init__` at all (verified: zero hits for `__post_init__` in
   `yascheduler/domain/engine.py`). This is precisely the negative-space
   pattern the project's prior trims removed from `cloud`, `domain-exceptions`,
   and `domain-ports`. The observable behavior — "validators raise `ValueError`
   on invalid INI at parse time" — is already asserted by the three
   `parse_engine_section rejects ...` scenarios, so the prose is drift bait.
2. **Design rationale living in the spec.** The spec Purpose ("Decouple engine
   INI parsing from the domain model so the domain spec does not reference an
   entrypoints module.") answers *why the parser lives in `entrypoints/` and the
   `Engine` value object lives in `domain/`* — a layering rationale, not a
   behavioral contract. `domain/engine.py` already carries the inverse half of
   this rationale on its `MODULE_CONTRACT` ("Why are these types in the domain
   layer instead of in config? A: ... Keeping them in domain prevents use cases
   from depending on the config module."); the parser-side half has no home in
   code today and should land as `RATIONALE` on `entrypoints/config_parser.py`'s
   `MODULE_CONTRACT`.
3. **Narrative that duplicates a scenario.** The requirement body says
   "`engine_valid_fields()` SHALL return the valid INI keys for an
   `[engine.*]` section, including the deploy alias fields
   (`deploy_local_files`, `deploy_local_archive`, `deploy_remote_archive`) and
   excluding the `name` and `deployable` dataclass fields." The
   `engine_valid_fields returns INI key list` scenario already enumerates the
   included and excluded keys as acceptance criteria — the prose restates the
   scenario verbatim. The include/exclude *rule* (deploy aliases in;
   dataclass-name and `deployable` out) is an `INVARIANT` of the function, not
   a spec sentence.

In parallel, the code under `yascheduler/entrypoints/config_parser.py` (the
engine regions) violates the GRACE proportional-coverage expectation set by
the recent trims:

- The three engine-side validator helpers — `_check_spawn`, `_check_check_`,
  `_check_at_least_one_elem` — live under the `MODULE_CONTRACT` with no
  entity-level region, even though they are the literal "parser-side
  validators" the spec's removed sentence refers to. The function they validate
  inside (`FUNC_parse_engine_section`) names them in the `BLOCK_validate_engine`
  region, but the helpers themselves carry no contract.
- The four engine-related regions that *do* exist (`MODULE_CONTRACT`,
  `FUNC_engine_valid_fields`, `FUNC_parse_engine_section`, `FUNC_parse_engines`)
  carry `PURPOSE` only; the rationale/invariants/scope that should accompany
  the code is missing because it currently sits in (or is implied by) the spec.
- `CLASS_Engine` in `yascheduler/domain/engine.py` carries `PURPOSE` only and
  has no `INVARIANTS` recording that validation lives outside the dataclass —
  the very property the spec's negative-space sentence tries to enforce.

## What Changes

- **MODIFIED `engine-config-parsing`**: rewrite the single requirement `Engine
  INI parser functions` to carry only behavioral contracts (SHALL statements +
  Gherkin scenarios). Remove (a) the negative-space tail "not in
  `Engine.__post_init__`" and (b) the duplicated `engine_valid_fields`
  narrative (the scenario is the truth). Every observable behavioral scenario
  (5) survives unchanged. The requirement header stays identical so OpenSpec
  recognizes the MODIFIED operation.
- Leave the spec `## Purpose` ("Decouple engine INI parsing from the domain
  model so the domain spec does not reference an entrypoints module.")
  unchanged: it is already a one-sentence capability-level WHY. The detailed
  layering rationale (how the decoupling is achieved — parser lives in
  `entrypoints/`, `Engine` is a plain frozen dataclass with no parser
  references, validation lives in `_check_*` helpers) moves to code via the
  next bullets, at a different level of detail than the spec Purpose.
- Enrich existing `MODULE_CONTRACT`, `FUNC_engine_valid_fields`,
  `FUNC_parse_engine_section`, `FUNC_parse_engines` regions in
  `yascheduler/entrypoints/config_parser.py` with the
  rationale/invariants/scope that leaves the spec, each in its correct GRACE
  field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
  - `INVARIANTS` carries conditions/contracts that always hold (e.g. the
    parser-side validators raise `ValueError`; the parser performs no
    `Engine.__post_init__` validation; `engine_valid_fields` includes the three
    deploy aliases and excludes `name` + `deployable`).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (e.g.
    why the parser layer owns validation, not the `Engine` dataclass).
  - `REQUIRES` / `ENSURES` carry pre/postconditions on the parser functions.
- Add `FUNC_*` regions on the three currently-unwrapped engine-side validator
  helpers (`_check_spawn`, `_check_check_`, `_check_at_least_one_elem`), so the
  "validators run parser-side" invariant has a literal home in markup. Each new
  region encloses the full function (`def` line, body, trailing blank).
- Enrich existing `CLASS_Engine` in `yascheduler/domain/engine.py` with
  `INVARIANTS` recording that the dataclass is plain frozen (no
  `__post_init__`) and that all INI-time validation lives in
  `entrypoints/config_parser`'s `_check_*` helpers and `parse_engine_section`.
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:` pseudo-field, no `RAISES:`, no
  `EXAMPLES:`, no free-form labels. The spec's removed "not in
  `Engine.__post_init__`" sentence does NOT become a `SHALL NOT:` contract
  field — it becomes an `INVARIANTS` entry on `CLASS_Engine` stating the
  positive contract ("plain frozen dataclass; no `__post_init__`; validation
  lives in the parser").
- Every `CLASS_*` / `FUNC_*` region encloses the FULL entity — for a function:
  the decorator (if any), the `def` line, the body, the trailing blank line
  before the next region marker. A region that closes before its entity ends
  (e.g. wrapping only the contract comment) is a defect. For `CLASS_Engine`,
  the existing region already encloses the full class body (decorator + class
  line + docstring + every field + the nested `METHOD_validate_inputs`); the
  enrichment is comment-only inside the existing region — no `# endregion`
  moves.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `engine-config-parsing`: requirement slimmed to SHALL statements and behavior
  scenarios; the negative-space "not in `Engine.__post_init__`" tail, the
  duplicated `engine_valid_fields` narrative, and the spec-Purpose layering
  rationale relocated out of the spec text and into GRACE code contracts on
  `yascheduler/entrypoints/config_parser.py` (engine regions) and
  `yascheduler/domain/engine.py` (`CLASS_Engine`). No engine-parsing behavior,
  function signature, deploy-strategy shape, scenario, INI key, or public API
  is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/engine-config-parsing/spec.md` rewritten — the
  single requirement trimmed to behavioral SHALL + scenarios; pre/post scenario
  count compared and MUST remain 5 → 5. `openspec validate --all --json` must
  still pass after the change.
- **Code (markup only, no logic)**:
  `yascheduler/entrypoints/config_parser.py` — existing `MODULE_CONTRACT`,
  `FUNC_engine_valid_fields`, `FUNC_parse_engine_section`, `FUNC_parse_engines`
  regions enriched with `INVARIANTS` / `RATIONALE` / `REQUIRES` / `ENSURES`;
  three new `FUNC_*` regions added for `_check_spawn`, `_check_check_`,
  `_check_at_least_one_elem`. `yascheduler/domain/engine.py` — existing
  `CLASS_Engine` region enriched with `INVARIANTS`. No code logic, signature,
  decorator, docstring semantics, or import changes. Code contracts absorb
  what leaves the spec; comment-only diff.
- **Tests**: no change. Existing scenarios in the trimmed spec remain the
  acceptance criteria; existing tests already assert them
  (`tests/unit/test_config.py::test_engine_valid_parsing`,
  `test_engine_invalid_spawn_template`, `test_engine_missing_check_methods`,
  `test_engine_empty_input_files`;
  `tests/unit/test_parse_engine_spawn_required.py::test_parse_engine_section_raises_value_error_on_missing_spawn`).
  A passing `uv run pytest -m unit` after the change is the regression guard.
- **Public surface**: none. No CLI command, console_script, INI config key, DB
  schema, public API, or log-format change in the diff. The diff is
  `# region` / `# endregion` markup + comment-field enrichment + spec text
  trim only.
- **Pilot scope**: this change ONLY dehydrates the `engine-config-parsing`
  spec. Other specs (`cloud`, `cli`, `use-cases`, `domain-entities`,
  `ssh-infrastructure`, etc.) are explicitly out of scope. Follows the pattern
  set by `2026-07-17-orchestrator-spec-dehydrate`,
  `2026-07-17-domain-entities-spec-trim`,
  `2026-07-17-domain-events-spec-trim`,
  `2026-07-18-domain-exceptions-spec-trim`,
  `2026-07-18-slim-domain-ports-spec`, and the in-flight `cli-spec-trim`,
  `cloud-spec-trim`, `config-value-objects-spec-trim`,
  `db-migrations-spec-trim`, `dependency-injection-spec-trim`,
  `e2e-testing-spec-trim`, and the sibling trims in flight.
- **Non-goals**:
  - No change to any engine-parsing behavior, deploy-strategy shape, parser
    rule, INI key, scenario wording, or import path.
  - No spec split; the single requirement remains in the `engine-config-parsing`
    capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No markup additions to the cloud / db / local / remote / `parse_config`
    assembly regions of `yascheduler/entrypoints/config_parser.py` — those are
    owned by other capabilities (and the in-flight `cloud-spec-trim` for the
    cloud regions); only the engine-related regions and the three engine-side
    validator helpers are touched here.
  - No markup additions to the three `Deploy` value-object dataclasses
    (`LocalFilesDeploy`, `LocalArchiveDeploy`, `RemoteArchiveDeploy`) in
    `yascheduler/domain/engine.py` — they are trivial single-field frozen
    dataclasses and are skipped per the GRACE proportional rule.
  - No rewrite of `yascheduler/domain/engine.py` `MODULE_CONTRACT` (already
    tight, WHY-shaped, and carries the inverse half of the layering rationale);
    only `CLASS_Engine` is enriched.

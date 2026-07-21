## Why

`openspec/specs/package-facades/spec.md` (366 lines, 12 requirements, 43 scenarios)
interleaves the actual SHALL requirements with content kinds that GRACE assigns to
code-local contracts, not to spec text:

1. **Implementation invariants dressed up as spec requirements** —
   `Yascheduler facade public contract` carries 91 lines of method/dict-shape
   prose that is partly genuine public contract (the dict shape
   `{task_id, label, status, metadata, node}`) and partly code-local
   implementation detail:
   - "A single extraction helper SHALL be the sole extraction site and SHALL
     construct the `metadata` Mapping inline" (the single-helper invariant
     belongs on the helper itself; the public contract is only the resulting
     shape).
   - "The `Yascheduler` facade is the **sole** `int`/`TaskId` marshalling
     boundary, in both directions: on input ... it wraps `TaskId(task_id)` /
     `[TaskId(i) for i in jobs]`; on output it extracts `.value`" (the
     marshalling strategy belongs on `CLASS_Yascheduler` INVARIANTS +
     RATIONALE; the public contract is only that the values stay bare `int`).
   - "`queue_submit_task(...) -> int` SHALL stay `int`; it wraps `submit_task`
     (which returns `TaskId`) and returns `(await submit_task(...)).value`"
     (the `.value` unwrap belongs on `METHOD_queue_submit_task_async`
     ENSURES; the public contract is only the `int` return).
   - "The public contract is keyed on the resolvable symbol and applies
     identically whether `Yascheduler` is imported via the package facade,
     the entrypoints layer facade, or the compat shim" (the
     import-path-equivalence design choice belongs on `CLASS_Yascheduler`
     RATIONALE; the public contract is only that all three paths resolve the
     same symbol).

2. **Design rationale living in the spec body** — five distinct pieces:
   - The "composition root is a resident of this layer and is subject to this
     R3 contract; its imports flow `entrypoints → infra → application →
     domain`, which is layer-legal" aside on R3 (this answers *why the
     composition root's imports don't violate R3*, not *what the rule is*).
   - The contrapositive restatement of each layer's permission in R3 body
     ("`yascheduler.infra` may import from `yascheduler.application`,
     `yascheduler.domain`, and `yascheduler.shared`" — already implied by the
     `→` direction in the SHALL statement).
   - The "Subpackage facades ... are internal organization of the `adapters`
     layer" framing in R2 (this answers *why subpackage facades are not
     cross-layer-public*, not *what R2 requires*).
   - The "public contract is keyed on the resolvable symbol, NOT on the file
     path that defines it" rationale in `Public API stability` (this answers
     *why the contract is symbol-keyed*, not *what the rule is*).
   - The "(`no compat shim`; breaking changes with no known downstream
     callers)" parenthetical enumerating absent compat shims for
     `yascheduler.aiida_plugin` / `yascheduler.shared.to_sync` /
     `yascheduler.shared.async_utils` (this answers *why those paths are
     not preserved*, not *what the contract is*).

3. **Invented `SHALL NOT` negative-space regression guards** — 7 instances
   enumerating absent code or non-existent code paths dressed up as normative
   requirements:
   - R1 body: "The `yascheduler.infra.cli` subpackage is liquidated; no
     `yascheduler.infra.cli` package exists, so no within-package
     relative-import scenario applies to it" (the package simply does not
     exist; nothing to enforce).
   - R1 scenario THEN tail: "`show_nodes` and `submit` are NOT re-exported by
     the facade" (these symbols are simply absent from the facade's `__all__`;
     absence is not a behavior).
   - Compat-shim body: "SHALL NOT re-export `Config` or contain any business
     logic" (already asserted by the positive "re-export exactly
     `Yascheduler`" + the "Shim does not re-export Config" scenario).
   - Layers-contract body: "No `forbidden` contract entry exists" (the
     absent contract is not behavior; the `layers` contract is the only
     contract and that is the positive contract).
   - Layers-contract scenario THEN tail: "no `forbidden` contract entry
     exists" (same negative-space restatement).
   - Public-API-stability body: "are NOT preserved (no compat shim; breaking
     changes with no known downstream callers)" (the enumeration of absent
     shims is drift bait; the positive "what IS preserved" bullets above it
     are the contract).
   - R2 body: "Direct imports of submodules from outside the package bypass
     the public surface and SHALL NOT appear in any import" (restating the
     positive "SHALL import via `__init__.py` only" by negation).

   Every one is either already asserted by a positive scenario / already
   present in the facade `__all__` in code, or describes a non-existent code
   path dressed up as a normative requirement. The negative prose is drift
   bait — a future reader cannot tell whether the prohibition guards real
   code or merely documents absence.

4. **Code-detail leakage into spec** — two instances:
   - Compat-shim body: "`__all__ = ["Yascheduler"]`" is a Python literal
     that belongs in the compat-shim MODULE_CONTRACT INVARIANTS, not in spec
     prose.
   - Layers-contract body: "and dev dependency `import-linter >=2.5,<2.6`"
     is a `pyproject.toml` line, not a behavioral contract. The behavior is
     "the layers contract runs as part of the import-linter check"; the
     version pin is a build-system detail.

In parallel, the code under the facade path carries GRACE markup that is
either missing entirely or holds `PURPOSE`/`SCOPE`/`KEYWORDS` only:

- `yascheduler/entrypoints/client.py` ships a 109-line `class Yascheduler:`
  with seven nested `METHOD_*` regions but NO enclosing `CLASS_Yascheduler`
  region — the GRACE Python rule ("if an entity is annotated by markup, it
  must always be wrapped in a region") is violated because the nested
  `METHOD_*` regions are orphaned. The class-level INVARIANTS (sole
  int/TaskId marshalling boundary; constructor takes `config_path` +
  `deps_factory=`, not a `Config` aggregate) and RATIONALE (why the
  marshalling boundary lives at the facade; why the constructor takes
  unpacked settings; why the import-path-equivalence holds across the three
  facades) that should accompany the class are absent because they currently
  sit in the spec.
- `_task_to_dict` — a 38-line module-level private helper that builds the
  public Mapping shape — is currently unwrapped. It is non-trivial (builds
  the canonical dict shape with None-omission and extra-merge semantics),
  so per "Mark up all public and non-trivial code" it deserves a
  `FUNC__task_to_dict` region. The "single extraction helper" invariant and
  the metadata-shape contract currently sit in the spec because the helper
  has no region to receive them.
- `yascheduler/{__init__,entrypoints/__init__,infra/__init__,application/__init__,shared/__init__,client}.py`
  carry `MODULE_CONTRACT` regions with `PURPOSE`/`SCOPE`/`KEYWORDS` only.
  The INVARIANTS / RATIONALE that should accompany each facade — why one
  layer facade, why the compat shim exists, why the composition root lives
  in entrypoints, why `yascheduler.shared` is typing-shims-only — are
  absent because they currently sit in the spec.

## What Changes

- **MODIFIED `package-facades`**: rewrite all 12 requirements to carry only
  behavioral contracts (SHALL statements + Gherkin scenarios). Remove the
  implementation invariants (single-helper, marshalling-boundary, `.value`
  unwrap), the design rationale (composition-root residence, subpackage-facade
  organization, symbol-keyed contract, no-compat-shim enumeration), the 7
  invented `SHALL NOT` negative-space enumerations, the code-detail leakage
  (`__all__` literal, `import-linter` version pin), and the contrapositive
  layer-permission restatement. Plus one factual correction: the
  `Entrypoints layer facade` requirement body and scenario list `Config`
  alongside the 7 previously-named symbols and the scenario THEN says "all
  eight symbols" (the original said "seven" and omitted `Config` — a
  pre-existing spec/code mismatch; `yascheduler/entrypoints/__init__.py`
  `__all__` already exports 8 symbols including `Config`). Every observable
  behavioral scenario (43)
  survives unchanged; the THEN-clause trims are: 5 negative-space tails
  enumerated in Why § 3 (the `show_nodes` / `submit` absent-re-export
  enumeration, the `no forbidden contract entry exists` absent-contract
  enumeration, the `— never from any other yascheduler layer` restatement,
  the `— no domain entities, no use-case orchestration, no I/O`
  enumeration, and the `; the daemonize module has moved to the
  entrypoints layer` historical note); plus 3 design-rationale tails
  (`Infra imports from entrypoints — violation` drops the
  "(driven layers may not import upward into driving adapters)" paren,
  `Composition root imports from infra — allowed` drops the
  "(composition root is a resident of yascheduler.entrypoints and its
  imports flow in the layer direction)" paren, and `Within-layer
  cross-subpackage imports also use the layer facade` drops the
  "— the layer facade is the single public surface, even for sibling
  subpackages within the same layer" tail). The scenario headers and
  WHEN clauses are unchanged. No requirement is added, removed,
  merged, or split; all 12 requirement headers stay identical so OpenSpec
  recognizes the MODIFIED operation.
- Wrap the 2 currently-unwrapped non-trivial entities required by the GRACE
  Python rule + the proportional rule:
  - `CLASS_Yascheduler` on `yascheduler/entrypoints/client.py` — the
    enclosing region the seven nested `METHOD_*` regions are missing.
  - `FUNC__task_to_dict` on `yascheduler/entrypoints/client.py` — the
    single-helper extraction site the spec currently describes.
- Enrich existing `MODULE_CONTRACT` regions on
  `yascheduler/__init__.py`, `yascheduler/entrypoints/__init__.py`,
  `yascheduler/entrypoints/client.py`, `yascheduler/entrypoints/di.py`,
  `yascheduler/client.py`, `yascheduler/shared/__init__.py`,
  `yascheduler/infra/__init__.py`, `yascheduler/application/__init__.py`
  with the INVARIANTS / RATIONALE that leaves the spec, each in its correct
  GRACE field per its defined purpose:
  - `PURPOSE` answers WHY (what the entity enables), not WHAT (a description).
    Audit the existing `PURPOSE` lines for WHAT-drift; tighten any that have
    slipped.
  - `INVARIANTS` carries conditions/contracts that always hold (the facade
    `__all__` contents; sole-public-surface for cross-layer consumers;
    single-helper extraction site; sole int/TaskId marshalling boundary;
    typing-shims-only contents of `yascheduler.shared`; the compat shim's
    `__all__ = ["Yascheduler"]`).
  - `RATIONALE` is Q/A format only — why the entity is shaped this way (why
    one layer facade instead of letting consumers import submodules; why
    the compat shim exists; why the composition root lives in entrypoints;
    why the marshalling boundary is on `Yascheduler` and not on a deeper
    helper; why the public contract is keyed on the resolvable symbol and
    not on the file path).
- No invented GRACE field names. Allowed fields only: `PURPOSE`, `SCOPE`,
  `INVARIANTS`, `USECASES`, `DEPENDENCIES`, `RATIONALE`, `KEYWORDS`,
  `REQUIRES`, `ENSURES`. No `SHALL NOT:`, no `EFFECTS:`, no `EXAMPLES:`, no
  `RAISES:`, no free-form labels. The spec's removed `SHALL NOT` sentences
  do NOT become a `SHALL NOT:` contract field — they become an `INVARIANTS`
  entry stating the positive contract, or a `RATIONALE` Q/A if the
  rationale is the valuable part, or are simply cut when neither invariant
  nor rationale is the valuable part (pure absence enumeration).
- Every `CLASS_*` / `FUNC_*` / `METHOD_*` region encloses the FULL entity.
  For `CLASS_Yascheduler`: the `class Yascheduler:` line, the docstring,
  every class-level attribute (`STATUS_TO_DO`, `STATUS_RUNNING`,
  `STATUS_DONE`, `config`), and every nested `METHOD_*` region through the
  trailing blank line before the next top-level statement. The
  `CLASS_Yascheduler` `# endregion` comes AFTER the last nested
  `METHOD_queue_get_task` `# endregion`. For `FUNC__task_to_dict`: the
  `def _task_to_dict(...)` line, the docstring (if any), the entire body,
  and the trailing blank line. A region that closes before its entity ends
  (e.g. wrapping only the contract comment) is a defect.
- Comment-only diff on the code side. No code logic, signature, decorator,
  docstring semantics, or import changes. Edits are `# region` /
  `# endregion` marker insertion and contract-field enrichment inside the
  marker block. The existing `__all__` lists, the `from .xxx import yyy`
  re-export lines, and the existing five `METHOD_*` regions in
  `entrypoints/client.py` are untouched.

## Capabilities

### New Capabilities

_None._

### Modified Capabilities

- `package-facades`: requirements slimmed to SHALL statements and behavior
  scenarios; implementation invariants (single-helper, marshalling-boundary,
  `.value` unwrap), design rationale (composition-root residence,
  subpackage-facade organization, symbol-keyed contract, no-compat-shim
  enumeration), 7 invented `SHALL NOT` negative-space enumerations, and
  code-detail leakage (`__all__` literal, `import-linter` version pin)
  relocated out of the spec text and into GRACE code contracts on the
  nine facade modules. No package-facades behavior, scenario, public API,
  facade `__all__` membership, layer direction, INI key, DB schema, or
  import path is added, removed, or changed.

## Impact

- **Specs**: `openspec/specs/package-facades/spec.md` rewritten — every
  requirement trimmed to behavioral SHALL + scenarios; pre/post scenario
  count MUST remain 43 → 43 (5 scenarios shed trailing negative-space tails
  in their THEN clauses: `yascheduler.shared imports only stdlib and
  third-party` drops the "— never from any other `yascheduler` layer"
  restatement; `entrypoints CLI module uses relative imports` drops the
  "; `show_nodes` and `submit` are NOT re-exported by the facade" absent-
  re-export enumeration; `infra/cli/ does not exist` drops the "; the
  `daemonize` module has moved to the entrypoints layer" historical note;
  `pyproject.toml contains required keys` drops the "; no `forbidden`
  contract entry exists" absent-contract enumeration; `yascheduler.shared
  contains only cross-layer typing shims` drops the "— no domain entities,
  no use-case orchestration, no I/O" negative-space enumeration — the
  invariant moves to `yascheduler/shared/__init__.py` MODULE_CONTRACT
  INVARIANTS). All 7 enumerated negative-space prohibition items from Why
  § 3 (5 in requirement bodies + 2 in scenario THEN tails) are removed.
  The 2 genuine `SHALL NOT` system rules are preserved verbatim
  (`yascheduler.shared SHALL NOT import from any other layer` in R3, and
  `SHALL NOT change; their public task_id/jobs parameters stay int /
  list[int]` in Yascheduler facade public contract). The scenario headers
  and WHEN clauses are unchanged. `openspec validate --all --json` must
  still pass after the change.
- **Code (markup only, no logic)**:
  - `yascheduler/__init__.py` — enrich `MODULE_CONTRACT` with `INVARIANTS`
    (public surface is exactly the symbols in `__all__`) + `RATIONALE`
    (why the public contract is keyed on the resolvable symbol, not on
    the file path).
  - `yascheduler/entrypoints/__init__.py` — enrich `MODULE_CONTRACT` with
    `INVARIANTS` (cross-layer sole-public-surface rule) + `RATIONALE`
    (why one layer facade).
  - `yascheduler/entrypoints/client.py` — add new `CLASS_Yascheduler`
    region enclosing the full class; add new `FUNC__task_to_dict` region
    enclosing the full helper; enrich existing `MODULE_CONTRACT` and the
    five `METHOD_*` regions with `INVARIANTS` / `ENSURES` / `RATIONALE`
    that absorbs the spec's single-helper / marshalling-boundary / dict-
    shape / import-path-equivalence prose. Comment-only diff. No `# region`
    / `# endregion` on the existing five `METHOD_*` regions is moved.
  - `yascheduler/entrypoints/di.py` — enrich `MODULE_CONTRACT` with
    `RATIONALE` (why the composition root lives in entrypoints).
  - `yascheduler/client.py` — enrich `MODULE_CONTRACT` with `INVARIANTS`
    (`__all__ = ["Yascheduler"]`, no business logic, `Config` import raises
    `ImportError`) + `RATIONALE` (why the shim exists).
  - `yascheduler/shared/__init__.py` — enrich `MODULE_CONTRACT` with
    `INVARIANTS` (typing-shims-only contents).
  - `yascheduler/infra/__init__.py` — enrich `MODULE_CONTRACT` with
    `INVARIANTS` (subpackage facades are internal organization; cross-layer
    consumers import via this layer facade only) + `RATIONALE` (why one
    layer facade).
  - `yascheduler/application/__init__.py` — enrich `MODULE_CONTRACT` with
    `INVARIANTS` (sole-public-surface rule).
  - `yascheduler/domain/__init__.py` — already carries tight
    `PURPOSE` / `SCOPE` / `INVARIANTS` / `KEYWORDS`; leave it (the existing
    INVARIANTS `__all__ lists every re-exported symbol` already absorbs the
    relocated prose).
- **Tests**: no change. The 43 existing scenarios in the trimmed spec
  remain the acceptance criteria; the existing facade tests
  (`tests/unit/test_application_no_adapter_imports.py`,
  `test_log_scope_discipline.py`, `test_di_no_casts.py`, plus the
  existing public-API / facade import-resolution tests) already assert
  them. A passing `uv run pytest -m unit` run after the change is the
  regression guard. `uv run lint-imports` continues to enforce the R3
  layer direction; no contract is added or removed.
- **Public surface**: none. No CLI command, console_script, INI config key,
  DB schema, public API, facade `__all__` membership, log-format, or import-
  path change in the diff. The diff is `# region` / `# endregion` markup +
  contract-field enrichment + spec text trim only.
- **Pilot scope**: this change ONLY dehydrates the `package-facades` spec.
  Other specs (`logging`, `orchestrator`, `cloud`, `cli`,
  `config-value-objects`, `db-migrations`, `dependency-injection`,
  `e2e-testing`, etc.) are explicitly out of scope. Follows the pattern set
  by `logging-spec-trim`, `cloud-spec-trim`, `orchestrator-spec-trim`,
  `config-value-objects-spec-trim`, `db-migrations-spec-trim`,
  `dependency-injection-spec-trim`, and `e2e-testing-spec-trim`.
- **Non-goals**:
  - No change to any package-facades behavior, layer direction, facade
    `__all__` membership, public API dict shape, or import path.
  - No spec split; all 12 trimmed requirements remain in the
    `package-facades` capability.
  - No markup added to `tests/` (test files are out of trim scope).
  - No markup additions to non-facade modules — the trim touches only the
    nine facade files named above. Layer-direction enforcement in
    `pyproject.toml` is unchanged (no `forbidden` contract is added or
    removed; the `layers` contract layers list and version pin are
    untouched).
  - No rewrite of `_task_to_dict` extraction logic, no signature change to
    any `Yascheduler` method, no change to any `__all__` list, no change
    to any re-export statement.
